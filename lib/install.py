#!/usr/bin/env python3
"""Idempotent XFCE installation with private, reversible migration backups."""
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


try:
    from . import setup_wizard as setup
except ImportError:
    import setup_wizard as setup


def preflight(plan):
    link = plan['home']/'.local/bin/sttanywhere'
    if link.exists() or link.is_symlink():
        if not link.is_symlink() or link.resolve() != ROOT/'bin/sttanywhere':
            raise ValueError(f'Refusing to replace unrelated executable: {link}')
    if plan['no_bind']:
        return '', ''
    if not os.environ.get('DISPLAY'):
        raise ValueError('Run from the Xubuntu desktop or use --no-bind to prepare config only')
    for binary in setup.DEPENDENCIES:
        if not shutil.which(binary):
            raise ValueError(f'Missing {binary}; rerun with --deps or --no-bind')
    listing = call('xfconf-query', '-c', 'xfce4-keyboard-shortcuts', '-lv').stdout
    shortcut = '/commands/custom/'+plan['config']['shortcut']
    for line in listing.splitlines():
        fields = line.split(None, 1)
        if len(fields) == 2 and fields[0] == shortcut:
            value = fields[1]
            if 'xhisper' not in value.lower() and str(ROOT/'bin/sttanywhere') not in value:
                raise ValueError(f'{shortcut} belongs to another command; choose another shortcut')
    units = call('systemctl', '--user', 'list-unit-files', '--no-legend', '--no-pager', check=False)
    if units.returncode:
        raise ValueError('Cannot connect to user systemd; run from your desktop session or use --no-bind')
    return listing, units.stdout


def apply(plan, listing, unit_listing):
    home, config_home, dest = plan['home'], plan['config_home'], plan['dest']
    cfg = plan['config']
    config_path, credentials = dest/'config.json', dest/'credentials.env'
    dest.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    backup = dest/'backups'/datetime.datetime.now().strftime('%Y%m%dT%H%M%S%f')
    backup.mkdir(parents=True, mode=0o700)
    for path in (home/'.env', config_home/'xhisper', config_path, credentials, config_home/'xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml'):
        if path.is_dir():
            shutil.copytree(path, backup/path.name)
        elif path.is_file():
            shutil.copy2(path, backup/path.name)
            os.chmod(backup/path.name, 0o600)
    print(f'Recovery backup: {backup}')
    # Atomic private replacements; unrelated settings and key assignments survive.
    atomic_write(config_path, json.dumps(cfg, indent=2)+'\n')
    atomic_write(credentials, plan['credentials'])
    bindir = home/'.local/bin'
    bindir.mkdir(parents=True, exist_ok=True)
    link = bindir/'sttanywhere'
    if link.exists() or link.is_symlink():
        if not link.is_symlink() or link.resolve() != ROOT/'bin/sttanywhere':
            raise ValueError(f'Refusing to replace unrelated executable: {link}')
    else:
        link.symlink_to(ROOT/'bin/sttanywhere')
    if plan['no_bind']:
        print(f'Configuration prepared; xhisper untouched. Private backups: {backup}')
        return
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
    disabled = []
    for line in unit_listing.splitlines():
        unit = line.split()[0] if line.split() else ''
        if 'xhisper' in unit.lower():
            result = call('systemctl', '--user', 'disable', '--now', unit, check=False)
            if result.returncode:
                raise ValueError(f'Cannot disable {unit}; refusing to enable competing shortcut')
            # A local unit cannot be masked in place; disabling plus stopping is
            # sufficient for login, with its previous unit listing saved below.
            disabled.append(unit)
    (backup/'systemd-units.txt').write_text(unit_listing)
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
    print('Credential: '+('present (hidden)' if plan['credential_present'] else 'missing; set credentials.env before dictating'))

def atomic_write(path, text):
    import tempfile
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.setup-')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def main():
    os.umask(0o077)
    args = setup.parser().parse_args()
    plan = setup.plan(ROOT, args)
    setup.preview(plan)
    if plan['dry_run']:
        print('Dry run complete. Nothing changed.')
        return
    if plan['deps'] and not shutil.which('apt-get'):
        raise ValueError('--deps supports Debian/Ubuntu apt-get; install dependencies manually on other systems')
    # Check conflicts before confirmation whenever dependencies are available.
    if not plan['deps']:
        preflight(plan)
    if plan['interactive'] and setup.ask('Apply this plan? Type yes to continue', 'no').lower() != 'yes':
        raise setup.Cancelled()
    if plan['deps']:
        subprocess.run(['sudo','apt-get','update'],check=True)
        subprocess.run(['sudo','apt-get','install','-y',*setup.PACKAGES],check=True)
    # Repeat the read-only check just before applying; never overwrite a changed binding.
    listing, unit_listing = preflight(plan)
    apply(plan, listing, unit_listing)
    print('Ready. Run sttanywhere doctor for local diagnostics. No provider request was made.')


if __name__ == '__main__':
    try:
        main()
    except (setup.Cancelled, EOFError):
        print('Setup cancelled. No installation changes applied.')
        sys.exit(0)
    except KeyboardInterrupt:
        print('Setup interrupted. If apply had started, review the private backups before retrying.')
        sys.exit(130)
    except Exception as exc:
        print(f'Install failed: {exc}', file=sys.stderr)
        sys.exit(1)
