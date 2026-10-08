import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('build_verified', PACKAGE / 'src/build_verified.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class BuildGuards(unittest.TestCase):
    def test_profile_matches_current_patch_bytes(self):
        profile = json.loads((PACKAGE / 'profiles/LX06_1.94.14.json').read_text())
        for file, digest in profile['patches'].items():
            self.assertEqual(builder.digest(PACKAGE / 'patches' / file), digest)

    def test_wrong_ota_size_and_hash_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            ota = Path(directory) / 'input.bin'
            ota.write_bytes(b'wrong firmware')
            profile = {'model': 'LX06', 'version': '1.94.14', 'otaBytes': 123}
            with self.assertRaisesRegex(ValueError, 'size mismatch'):
                builder.verify_inputs(ota, profile)
            profile.update(otaBytes=ota.stat().st_size, otaSHA256='0' * 64)
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                builder.verify_inputs(ota, profile)

    def test_wrong_version_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Only the audited'):
            builder.verify_inputs(Path('unused'), {'model': 'OH2P', 'version': '1.94.14'})

    def test_audio_target_must_be_unique(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / 'audio.so'
            library.write_bytes(b'hw:0,3\0hw:0,3\0')
            profile = {'audioLibrarySHA256': builder.digest(library), 'audioLibraryOffset': 0}
            with self.assertRaisesRegex(ValueError, 'unique'):
                builder.patch_audio(library, profile)

    def test_secret_file_is_exclusive_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'secret.json'
            builder.write_private(file, 'test only')
            with self.assertRaises(FileExistsError):
                builder.write_private(file, 'overwrite')
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
