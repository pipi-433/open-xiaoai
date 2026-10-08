"""Optional literal STT name corrections, not acoustic/model hotword biasing."""
import json
import logging
import os
from pathlib import Path
import re

LOGGER = logging.getLogger(__name__)
# Guard common control/negation tokens, Arabic numbers, and Chinese quantities.
# This deliberately isn't a claim of complete semantic safety for arbitrary rules.
_ACTIONS = re.compile(r'打开|关闭|开启|关掉|启动|停止|取消|暂停|继续|不要|别|不|没|勿|开|关')
_NUMBERS = re.compile(r'\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万点]+(?=度|分|秒|时|点|个|盏|档|级)|(?<=到)[零〇一二两三四五六七八九十百千万]+')


def _protected(text):
    return _ACTIONS.findall(text), _NUMBERS.findall(text)


def correct_text(text, file=None):
    """Single-pass exact/literal replacement; empty/broken tables change nothing."""
    if not isinstance(text, str) or not text:
        return text
    file = Path(file or os.getenv('OPEN_XIAOAI_CORRECTIONS_FILE') or
                Path(__file__).resolve().parents[1] / 'asr-corrections.json')
    if file.stem != 'asr-corrections.local':
        local = file.with_name('asr-corrections.local.json')
        if local.is_file():
            file = local
    try:
        if not file.is_file():
            return text
        if file.stat().st_size > 65536:
            raise ValueError('table too large')
        config = json.loads(file.read_text(encoding='utf-8-sig'))
        if not isinstance(config, dict) or config.get('version') != 1:
            raise ValueError('invalid schema')
        if config.get('enabled') is not True:
            return text
        rules = config.get('rules', [])
        if not isinstance(rules, list) or len(rules) > 256:
            raise ValueError('invalid rules')
        exact, names = {}, {}
        for rule in rules:
            if not isinstance(rule, dict):
                raise ValueError('invalid rule')
            source, target = rule.get('source'), rule.get('target')
            mode = rule.get('mode', 'exact')
            if (not isinstance(source, str) or not isinstance(target, str) or
                    not 2 <= len(source) <= 80 or not 1 <= len(target) <= 80 or
                    not source.strip() or not target.strip() or
                    '\n' in source + target or '\r' in source + target or mode not in ('exact', 'name')):
                raise ValueError('invalid rule fields')
            if _protected(source) != _protected(target):
                raise ValueError('rule changes protected tokens')
            mapping = exact if mode == 'exact' else names
            if source in mapping and mapping[source] != target:
                raise ValueError('ambiguous rule')
            if source in (names if mode == 'exact' else exact) and (names if mode == 'exact' else exact)[source] != target:
                raise ValueError('ambiguous rule mode')
            mapping[source] = target
        corrected = exact.get(text)
        if corrected is None and names:
            pattern = re.compile('|'.join(re.escape(source) for source in sorted(names, key=lambda s: (-len(s), s))))
            corrected = pattern.sub(lambda match: names[match.group(0)], text)
        corrected = text if corrected is None else corrected
        return corrected if _protected(text) == _protected(corrected) else text
    except (OSError, ValueError, TypeError):
        # Do not log private words or utterances; bad local config must not
        # break voice service or rewrite text through a partially loaded table.
        LOGGER.warning('STT correction table unavailable or invalid; original text kept')
        return text
