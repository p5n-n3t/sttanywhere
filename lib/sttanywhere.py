#!/usr/bin/env python3
"""X11 dictation controller. Python stdlib only; Bash is the public entrypoint."""
import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(os.environ.get('STTANYWHERE_CONFIG', Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'sttanywhere/config.json'))
RUNTIME = Path('/tmp') / f'sttanywhere-{os.getuid()}'
RECORDING = '(Recording....)'
TRANSCRIBING = '(Transcribing....)'


def notify(message, critical=False):
    if shutil.which('notify-send'):
        subprocess.run(['notify-send', '-a', 'STT Anywhere', '-u', 'critical' if critical else 'normal', 'STT Anywhere', message], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run(*args, **kwargs):
    return subprocess.check_output(list(args), **kwargs).decode().strip()


def load_config():
    with CONFIG.open() as f:
        cfg = json.load(f)
    profile = cfg['providers'][cfg['provider']]
    if profile['adapter'] not in ('openai', 'raw', 'json_base64', 'assemblyai'):
        raise ValueError('Unsupported adapter')
    if cfg.get('placeholder_padding', ' ') != ' ':
        raise ValueError('Exactly one padding space are required for 16/19 BackSpace counts')
    return cfg, profile


def key_for(profile):
    name = profile['api_key_env']
    value = os.environ.get(name, '')
    if not value:
        raise ValueError(f'Missing {name}. Set it in your environment or private credentials.env.')
    return value


def runtime():
    try:
        RUNTIME.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = RUNTIME.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('Unsafe runtime directory; expected an owned, private /tmp directory')
    return RUNTIME


def write_json(path, data):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.state-')
    with os.fdopen(fd, 'w') as f:
        json.dump(data, f)
    os.replace(name, path)


def proc_token(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


def alive(pid, token):
    if token is None or proc_token(pid) != token:
        return False
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    except FileNotFoundError:
        return False


def stop_recorder(state):
    pid = state['recorder_pid']
    if alive(pid, state['recorder_token']):
        os.killpg(pid, signal.SIGINT)
        for _ in range(100):
            if not alive(pid, state['recorder_token']):
                break
            # A zombie has already finalized its WAV.
            try:
                if Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] == 'Z':
                    break
            except FileNotFoundError:
                break
            time.sleep(.02)
        else:
            os.killpg(pid, signal.SIGKILL)


def xdo(*args):
    return run('xdotool', *map(str, args))


def activate(window):
    xdo('getwindowname', window)  # fail closed if target was closed
    xdo('windowactivate', '--sync', window)
    if xdo('getactivewindow') != str(window):
        raise ValueError('Could not focus original window')


def type_text(text):
    xdo('type', '--clearmodifiers', '--delay', '1', '--', text)


def replace_placeholder(window, count, replacement):
    activate(window)
    xdo('key', '--clearmodifiers', '--repeat', count, '--repeat-delay', '1', 'BackSpace')
    if replacement:
        type_text(replacement)


def endpoint(profile):
    value = profile['endpoint'].replace('${model}', profile.get('model', ''))
    value = os.path.expandvars(value)
    parsed = urllib.parse.urlparse(value)
    if '${' in value or parsed.scheme != 'https' or not parsed.netloc or parsed.username:
        raise ValueError('Provider endpoint must be a complete HTTPS URL without embedded credentials')
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Provider redirected request; refusing to forward credentials')


def request_json(url, key, data=None, content_type=None, timeout=90, bearer=True):
    headers = {'Authorization': ('Bearer ' if bearer else '') + key, 'User-Agent': 'STTAnywhere/1.0'}
    if content_type:
        headers['Content-Type'] = content_type
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=timeout) as response:
            body = response.read(8 * 1024 * 1024 + 1)
        if len(body) > 8 * 1024 * 1024:
            raise ValueError('Provider response is too large')
        return json.loads(body)
    except urllib.error.HTTPError as error:
        raise ValueError(f'Provider HTTP {error.code}; check credentials, endpoint, quota and audio format') from None
    except urllib.error.URLError:
        raise ValueError('Provider connection failed; check network and endpoint') from None


def multipart(audio, model, options):
    boundary = 'sttanywhere-' + uuid.uuid4().hex
    parts = []
    for name, value in {'model': model, **options}.items():
        if not re.fullmatch(r'[\w\[\]-]+', name):
            raise ValueError('Invalid multipart field name')
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio{audio.suffix}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
    parts.extend([audio.read_bytes(), f'\r\n--{boundary}--\r\n'.encode()])
    return b''.join(parts), f'multipart/form-data; boundary={boundary}'


def transcribe(audio, cfg, profile):
    key = key_for(profile)
    size = audio.stat().st_size
    if size < 45 or size > cfg.get('max_audio_bytes', 25000000):
        raise ValueError('Audio is empty or exceeds configured upload limit')
    url = endpoint(profile)
    timeout = cfg.get('request_timeout', 90)
    adapter = profile['adapter']
    if adapter == 'openai':
        data, mime = multipart(audio, profile['model'], profile.get('options', {}))
        result = request_json(url, key, data, mime, timeout)
    elif adapter == 'raw':
        result = request_json(url, key, audio.read_bytes(), 'application/octet-stream', timeout)
    elif adapter == 'json_base64':
        payload = dict(profile.get('options', {}))
        payload['audio'] = base64.b64encode(audio.read_bytes()).decode('ascii')
        result = request_json(url, key, json.dumps(payload).encode(), 'application/json', timeout)
    else:
        deadline = time.monotonic() + cfg.get('job_timeout', 300)
        upload = request_json(url.rstrip('/')+'/upload', key, audio.read_bytes(), 'application/octet-stream', timeout, False)
        options = dict(profile.get('options', {}))
        if profile.get('model'):
            options['speech_models'] = [profile['model']]
        options['audio_url'] = upload['upload_url']
        result = request_json(url.rstrip('/')+'/transcript', key, json.dumps(options).encode(), 'application/json', timeout, False)
        job_id = urllib.parse.quote(str(result['id']), safe='')
        while result.get('status') not in ('completed', 'error'):
            if time.monotonic() >= deadline:
                raise ValueError('Provider job timed out; do not blindly resubmit a potentially billed job')
            time.sleep(2)
            result = request_json(url.rstrip('/')+'/transcript/'+job_id, key, timeout=min(timeout, max(1, deadline-time.monotonic())), bearer=False)
        if result['status'] == 'error':
            raise ValueError('AssemblyAI transcription failed')
    text = result
    for component in profile.get('response_path', 'text').split('.'):
        text = text[component]
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Provider returned no transcription text')
    return text.strip()


def detach(command, *args, log=None):
    output = open(log, 'ab') if log else subprocess.DEVNULL
    try:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), command, *args], stdin=subprocess.DEVNULL, stdout=output, stderr=output, start_new_session=True, close_fds=True)
    finally:
        if log:
            output.close()
    return process


def worker(job):
    job = Path(job)
    # Parent publishes worker PID while holding this lock. Wait for that write
    # so a fast API response cannot be overwritten with stale parent state.
    with (runtime()/'toggle.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads((job/'state.json').read_text())
    try:
        cfg, profile = state['config'], state['profile']
        text = transcribe(job/'audio.wav', cfg, profile)
        result_file = job/'transcript.txt'
        result_file.write_text(text)
        os.chmod(result_file, 0o600)
        # xclip intentionally forks its clipboard owner; it must survive this worker.
        subprocess.run(['xclip', '-selection', 'clipboard'], input=text.encode(), check=True)
        if cfg.get('auto_paste', True):
            replace_placeholder(state['window'], 19, '')
            terminal = re.search(cfg.get('terminal_pattern', 'warp|terminal|kitty|xterm'), state['window_class'], re.I)
            mode = cfg.get('paste_mode', 'auto')
            chord = 'ctrl+shift+v' if mode == 'terminal' or (mode == 'auto' and terminal) else 'ctrl+v'
            xdo('key', '--clearmodifiers', chord)
            state['status'] = 'done'
            notify('Transcription pasted.')
        else:
            state['status'] = 'clipboard'
            notify('Transcription copied. Replace the placeholder and paste when ready.')
        # Successful audio is deleted; transcript retained privately for recovery.
        (job/'audio.wav').unlink(missing_ok=True)
    except Exception as error:
        state['status'] = 'failed'
        state['error'] = str(error)
        notify(f'Transcription failed: {error}. Recovery files: {job}', True)
    finally:
        write_json(job/'state.json', state)


def toggle(cfg, profile):
    base = runtime()
    with (base/'toggle.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        active = base/'active.json'
        if active.exists():
            state = json.loads(active.read_text())
            stop_recorder(state)  # signal recorder before any desktop operations
            replace_placeholder(state['window'], 16, TRANSCRIBING+' ')
            state['status'] = 'transcribing'
            job = Path(state['job'])
            write_json(job/'state.json', state)
            process = detach('_worker', str(job), log=job/'worker.log')
            state.update(worker_pid=process.pid, worker_token=proc_token(process.pid))
            write_json(job/'state.json', state)
            active.unlink()
            return
        # Do not let a pending completion delete a newer placeholder.
        for jobstate in base.glob('job-*/state.json'):
            pending = json.loads(jobstate.read_text())
            if pending.get('status') == 'transcribing' and alive(pending.get('worker_pid', -1), pending.get('worker_token')):
                notify('A transcription is still running. Use status or cancel.')
                return
        key_for(profile)  # fail before touching any editable field
        window = xdo('getactivewindow')
        # Ubuntu's xdotool has no getwindowclassname command. Query WM_CLASS
        # via xprop while xdotool supplies the captured ID and window name.
        window_class = run('xprop', '-id', window, 'WM_CLASS')
        window_name = xdo('getwindowname', window)
        job = Path(tempfile.mkdtemp(prefix='job-', dir=base))
        os.chmod(job, 0o700)
        logfile = (job/'recorder.log').open('ab')
        recorder = subprocess.Popen(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'pulse', '-i', cfg.get('audio_source', 'default'), '-t', str(cfg.get('max_recording_seconds', 600)), '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(job/'audio.wav')], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=logfile, start_new_session=True)
        logfile.close()
        state = dict(status='recording', job=str(job), window=window, window_class=window_class, window_name=window_name, recorder_pid=recorder.pid, recorder_token=proc_token(recorder.pid), config=cfg, profile=profile)
        try:
            type_text(RECORDING+' ')
            time.sleep(.15)
            if recorder.poll() is not None:
                raise ValueError(f'Microphone recording failed; see {job}/recorder.log')
            write_json(job/'state.json', state)
            write_json(active, state)
        except Exception:
            stop_recorder(state)
            # Placeholder is still at the current caret here.
            replace_placeholder(window, 16, '')
            raise


def cancel():
    base = runtime()
    with (base/'toggle.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        active = base/'active.json'
        if active.exists():
            state = json.loads(active.read_text())
            stop_recorder(state)
            state['status'] = 'cancelled'
            write_json(Path(state['job'])/'state.json', state)
            active.unlink()
        for path in base.glob('job-*/state.json'):
            state = json.loads(path.read_text())
            if state.get('status') == 'transcribing':
                if alive(state.get('worker_pid', -1), state.get('worker_token')):
                    os.killpg(state['worker_pid'], signal.SIGTERM)
                state['status'] = 'cancelled'
                write_json(path, state)
    notify('Cancelled. Remove the placeholder manually; recovery files remain private in /tmp.')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', default='toggle', choices=['toggle', 'status', 'cancel', 'doctor', 'transcribe', '_worker'])
    parser.add_argument('file', nargs='?')
    args = parser.parse_args()
    if args.command == '_worker':
        worker(args.file)
        return
    if args.command == 'cancel':
        cancel()
        return
    if args.command == 'status':
        base = runtime()
        for path in sorted(base.glob('job-*/state.json')):
            state = json.loads(path.read_text())
            print(json.dumps({k: state.get(k) for k in ('status', 'job', 'window', 'error')}))
        return
    cfg, profile = load_config()
    if args.command == 'doctor':
        missing = [name for name in ('xdotool', 'xprop', 'xclip', 'ffmpeg', 'notify-send', 'xfconf-query', 'pactl') if not shutil.which(name)]
        key_for(profile)
        endpoint(profile)
        if missing:
            raise ValueError('Missing dependencies: '+', '.join(missing))
        if not os.environ.get('DISPLAY'):
            raise ValueError('DISPLAY is unset; run in the Xubuntu desktop session')
        print('Provider:', cfg['provider'], '| model:', profile['model'], '| key: present')
        print('X11 active window:', xdo('getactivewindow'))
        print('Audio:', run('pactl', 'get-default-source'))
        print('Shortcut:', cfg.get('shortcut', '<Alt>x'))
    elif args.command == 'transcribe':
        if not args.file:
            parser.error('transcribe requires an audio file')
        print(transcribe(Path(args.file), cfg, profile))
    else:
        toggle(cfg, profile)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        notify(str(exc), True)
        print(f'STT Anywhere: {exc}', file=sys.stderr)
        sys.exit(1)
