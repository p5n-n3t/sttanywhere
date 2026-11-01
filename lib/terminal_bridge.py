"""Opt-in background dictation for explicitly managed tmux terminals.

This adapter never focuses a window and never submits a line. It writes a marker
at the managed pane cursor, then requires the complete visible pane and cursor to
remain unchanged before replacing that marker. A changed pane is left alone.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid


def runtime_dir():
    path = Path(os.environ.get('STTANYWHERE_RUNTIME_DIR', f'/tmp/sttanywhere-{os.getuid()}'))
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('Unsafe STT Anywhere runtime directory')
    return path


def _proc_stat(pid):
    try:
        text = Path(f'/proc/{int(pid)}/stat').read_text()
        tail = text.rsplit(')', 1)[1].split()
        return {'state': tail[0], 'parent': int(tail[1]), 'pgrp': int(tail[2]),
                'tty': int(tail[4]), 'foreground': int(tail[5]), 'token': tail[19]}
    except (OSError, ValueError, IndexError, TypeError):
        return None


def process_token(pid):
    info = _proc_stat(pid)
    return info['token'] if info else None


def alive(pid, token):
    info = _proc_stat(pid)
    return bool(info and token and info['token'] == str(token) and info['state'] != 'Z')


def is_descendant(pid, ancestor):
    pid, ancestor = int(pid or 0), int(ancestor or 0)
    seen = set()
    while pid and pid not in seen:
        if pid == ancestor:
            return True
        seen.add(pid)
        info = _proc_stat(pid)
        if not info:
            return False
        pid = info['parent']
    return False


def _private_json(path):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            return None
        return json.loads(path.read_text())
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _tmux(socket_name, *args, timeout=3):
    if not shutil.which('tmux'):
        raise ValueError('tmux is required for managed terminal dictation')
    result = subprocess.run(['tmux', '-L', socket_name, *map(str, args)],
                            text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise ValueError('Managed terminal is unavailable')
    return result.stdout.rstrip('\n')


def _pane_meta(reg):
    template = '#{pane_id}\t#{pane_tty}\t#{pane_pid}\t#{pane_current_command}\t#{cursor_x}\t#{cursor_y}\t#{pane_in_mode}'
    output = _tmux(reg['socket'], 'display-message', '-p', '-t', reg['pane'], template)
    values = output.split('\t')
    if len(values) != 7 or values[0] != reg['pane'] or values[6] == '1':
        raise ValueError('Managed terminal pane identity changed')
    pane_pid = int(values[2])
    token = process_token(pane_pid)
    if not token or token != str(reg.get('pane_token')):
        raise ValueError('Managed terminal process identity changed')
    pane_stat = _proc_stat(pane_pid)
    fg = _foreground(pane_stat['tty']) if pane_stat else None
    if not fg:
        raise ValueError('Could not identify foreground process in managed terminal')
    return {'id': values[0], 'tty': values[1], 'pid': pane_pid, 'command': values[3],
            'x': int(values[4]), 'y': int(values[5]), 'token': token,
            'foreground_pid': fg['pid'], 'foreground_token': fg['token']}


def _foreground(tty_nr):
    """Return the one foreground process-group leader attached to tty_nr."""
    found = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        info = _proc_stat(path.name)
        if info and info['tty'] == tty_nr and info['pgrp'] == info['foreground'] and int(path.name) == info['pgrp']:
            found.append({'pid': int(path.name), 'token': info['token']})
    return found[0] if len(found) == 1 else None


def _snapshot(reg):
    meta = _pane_meta(reg)
    screen = _tmux(reg['socket'], 'capture-pane', '-p', '-t', reg['pane'])
    data = (screen + '\0' + str(meta['x']) + ':' + str(meta['y']) + '\0' +
            str(meta['pid']) + ':' + meta['token'] + '\0' + meta['command'] + '\0' +
            str(meta['foreground_pid']) + ':' + meta['foreground_token']).encode()
    return hashlib.sha256(data).hexdigest(), meta, screen


def _wait_screen(reg, expected_rows, cursor, foreground_pid, foreground_token, timeout=0.6):
    deadline = time.monotonic() + timeout
    last = None
    while True:
        digest, meta, screen = _snapshot(reg)
        rows = screen.splitlines()
        last = (digest, meta, screen)
        if ([row.rstrip(' ') for row in rows] == [row.rstrip(' ') for row in expected_rows] and [meta['x'], meta['y']] == cursor
                and meta['foreground_pid'] == foreground_pid
                and meta['foreground_token'] == foreground_token):
            return last
        if time.monotonic() >= deadline:
            raise ValueError('Could not verify unchanged terminal input; result kept on clipboard')
        time.sleep(0.025)


def _registrations():
    base = runtime_dir()
    for path in base.glob('terminal-*.json'):
        reg = _private_json(path)
        if reg and reg.get('uid') == os.getuid() and alive(reg.get('owner_pid'), reg.get('owner_token')):
            yield path, reg


def discover(window_pid, window_id=None):
    """Return the single live managed pane owned below this terminal window."""
    matches = []
    for path, reg in _registrations():
        if window_id and reg.get('window_id') and str(window_id) != str(reg['window_id']):
            continue
        if is_descendant(window_pid, reg.get('owner_pid')) or is_descendant(reg.get('owner_pid'), window_pid):
            try:
                _pane_meta(reg)
            except (ValueError, OSError, subprocess.SubprocessError):
                continue
            matches.append((path, reg))
    if len(matches) > 1:
        raise ValueError('More than one managed terminal matches this window')
    return matches[0] if matches else (None, None)


def _registered_anchor(anchor):
    path = Path(anchor.get('registry', ''))
    if path.parent != runtime_dir() or not path.name.startswith('terminal-'):
        raise ValueError('Terminal anchor is not registered')
    reg = _private_json(path)
    if not reg or not alive(reg.get('owner_pid'), reg.get('owner_token')) or reg.get('owner_token') != anchor.get('registry_token'):
        raise ValueError('Managed terminal registration expired')
    if reg.get('socket') != anchor.get('socket') or reg.get('pane') != anchor.get('pane'):
        raise ValueError('Managed terminal registration changed')
    return reg


def replace(anchor, replacement):
    if any(ch in replacement for ch in '\r\n\t') or any(not ch.isascii() or ord(ch) < 32 or ord(ch) == 127 for ch in replacement):
        raise ValueError('Terminal result contains unsupported characters; kept on clipboard')
    if anchor.get('kind') == 'shell':
        return _shell_replace(anchor, replacement)
    if anchor.get('kind') != 'tmux':
        raise ValueError('Unsupported terminal anchor')
    reg = _registered_anchor(anchor)
    digest, meta, screen = _snapshot(reg)
    if digest != anchor.get('snapshot') or meta['token'] != anchor.get('pane_token'):
        raise ValueError('Managed terminal input or output changed; result kept on clipboard')
    marker = anchor.get('marker', '')
    if not marker:
        raise ValueError('Terminal marker is missing')
    rows = screen.splitlines()
    x, y = meta['x'], meta['y']
    if y < len(rows):
        rows[y] = rows[y].ljust(x)
    if y >= len(rows) or not rows[y][:x].endswith(marker):
        raise ValueError('Terminal marker is no longer immediately before the cursor')
    # Recheck the foreground process token immediately before modifying input.
    if meta['foreground_pid'] != anchor.get('foreground_pid') or meta['foreground_token'] != anchor.get('foreground_token'):
        raise ValueError('Terminal foreground process changed; result kept on clipboard')
    _tmux(reg['socket'], 'send-keys', '-t', reg['pane'], '-N', str(len(marker)), 'BSpace')
    expected_rows = list(rows)
    expected_rows[y] = rows[y][:x-len(marker)] + rows[y][x:]
    after_delete_hash, after_delete_meta, after_delete = _wait_screen(
        reg, expected_rows, [x-len(marker), y], meta['foreground_pid'], meta['foreground_token'])
    if ([r.rstrip(' ') for r in after_delete.splitlines()] != [r.rstrip(' ') for r in expected_rows] or after_delete_meta['x'] != x-len(marker)
            or after_delete_meta['y'] != y or after_delete_meta['foreground_token'] != meta['foreground_token']):
        raise ValueError('Terminal changed during marker removal; result kept on clipboard')
    if replacement:
        _tmux(reg['socket'], 'send-keys', '-t', reg['pane'], '-l', '--', replacement)
    expected_result_rows = list(expected_rows)
    expected_result_rows[y] = expected_rows[y][:x-len(marker)] + replacement + expected_rows[y][x-len(marker):]
    after_hash, after_meta, after_screen = _wait_screen(
        reg, expected_result_rows, [x-len(marker)+len(replacement), y], meta['foreground_pid'], meta['foreground_token'])
    return {**anchor, 'marker': replacement, 'snapshot': after_hash,
            'cursor': [after_meta['x'], after_meta['y']], 'command': after_meta['command'],
            'foreground_pid': after_meta['foreground_pid'], 'foreground_token': after_meta['foreground_token'],
            'screen': after_screen}


def _shell_request(path, request, timeout=2):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(path))
        client.sendall((json.dumps(request) + '\n').encode())
        data = bytearray()
        while b'\n' not in data and len(data) < 65536:
            chunk = client.recv(4096)
            if not chunk:
                break
            data.extend(chunk)
    if b'\n' not in data:
        raise ValueError('Shell terminal integration did not respond; result kept on clipboard')
    response = json.loads(bytes(data).split(b'\n', 1)[0])
    if response.get('id') != request['id'] or not response.get('ok'):
        raise ValueError(response.get('error', 'Shell terminal anchor is no longer valid'))
    return response


def _shell_registry(context):
    base = runtime_dir()
    matches = []
    for path in base.glob('shell-*.json'):
        reg = _private_json(path)
        if not reg or int(reg.get('pid', 0)) == 0 or not alive(reg.get('pid'), reg.get('process_token')):
            continue
        if reg.get('window_id') and context.get('window') and str(reg['window_id']) != str(context['window']):
            continue
        if is_descendant(context.get('window_pid'), reg['pid']) or is_descendant(reg['pid'], context.get('window_pid')):
            matches.append((path, reg))
    if len(matches) > 1:
        raise ValueError('More than one registered shell matches this window')
    return matches[0] if matches else (None, None)


def _shell_capture(context, marker):
    path, reg = _shell_registry(context)
    if not reg:
        return None
    current = _foreground(_proc_stat(reg['pid'])['tty']) if _proc_stat(reg['pid']) else None
    if not current or current['pid'] != reg['pid']:
        return None
    sock = path.with_suffix('.sock')
    request = {'id': uuid.uuid4().hex, 'op': 'capture', 'marker': marker}
    response = _shell_request(sock, request)
    return {'backend': 'terminal', 'kind': 'shell', 'registry': str(path),
            'registry_token': reg['process_token'], 'socket': str(sock),
            'pid': reg['pid'], 'process_token': reg['process_token'], 'marker': marker,
            'shell_anchor': response.get('anchor', {})}


def _shell_replace(anchor, replacement):
    path = Path(anchor.get('registry', ''))
    if path.parent != runtime_dir() or not path.name.startswith('shell-'):
        raise ValueError('Shell anchor is not registered')
    reg = _private_json(path)
    if not reg or reg.get('process_token') != anchor.get('registry_token') or not alive(reg.get('pid'), reg.get('process_token')):
        raise ValueError('Registered shell process changed; result kept on clipboard')
    info = _proc_stat(reg['pid'])
    current = _foreground(info['tty']) if info else None
    if not current or current['pid'] != reg['pid'] or current['token'] != anchor.get('process_token'):
        raise ValueError('Shell no longer owns terminal input; result kept on clipboard')
    request = {'id': uuid.uuid4().hex, 'op': 'replace',
               'anchor': {**anchor.get('shell_anchor', {}), 'marker': anchor.get('marker')},
               'replacement': replacement}
    _shell_request(anchor['socket'], request)
    return {**anchor, 'marker': replacement, 'shell_anchor': {'marker': replacement}}


def capture(context, marker):
    path, reg = discover(context.get('window_pid'), context.get('window'))
    if reg:
        digest, meta, screen = _snapshot(reg)
        _tmux(reg['socket'], 'send-keys', '-t', reg['pane'], '-l', '--', marker)
        rows = screen.splitlines()
        x, y = meta['x'], meta['y']
        if y >= len(rows):
            raise ValueError('Could not verify marker position in the managed terminal')
        expected_rows = list(rows)
        row = rows[y].ljust(x)
        expected_rows[y] = row[:x] + marker + row[x:]
        after, after_meta, after_screen = _wait_screen(
            reg, expected_rows, [x + len(marker), y], meta['foreground_pid'], meta['foreground_token'])
        if (after_meta['command'] != meta['command'] or after_meta['foreground_pid'] != meta['foreground_pid']):
            raise ValueError('Terminal foreground process changed during marker insertion')
        return {'backend': 'terminal', 'kind': 'tmux', 'registry': str(path),
                'registry_token': reg['owner_token'], 'socket': reg['socket'], 'pane': reg['pane'],
                'pane_token': meta['token'], 'marker': marker, 'snapshot': after,
                'cursor': [after_meta['x'], after_meta['y']], 'command': after_meta['command'],
                'foreground_pid': after_meta['foreground_pid'], 'foreground_token': after_meta['foreground_token'],
                'screen': after_screen}
    return _shell_capture(context, marker)


def start(command):
    """Run COMMAND (or the user's shell) in a private, attached tmux session."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError('sttanywhere-terminal requires an interactive terminal')
    if not command:
        command = [os.environ.get('SHELL', '/bin/zsh')]
    if not shutil.which('tmux'):
        raise ValueError('tmux is required; install it before using the terminal adapter')
    base = runtime_dir()
    instance = uuid.uuid4().hex[:12]
    socket_name = f'sttanywhere-{os.getuid()}-{instance}'
    session = f'stt-{instance}'
    registry_path = base / f'terminal-{os.getpid()}.json'
    try:
        _tmux(socket_name, 'new-session', '-d', '-s', session, '-x', '120', '-y', '40', shlex.join(command))
        _tmux(socket_name, 'set-option', '-g', 'remain-on-exit', 'on')
        pane = _tmux(socket_name, 'display-message', '-p', '-t', session, '#{pane_id}')
        pane_pid = int(_tmux(socket_name, 'display-message', '-p', '-t', pane, '#{pane_pid}'))
        reg = {'uid': os.getuid(), 'owner_pid': os.getpid(), 'owner_token': process_token(os.getpid()),
               'window_id': os.environ.get('WINDOWID'), 'socket': socket_name, 'session': session,
               'pane': pane, 'pane_pid': pane_pid, 'pane_token': process_token(pane_pid),
               'created': time.time(), 'command': command}
        if not reg['owner_token'] or not reg['pane_token']:
            raise ValueError('Could not establish managed terminal process identity')
        fd, temp = tempfile.mkstemp(prefix='.terminal-', dir=base)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(reg, stream)
            os.replace(temp, registry_path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return subprocess.call(['tmux', '-L', socket_name, 'attach-session', '-t', session])
    finally:
        registry_path.unlink(missing_ok=True)
        try:
            _tmux(socket_name, 'kill-server')
        except (ValueError, OSError, subprocess.SubprocessError):
            pass
