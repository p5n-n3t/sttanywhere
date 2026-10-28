#!/usr/bin/env python3
"""Idempotent XFCE installation with private, reversible migration backups."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]

def call(*args, check=True):
    return subprocess.run(args, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-bind', action='store_true', help='Prepare config only, leave xhisper and shortcuts untouched')
    args = parser.parse_args()
    os.umask(0o077)
    home = Path.home()
    config_home = Path(os.environ.get('XDG_CONFIG_HOME', home/'.config'))
    dest = config_home/'sttanywhere'
    dest.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    config_path = dest/'config.json'
    credentials = dest/'credentials.env'
    backup = dest/'backups'/datetime.datetime.now().strftime('%Y%m%dT%H%M%S%f')
    backup.mkdir(parents=True, mode=0o700)
    for path in (home/'.env', config_home/'xhisper', config_path, credentials, config_home/'xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml'):
        if path.is_dir():
            shutil.copytree(path, backup/path.name)
        elif path.is_file():
            shutil.copy2(path, backup/path.name)
            os.chmod(backup/path.name, 0o600)
    cfg = json.loads(config_path.read_text()) if config_path.exists() else json.loads((ROOT/'config/config.example.json').read_text())
    # Read data rather than source an arbitrary old shell startup file.
    key = os.environ.get('GROQ_API_KEY', '')
    if not key and (home/'.env').exists():
        for line in (home/'.env').read_text().splitlines():
            match = re.match(r'^\s*(?:export\s+)?GROQ_API_KEY\s*=\s*(.*)$', line)
            if match:
                values = shlex.split(match[1], comments=True)
                if len(values) == 1:
                    key = values[0]
    if not credentials.exists():
        if key:
            credentials.write_text('# Private; never commit. Environment used by the global shortcut.\nGROQ_API_KEY='+shlex.quote(key)+'\n')
        else:
            credentials.write_text('# Add GROQ_API_KEY here or export it in your desktop session.\n')
    os.chmod(credentials, 0o600)
    config_path.write_text(json.dumps(cfg, indent=2)+'\n')
    os.chmod(config_path, 0o600)
    bindir = home/'.local/bin'
    bindir.mkdir(parents=True, exist_ok=True)
    link = bindir/'sttanywhere'
    if link.exists() or link.is_symlink():
        if not link.is_symlink() or link.resolve() != ROOT/'bin/sttanywhere':
            raise ValueError(f'Refusing to replace unrelated executable: {link}')
    else:
        link.symlink_to(ROOT/'bin/sttanywhere')
    if args.no_bind:
        print(f'Configuration prepared; xhisper untouched. Private backups: {backup}')
        return
    if not os.environ.get('DISPLAY'):
        raise ValueError('Run installation from the Xubuntu desktop (DISPLAY unset)')
    for binary in ('xdotool', 'xprop', 'xclip', 'ffmpeg', 'notify-send', 'xfconf-query', 'pactl'):
        if not shutil.which(binary):
            raise ValueError(f'Missing {binary}; run ./install.sh --deps')
    # Confirm live XFCE connection before modifying old services or bindings.
    listing = call('xfconf-query', '-c', 'xfce4-keyboard-shortcuts', '-lv').stdout
    shortcut = '/commands/custom/'+cfg.get('shortcut', '<Alt>x')
    old_bindings = []
    occupied = None
    for line in listing.splitlines():
        fields = line.split(None, 1)
        if len(fields) != 2:
            continue
        prop, value = fields
        if prop == shortcut:
            occupied = value
        if 'xhisper' in value.lower() or str(ROOT/'bin/sttanywhere') in value:
            old_bindings.append((prop, value))
    if occupied and 'xhisper' not in occupied.lower() and str(ROOT/'bin/sttanywhere') not in occupied:
        raise ValueError(f'{shortcut} belongs to another command; change shortcut in config.json first')
    (backup/'shortcuts.json').write_text(json.dumps(old_bindings, indent=2))
    units = call('systemctl', '--user', 'list-unit-files', '--no-legend', '--no-pager', check=False)
    if units.returncode:
        raise ValueError('Cannot connect to user systemd; run from your desktop session')
    disabled = []
    for line in units.stdout.splitlines():
        unit = line.split()[0] if line.split() else ''
        if 'xhisper' in unit.lower():
            result = call('systemctl', '--user', 'disable', '--now', unit, check=False)
            if result.returncode:
                raise ValueError(f'Cannot disable {unit}; refusing to enable competing shortcut')
            # A local unit cannot be masked in place; disabling plus stopping is
            # sufficient for login, with its previous unit listing saved below.
            disabled.append(unit)
    (backup/'systemd-units.txt').write_text(units.stdout)
    autostart = config_home/'autostart'
    if autostart.exists():
        for path in autostart.glob('*.desktop'):
            text = path.read_text()
            if 'xhisper' in text.lower():
                shutil.copy2(path, backup/path.name)
                text = re.sub(r'^Hidden=.*\n?', '', text, flags=re.M)
                path.write_text(text.replace('[Desktop Entry]', '[Desktop Entry]\nHidden=true', 1))
    # Kill only exact old executable names or recorders using xhisper files.
    uid = os.getuid()
    killed = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid != uid:
                continue
            argv = proc.joinpath('cmdline').read_bytes().split(b'\0')
            argv = [a.decode(errors='replace') for a in argv if a]
            names = [Path(a).name for a in argv[:2]]
            old = any(n in ('xhisper', 'xhispertool', 'xhispertoold') for n in names)
            recorder = names and names[0] in ('pw-record', 'parec', 'ffmpeg', 'arecord') and any('/tmp/xhisper' in a for a in argv)
            if old or recorder:
                os.kill(int(proc.name), signal.SIGTERM)
                killed.append(int(proc.name))
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    if killed:
        time.sleep(.3)
        for pid in killed:
            try:
                argv = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
                names = [Path(a.decode(errors='replace')).name for a in argv[:2] if a]
                # Recheck executable identity so a reused PID is never killed.
                if any(n in ('xhisper', 'xhispertool', 'xhispertoold') for n in names) or (names and names[0] in ('pw-record', 'parec', 'ffmpeg', 'arecord') and any(b'/tmp/xhisper' in a for a in argv)):
                    os.kill(pid, signal.SIGKILL)
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                pass
    for prop, _ in old_bindings:
        call('xfconf-query', '-c', 'xfce4-keyboard-shortcuts', '-p', prop, '-r', '-R')
    command = shlex.quote(str(ROOT/'bin/sttanywhere'))+' toggle'
    call('xfconf-query', '-c', 'xfce4-keyboard-shortcuts', '-p', shortcut, '-n', '-t', 'string', '-s', command)
    actual = call('xfconf-query', '-c', 'xfce4-keyboard-shortcuts', '-p', shortcut).stdout.strip()
    if actual != command:
        raise ValueError('Shortcut verification failed')
    (backup/'migration.json').write_text(json.dumps({'disabled_units': disabled, 'stopped_pids': killed, 'shortcut': shortcut, 'new_command': command}, indent=2))
    print(f'Installed STT Anywhere at {ROOT}; shortcut {cfg.get("shortcut", "<Alt>x")}')
    print(f'Private backups and migration report: {backup}')
    print('Credential: '+('present' if key or 'GROQ_API_KEY=' in credentials.read_text() else 'missing; set credentials.env'))

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Install failed: {exc}', file=sys.stderr)
        sys.exit(1)
