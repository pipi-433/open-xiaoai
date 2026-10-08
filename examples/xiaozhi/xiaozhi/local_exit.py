"""Exact phrase matching only; never treat a device-control sentence as exit."""
import re


def normalize(text):
    return re.sub(r'[\s，。！？!?、,.;；：:]+', '', text).lower() if isinstance(text, str) else ''


def is_local_exit_command(text, config):
    normalized = normalize(text)
    commands = config.get('local_exit_commands', ())
    if not isinstance(commands, (list, tuple)):
        return False
    return bool(normalized) and any(normalized == normalize(command) for command in commands)
