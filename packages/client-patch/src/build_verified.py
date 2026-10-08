#!/usr/bin/env python3
"""Offline, profile-pinned LX06 rootfs builder. Never connects to a speaker."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import subprocess
import tempfile

PACKAGE = Path(__file__).resolve().parents[1]
CHANGED_FILES = {
    'bin/flash.sh', 'bin/ota', 'etc/asound.conf', 'etc/asound.conf.dts',
    'etc/init.d/dropbear', 'etc/init.d/wireless', 'etc/inittab',
    'etc/pam.d/common-auth', 'etc/rc.local', 'etc/shadow',
    'usr/lib/libxaudio_engine.so',
}


def digest(file, algorithm='sha256'):
    value = hashlib.new(algorithm)
    with Path(file).open('rb') as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def verify_inputs(ota, profile):
    if profile['model'] != 'LX06' or profile['version'] != '1.94.14':
        raise ValueError('Only the audited LX06 1.94.14 profile is supported')
    if ota.stat().st_size != profile['otaBytes']:
        raise ValueError('OTA size mismatch')
    if digest(ota) != profile['otaSHA256'] or digest(ota, 'md5') != profile['otaMD5']:
        raise ValueError('OTA checksum mismatch')
    for relative, expected in profile['patches'].items():
        file = (PACKAGE / 'patches' / relative).resolve()
        if not file.is_relative_to((PACKAGE / 'patches').resolve()) or digest(file) != expected:
            raise ValueError('Patch source changed: ' + relative)


def patch_audio(library, profile):
    if digest(library) != profile['audioLibrarySHA256']:
        raise ValueError('Unexpected audio library')
    data = library.read_bytes()
    needle, replacement = b'hw:0,3\0', b'noop\0\0\0'
    if data.count(needle) != 1 or data.index(needle) != profile['audioLibraryOffset']:
        raise ValueError('Audio target must be unique at the verified offset')
    offset = data.index(needle)
    library.write_bytes(data[:offset] + replacement + data[offset + len(needle):])


def snapshot(root):
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            file = Path(directory) / name
            attrs = file.lstat()
            record = {'type': stat.S_IFMT(attrs.st_mode), 'mode': stat.S_IMODE(attrs.st_mode),
                      'uid': attrs.st_uid, 'gid': attrs.st_gid}
            if stat.S_ISREG(attrs.st_mode):
                record['sha256'] = digest(file)
            elif stat.S_ISLNK(attrs.st_mode):
                record['target'] = os.readlink(file)
            elif stat.S_ISCHR(attrs.st_mode) or stat.S_ISBLK(attrs.st_mode):
                record['device'] = attrs.st_rdev
            result[file.relative_to(root).as_posix()] = record
    return result


def run(args, **kwargs):
    result = subprocess.run(args, check=True, text=True, capture_output=True, **kwargs)
    return result.stdout


def write_private(file, text):
    fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as writer:
        writer.write(text)


def build(ota, output, profile):
    if os.geteuid() != 0:
        raise ValueError('Run as root on Linux/WSL to preserve device nodes and ownership')
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    # Keep an isolated Linux filesystem workdir, including on WSL. It can be
    # inspected after a failure; never recursively delete a user-supplied path.
    work = Path(tempfile.mkdtemp(prefix='open-xiaoai-verified-', dir='/var/tmp'))
    spec = importlib.util.spec_from_file_location('ota_extract', PACKAGE / 'src/extract.py')
    extract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extract)
    firmware = extract.Firmware(str(ota))
    try:
        # Full MD5 and SHA-256 were checked first; don't rely on a short hash
        # suffix in the filename. The existing extractor still checks CRC32.
        firmware.verify(ignore_hash=True)
        firmware.extract(str(work / 'segments'))
    finally:
        firmware.fd.close()
    image = work / 'segments/root.squashfs'
    version = (work / 'segments/mico_version').read_text()
    for key, expected in [('HARDWARE', profile['model']), ('ROM', profile['version'])]:
        if not re.search(r"option\s+" + key + r"\s+['\"]" + re.escape(expected) + r"['\"]", version):
            raise ValueError('Extracted model/version mismatch')
    if digest(image) != profile['rootfsSHA256']:
        raise ValueError('Unexpected rootfs')
    with image.open('rb') as reader:
        header = reader.read(96)
    if header[:4] != b'hsqs' or struct.unpack_from('<H', header, 20)[0] != 4:
        raise ValueError('Expected xz SquashFS')
    epoch, block_size = struct.unpack_from('<II', header, 8)
    if block_size != 131072:
        raise ValueError('Unexpected block size')
    original, patched = work / 'original', work / 'patched'
    run(['unsquashfs', '-processors', '2', '-no-progress', '-d', str(original), str(image)])
    run(['cp', '-a', str(original), str(patched)])
    password = secrets.token_urlsafe(24)
    password_hash = run(['openssl', 'passwd', '-1', '-salt', secrets.token_hex(4), '-stdin'], input=password + '\n').strip()
    write_private(output / 'SSH-CREDENTIALS.json', json.dumps({'username': 'root', 'password': password}, indent=2) + '\n')
    for relative in profile['patches']:
        text = (PACKAGE / 'patches' / relative).read_text().replace('{SSH_PASSWORD}', password_hash)
        command = ['patch', '--batch', '--forward', '--fuzz=0', '--no-backup-if-mismatch', '-p1']
        run(command + ['--dry-run'], input=text, cwd=patched)
        run(command, input=text, cwd=patched)
    patch_audio(patched / 'usr/lib/libxaudio_engine.so', profile)
    for relative in CHANGED_FILES:
        attrs = (original / relative).stat()
        os.utime(patched / relative, ns=(attrs.st_atime_ns, attrs.st_mtime_ns))
    before, after = snapshot(original), snapshot(patched)
    if before.keys() != after.keys() or {k for k in before if before[k] != after[k]} != CHANGED_FILES:
        raise ValueError('Unexpected changed files')
    for relative in CHANGED_FILES:
        if any(before[relative][key] != after[relative][key] for key in ('type', 'mode', 'uid', 'gid')):
            raise ValueError('Metadata changed: ' + relative)
    for relative in ('etc/init.d/dropbear', 'bin/ota', 'bin/flash.sh', 'etc/init.d/wireless', 'etc/rc.local'):
        run(['bash', '-n', str(patched / relative)])
    files = [output / 'LX06_1.94.14_patched.squashfs', work / 'repeated.squashfs']
    for file in files:
        run(['mksquashfs', str(patched), str(file), '-comp', 'xz', '-b', str(block_size),
             '-noappend', '-all-root', '-always-use-fragments', '-no-xattrs', '-no-exports',
             '-processors', '2', '-mem', '256M', '-no-progress', '-mkfs-time', str(epoch)])
        if file.stat().st_size >= profile['partitionLimitBytes']:
            raise ValueError('Patched image exceeds partition limit')
    if digest(files[0]) != digest(files[1]):
        raise ValueError('Repeated pack differs')
    unpacked = work / 'verified'
    run(['unsquashfs', '-processors', '2', '-no-progress', '-d', str(unpacked), str(files[0])])
    if snapshot(unpacked) != after:
        raise ValueError('Repacked content/metadata mismatch')
    manifest = {'model': profile['model'], 'version': profile['version'], 'otaSHA256': digest(ota),
                'patchedSHA256': digest(files[0]), 'patchedBytes': files[0].stat().st_size,
                'changedFiles': sorted(CHANGED_FILES), 'repackVerified': True, 'sameRunReproducible': True,
                'hardwareBootTest': 'NOT_PERFORMED_BY_THIS_BUILD', 'deviceFlashed': False}
    write_private(output / 'manifest.json', json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'status': 'OFFLINE_BUILD_VERIFIED', 'outputDirectory': str(output), 'workDirectory': str(work),
                      'passwordLocation': str(output / 'SSH-CREDENTIALS.json'), **manifest}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ota', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New, nonexistent directory')
    parser.add_argument('--check-only', action='store_true', help='Verify input hashes without extracting or building')
    args = parser.parse_args()
    profile = json.loads((PACKAGE / 'profiles/LX06_1.94.14.json').read_text())
    verify_inputs(args.ota.resolve(strict=True), profile)
    if args.check_only:
        print('Verified LX06 1.94.14 OTA and patch inputs; no firmware built or flashed')
    else:
        build(args.ota.resolve(), args.output.resolve(), profile)


if __name__ == '__main__':
    main()
