#!/usr/bin/env python3
"""Opt-in isolated X11 + Pulse loopback + LIVE Groq integration test.

Runs one billable transcription. Requires Xvfb, xfwm4, espeak, paplay,
Pulse/PipeWire, /usr/bin/python3 with tkinter, plus normal dependencies.
Never targets the user's display or speakers. python3 tests/integration_x11.py
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def wait_for(check, timeout=15):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(.1)
    raise AssertionError('Timed out waiting for integration condition')


def main():
    processes = []
    module = None
    env = os.environ.copy()
    env['XDG_RUNTIME_DIR'] = f'/run/user/{os.getuid()}'
    env['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path=/run/user/{os.getuid()}/bus'
    base = Path(tempfile.mkdtemp(prefix='sttanywhere-integration-'))
    os.chmod(base, 0o700)
    try:
        readfd, writefd = os.pipe()
        xvfb = subprocess.Popen(['Xvfb', '-displayfd', str(writefd), '-screen', '0', '1024x768x24', '-nolisten', 'tcp'], pass_fds=(writefd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(xvfb)
        os.close(writefd)
        with os.fdopen(readfd) as stream:
            display = stream.readline().strip()
        assert display.isdigit(), 'Xvfb did not allocate a display'
        env['DISPLAY'] = ':'+display
        env.pop('XAUTHORITY', None)
        wm = subprocess.Popen(['dbus-run-session', '--', 'xfwm4', '--replace', '--sm-client-disable', '--compositor=off'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(wm)
        wait_for(lambda: '_NET_ACTIVE_WINDOW' in subprocess.check_output(['xprop', '-root', '_NET_SUPPORTED'], env=env, text=True))
        sink = 'sttanywhere_test_'+str(os.getpid())
        module = subprocess.check_output(['pactl', 'load-module', 'module-null-sink', 'sink_name='+sink], env=env, text=True).strip()
        cfg = json.loads((Path.home()/'.config/sttanywhere/config.json').read_text())
        cfg.update(delivery_mode='legacy', provider='groq', audio_source=sink+'.monitor', auto_paste=True)
        config_path = base/'config.json'
        config_path.write_text(json.dumps(cfg))
        env['STTANYWHERE_CONFIG'] = str(config_path)
        textpath = base/'editor.txt'
        app = base/'editor.py'
        app.write_text('''import tkinter as tk
from pathlib import Path
import sys
root=tk.Tk(className="SttTestEditor")
root.title("STT Anywhere Integration Editor")
t=tk.Text(root);t.pack();t.focus_set()
def snapshot():
 Path(sys.argv[1]).write_text(t.get("1.0","end-1c"));root.after(30,snapshot)
snapshot();root.mainloop()
''')
        processes.append(subprocess.Popen(['/usr/bin/python3', str(app), str(textpath)], env=env))
        def xdo(*args):
            return subprocess.check_output(['xdotool', *args], env=env, text=True).strip()
        window = wait_for(lambda: xdo('search', '--name', '^STT Anywhere Integration Editor$').splitlines()[0] if textpath.exists() else None)
        xdo('windowactivate', '--sync', window)
        xdo('type', '--clearmodifiers', '--delay', '1', 'Before ')
        wait_for(lambda: textpath.read_text() == 'Before ')
        command = [str(ROOT/'bin/sttanywhere'), 'toggle']
        subprocess.run(command, env=env, check=True)
        wait_for(lambda: textpath.read_text() == 'Before (Recording....) ')
        audio = base/'speech.wav'
        subprocess.run(['espeak', '-w', str(audio), 'Speech to text anywhere is working. This is a test of voice dictation.'], check=True)
        subprocess.run(['paplay', '--device='+sink, str(audio)], env=env, check=True)
        time.sleep(.3)
        started = time.monotonic()
        subprocess.run(command, env=env, check=True)
        elapsed = time.monotonic()-started
        assert elapsed < 3, f'Stop blocked for {elapsed}s'
        active_base = Path('/tmp')/f'sttanywhere-{os.getuid()}'
        def finished():
            for statepath in active_base.glob('job-*/state.json'):
                state = json.loads(statepath.read_text())
                if state.get('window') == window and state.get('config',{}).get('audio_source') == sink+'.monitor':
                    if state['status'] == 'failed':
                        raise AssertionError(state.get('error'))
                    if state['status'] == 'done':
                        return statepath.parent
        job = wait_for(finished, 100)
        transcript = (job/'transcript.txt').read_text()
        try:
            wait_for(lambda: textpath.read_text() == 'Before '+transcript)
        except AssertionError:
            raise AssertionError(f'Editor mismatch: {textpath.read_text()!r}; expected {("Before "+transcript)!r}') from None
        assert 'speech' in transcript.lower() and 'dictation' in transcript.lower(), transcript
        clip = subprocess.check_output(['xclip', '-selection', 'clipboard', '-o'], env=env, text=True)
        assert clip == transcript
        assert not (job/'audio.wav').exists()
        assert not (active_base/'active.json').exists()
        report = {'result':'PASS', 'display':env['DISPLAY'], 'stop_return_seconds':round(elapsed,3), 'transcript':transcript, 'editor_text':textpath.read_text(), 'checks':['microphone loopback capture','recording placeholder exact','detached live Groq worker','19 BackSpace replacement','original prefix preserved','clipboard matches','successful audio removed']}
        print(json.dumps(report, indent=2))
    finally:
        if module:
            subprocess.run(['pactl', 'unload-module', module], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for proc in reversed(processes):
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(base)

if __name__ == '__main__':
    main()
