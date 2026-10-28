"""Conservative terminal foreground-process discovery and user paste rules."""
import os
from pathlib import Path
import re


def foreground_process(window_pid):
    """Return only an unambiguous foreground TTY command below the window PID.

    Multiple terminal tabs/PTYS are deliberately unknown, never guessed.
    """
    if not window_pid:
        return ''
    entries = {}
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            if path.stat().st_uid != os.getuid():
                continue
            tail = (path/'stat').read_text().rsplit(')', 1)[1].split()
            entries[int(path.name)] = {'parent': int(tail[1]), 'pgrp': int(tail[2]), 'tty': int(tail[4]), 'foreground': int(tail[5]), 'name': (path/'comm').read_text().strip()}
        except (OSError, ValueError, IndexError):
            continue
    descendants = {int(window_pid)}
    while True:
        extra = {pid for pid, item in entries.items() if item['parent'] in descendants}
        new = descendants | extra
        if new == descendants:
            break
        descendants = new
    foreground = {}
    for pid in descendants:
        item = entries.get(pid)
        if item and item['tty'] and item['pgrp'] == item['foreground']:
            foreground.setdefault(item['tty'], set()).add(item['name'])
    if len(foreground) != 1:
        return ''
    names = next(iter(foreground.values()))
    for name in names:
        if re.search('codex|claude', name, re.I):
            return name
    return next(iter(names)) if len(names) == 1 else ''


def paste_chord(cfg, context):
    for rule in cfg.get('paste_rules', []):
        matches = rule.get('match', {})
        if matches and all(re.search(pattern, str(context.get(field, '')), re.I) for field, pattern in matches.items()):
            return rule['chord']
    mode = cfg.get('paste_mode', 'auto')
    terminal = re.search(cfg.get('terminal_pattern', 'warp|terminal|kitty|xterm'), context.get('window_class', ''), re.I)
    return 'ctrl+shift+v' if mode == 'terminal' or (mode == 'auto' and terminal) else 'ctrl+v'
