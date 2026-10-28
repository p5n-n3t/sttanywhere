#!/usr/bin/env python3
"""Opt-in real XFCE terminal paste check on Xvfb; no provider call."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from integration_x11 import wait_for, ROOT


def main():
    procs = []
    env = os.environ.copy()
    with tempfile.TemporaryDirectory(prefix='sttanywhere-terminal-') as folder:
        base = Path(folder)
        try:
            readfd, writefd = os.pipe()
            procs.append(subprocess.Popen(['Xvfb', '-displayfd', str(writefd), '-screen', '0', '1024x768x24', '-nolisten', 'tcp'], pass_fds=(writefd,), stderr=subprocess.DEVNULL))
            os.close(writefd)
            with os.fdopen(readfd) as stream:
                env['DISPLAY'] = ':'+stream.readline().strip()
            env.pop('XAUTHORITY', None)
            procs.append(subprocess.Popen(['dbus-run-session', '--', 'xfwm4', '--replace', '--sm-client-disable', '--compositor=off'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            wait_for(lambda: '_NET_ACTIVE_WINDOW' in subprocess.check_output(['xprop', '-root', '_NET_SUPPORTED'], env=env, text=True))
            capture = base/'capture.sh'
            target = base/'terminal.txt'
            # read captures typed text as data, never executes the transcript.
            capture.write_text('#!/bin/bash\nIFS= read -r line\nprintf "%s" "$line" > "$1"\nsleep 60\n')
            procs.append(subprocess.Popen(['xfce4-terminal', '--disable-server', '--title=STT Anywhere Terminal Test', '--execute', '/bin/bash', str(capture), str(target)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            def xdo(*args):
                return subprocess.check_output(['xdotool', *args], env=env, text=True, stderr=subprocess.DEVNULL).strip()
            def getwindow():
                try:
                    return xdo('search', '--name', '^STT Anywhere Terminal Test$').splitlines()[0]
                except (subprocess.CalledProcessError, IndexError):
                    return None
            window = wait_for(getwindow)
            xdo('windowactivate', '--sync', window)
            xdo('type', '--clearmodifiers', '--delay', '1', 'Before (Transcribing....) ')
            job = base/'job'
            job.mkdir(mode=0o700)
            (job/'audio.wav').write_bytes(b'test audio')
            window_class = subprocess.check_output(['xprop', '-id', window, 'WM_CLASS'], env=env, text=True)
            (job/'state.json').write_text(json.dumps({'status':'transcribing', 'window':window, 'window_class':window_class, 'config':{'auto_paste':True,'delivery_mode':'legacy'}, 'profile':{}}))
            script = 'from lib import sttanywhere as s; import sys; s.transcribe=lambda *a:"Terminal paste works."; s.worker(sys.argv[1])'
            subprocess.run([sys.executable, '-c', script, str(job)], cwd=ROOT, env=env, check=True)
            assert json.loads((job/'state.json').read_text())['status'] == 'done'
            xdo('key', '--clearmodifiers', 'Return')
            wait_for(lambda: target.exists())
            actual = target.read_text()
            assert actual == 'Before Terminal paste works.', repr(actual)
            print(json.dumps({'result':'PASS','window_class':window_class.strip(),'terminal_text':actual,'checks':['real xfce4-terminal','ctrl+shift+v paste','19 BackSpace cleanup','prefix preserved'],'provider_call':False},indent=2))
        finally:
            for process in reversed(procs):
                process.terminate()
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()

if __name__ == '__main__':
    main()
