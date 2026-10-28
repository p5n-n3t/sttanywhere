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

try:
    from .paste_context import foreground_process, paste_chord
    from .input_guard import focus_id
    from .transport import NoRedirect, request_json, ProviderTransportError
except ImportError:
    from paste_context import foreground_process, paste_chord
    from input_guard import focus_id
    from transport import NoRedirect, request_json, ProviderTransportError

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


def accessible(command, data):
    result = subprocess.run(['/usr/bin/python3', str(ROOT/'lib/accessibility.py'), command],
                            input=json.dumps(data), text=True, capture_output=True, timeout=12)
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise ValueError('Accessibility bridge unavailable; result kept for manual paste') from None
    if result.returncode:
        raise ValueError(output.get('error', 'Accessibility operation failed'))
    return output


def target_context():
    window = xdo('getactivewindow')
    window_class = run('xprop', '-id', window, 'WM_CLASS')
    window_name = xdo('getwindowname', window)
    try:
        pid = int(xdo('getwindowpid', window))
    except (ValueError, subprocess.CalledProcessError):
        pid = None
    return dict(window=window, window_class=window_class, window_name=window_name,
                window_pid=pid, foreground_process=foreground_process(pid))


def endpoint(profile):
    value = profile['endpoint'].replace('${model}', profile.get('model', ''))
    value = os.path.expandvars(value)
    parsed = urllib.parse.urlparse(value)
    if '${' in value or parsed.scheme != 'https' or not parsed.netloc or parsed.username:
        raise ValueError('Provider endpoint must be a complete HTTPS URL without embedded credentials')
    return value


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
        if cfg.get('lossless_upload',False) and audio.suffix.lower()=='.wav':
            with tempfile.TemporaryDirectory(prefix='upload-',dir=audio.parent) as folder:
                packed=Path(folder)/'audio.flac'
                subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(audio),'-c:a','flac',str(packed)],
                               check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
                data,mime=multipart(packed,profile['model'],profile.get('options',{}))
        else:
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


def start_input_guard(job, cfg):
    path = job/'input-guard.json'
    process = subprocess.Popen([sys.executable, str(ROOT/'lib/input_guard.py'), str(path), cfg.get('shortcut','<Alt>x'),
                                str(int(cfg.get('max_recording_seconds',600)+cfg.get('job_timeout',300)+120))],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True, close_fds=True)
    guard = {'pid':process.pid,'token':proc_token(process.pid),'path':str(path)}
    for _ in range(100):
        try:
            status=json.loads(path.read_text())
            if status.get('ready'):
                return guard
        except (OSError,json.JSONDecodeError):
            pass
        if process.poll() is not None:
            break
        time.sleep(.02)
    stop_input_guard(guard)
    return None


def stop_input_guard(guard):
    if guard and alive(guard['pid'],guard['token']):
        try:os.kill(guard['pid'],signal.SIGTERM)
        except ProcessLookupError:pass


def foreground_deliver(state, text):
    guard=state.get('input_guard')
    if not guard:
        return False,'Foreground input could not be monitored'
    try:
        status=json.loads(Path(guard['path']).read_text())
        if not status.get('ready') or status.get('dirty') or not alive(guard['pid'],guard['token']):
            return False,'You typed, clicked, changed focus, or the input monitor stopped; result kept on clipboard'
        if xdo('getactivewindow')!=state['window'] or focus_id()!=status.get('focus'):
            return False,'Original field is no longer focused; result kept on clipboard'
        cfg=state.get('config',{})
        terminal=re.search(cfg.get('terminal_pattern','warp|terminal|kitty|xterm'),state.get('window_class',''),re.I)
        if terminal and any(c in text for c in ('\n','\r','\t')):
            return False,'Multiline text kept on clipboard for explicit paste'
        # Terminal ASCII uses normal keys instead of application-specific paste
        # chords. GUI fields use atomic clipboard paste to avoid dropped keys
        # in busy browser UI threads. Unicode also uses the configured chord.
        # No Return/Tab is synthesized, and no window is ever activated here.
        if text.isascii() and terminal:
            xdo('type','--clearmodifiers','--delay','5','--',text)
            state['foreground_method']='typing'
        else:
            subprocess.run(['xclip','-selection','clipboard'],input=text.encode(),check=True)
            # Clipboard ownership may take time; recheck input/focus immediately.
            status=json.loads(Path(guard['path']).read_text())
            if status.get('dirty') or xdo('getactivewindow')!=state['window'] or focus_id()!=status.get('focus'):
                return False,'Focus/input changed before Unicode paste; text kept on clipboard'
            xdo('key','--clearmodifiers',paste_chord(state.get('config',{}),state))
            state['foreground_method']='clipboard-paste'
        return True,None
    except Exception:
        return False,'Could not verify unchanged foreground input; result kept on clipboard'


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
        if cfg.get('auto_paste', True) and cfg.get('delivery_mode', 'anchored') == 'legacy':
            replace_placeholder(state['window'], 19, '')
            chord = paste_chord(cfg, state)
            xdo('key', '--clearmodifiers', chord)
            state['status'] = 'done'
        elif cfg.get('auto_paste', True) and state.get('anchor'):
            try:
                state['anchor'] = accessible('replace', {**state['anchor'], 'replacement': text})
                state['status'] = 'done'
                state['delivery'] = 'accessibility-background'
            except Exception as error:
                state['status'] = 'clipboard'
                state['delivery_reason'] = str(error)
        else:
            state['status'] = 'clipboard'
            state['delivery_reason'] = state.get('anchor_error', 'Automatic insertion disabled')
            if cfg.get('auto_paste',True) and cfg.get('foreground_fallback',True) and state.get('input_guard'):
                delivered,reason=foreground_deliver(state,text)
                if delivered:
                    state['status']='done'
                    state['delivery']='foreground-paste' if state.get('foreground_method')=='clipboard-paste' else 'foreground-typing'
                    state.pop('delivery_reason',None)
                else:
                    state['delivery_reason']=reason
        if state['status'] == 'clipboard' and cfg.get('auto_paste', True):
            # A requested insertion that could not happen needs feedback even
            # when routine success notifications are disabled.
            notify('Transcribed, but automatic insertion was unavailable or focus changed. Text copied to clipboard; use your paste shortcut or sttanywhere paste.')
        elif cfg.get('notify_completion', False):
            notify('Transcription inserted in the original text field.' if state['status'] == 'done' else 'Transcription ready on clipboard; use your paste shortcut or sttanywhere paste.')
        # Successful audio is deleted; transcript retained privately for recovery.
        (job/'audio.wav').unlink(missing_ok=True)
    except Exception as error:
        state['status'] = 'failed'
        state['error'] = str(error)
        if isinstance(error, ProviderTransportError):
            state['error_category'] = error.category
            state['outcome_unknown'] = error.outcome_unknown
        notify(f'Transcription failed: {error}. Recovery files: {job}', True)
    finally:
        stop_input_guard(state.get('input_guard'))
        write_json(job/'state.json', state)


def toggle(cfg, profile):
    base = runtime()
    with (base/'toggle.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        active = base/'active.json'
        if active.exists():
            state = json.loads(active.read_text())
            stop_recorder(state)  # signal recorder before any desktop operations
            if state['config'].get('delivery_mode', 'anchored') == 'legacy':
                replace_placeholder(state['window'], 16, TRANSCRIBING+' ')
            elif state.get('anchor'):
                try:
                    state['anchor'] = accessible('replace', {**state['anchor'], 'replacement': TRANSCRIBING+' '})
                except Exception as error:
                    state['anchor_error'] = str(error)
                    state.pop('anchor', None)
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
        context = target_context()
        window = context['window']
        job = Path(tempfile.mkdtemp(prefix='job-', dir=base))
        os.chmod(job, 0o700)
        logfile = (job/'recorder.log').open('ab')
        recorder = subprocess.Popen(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'pulse', '-i', cfg.get('audio_source', 'default'), '-t', str(cfg.get('max_recording_seconds', 600)), '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(job/'audio.wav')], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=logfile, start_new_session=True)
        logfile.close()
        state = dict(status='recording', job=str(job), **context, recorder_pid=recorder.pid, recorder_token=proc_token(recorder.pid), config=cfg, profile=profile)
        try:
            if cfg.get('delivery_mode', 'anchored') == 'legacy':
                type_text(RECORDING+' ')
            else:
                if cfg.get('auto_paste',True) and cfg.get('foreground_fallback',True):
                    state['input_guard']=start_input_guard(job,cfg)
                try:
                    state['anchor'] = accessible('capture', {'pid': context['window_pid'], 'marker': RECORDING+' '})
                    stop_input_guard(state.pop('input_guard',None))
                except Exception as error:
                    state['anchor_error'] = str(error)
                    # Only a cleanly unavailable bridge/field can fall back to
                    # typing. A partial or ambiguous anchor operation cannot.
                    unavailable=any(message in str(error) for message in ('No accessible editable target','Accessibility bridge unavailable'))
                    if not unavailable:
                        stop_input_guard(state.pop('input_guard',None))
            time.sleep(.15)
            if recorder.poll() is not None:
                raise ValueError(f'Microphone recording failed; see {job}/recorder.log')
            write_json(job/'state.json', state)
            write_json(active, state)
            if not state.get('anchor') and cfg.get('delivery_mode','anchored')!='legacy' and cfg.get('notify_recording',True):
                notify('Recording — Alt+X stops. This field uses foreground insertion if untouched; otherwise clipboard recovery.')
        except Exception:
            stop_input_guard(state.get('input_guard'))
            stop_recorder(state)
            if state.get('anchor'):
                accessible('replace', {**state['anchor'], 'replacement': ''})
            elif cfg.get('delivery_mode', 'anchored') == 'legacy':
                replace_placeholder(window, 16, '')
            raise


def cancel():
    base = runtime()
    with (base/'toggle.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        active = base/'active.json'
        if active.exists():
            state = json.loads(active.read_text())
            stop_input_guard(state.get('input_guard'))
            stop_recorder(state)
            state['status'] = 'cancelled'
            write_json(Path(state['job'])/'state.json', state)
            active.unlink()
        for path in base.glob('job-*/state.json'):
            state = json.loads(path.read_text())
            if state.get('status') == 'transcribing':
                stop_input_guard(state.get('input_guard'))
                if alive(state.get('worker_pid', -1), state.get('worker_token')):
                    os.killpg(state['worker_pid'], signal.SIGTERM)
                state['status'] = 'cancelled'
                write_json(path, state)
    notify('Cancelled. Remove the placeholder manually; recovery files remain private in /tmp.')


def retry_job(name):
    """One explicit recovery attempt; never write into an old document/caret."""
    base=runtime().resolve()
    job=Path(name)
    if not job.is_absolute():job=base/job
    job=job.resolve()
    if job.parent!=base or not job.name.startswith('job-'):
        raise ValueError('Choose a job directory from sttanywhere status')
    path=job/'state.json'
    with (job/'recovery.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('A recovery attempt is already running') from None
        state=json.loads(path.read_text())
        if state.get('status') not in ('failed','recovery_failed') or not (job/'audio.wav').is_file():
            raise ValueError('Only failed jobs with retained audio can be retried')
        attempt={'operation':'explicit-recovery','started':time.time(),'provider_request':not (job/'transcript.txt').exists()}
        state.setdefault('recovery_attempts',[]).append(attempt)
        state['previous_error']=state.get('error')
        state['status']='recovering'
        write_json(path,state)
        try:
            # A successful provider response may already be saved after a clipboard error.
            # Reuse it instead of billing a second transcription.
            transcript=job/'transcript.txt'
            text=transcript.read_text() if transcript.exists() else transcribe(job/'audio.wav',state['config'],state['profile'])
            (job/'transcript.txt').write_text(text)
            os.chmod(job/'transcript.txt',0o600)
            subprocess.run(['xclip','-selection','clipboard'],input=text.encode(),check=True)
            state.update(status='recovered',delivery='clipboard',delivery_reason='Explicit recovery; old document left untouched')
            state.pop('error',None)
            attempt['status']='success'
            print('Recovered transcription copied to clipboard. Original audio retained; no window was focused or modified.')
        except Exception as error:
            state.update(status='recovery_failed',error=str(error))
            attempt.update(status='failed',error=str(error))
            if isinstance(error,ProviderTransportError):
                state.update(error_category=error.category,outcome_unknown=error.outcome_unknown)
            raise
        finally:
            attempt['finished']=time.time()
            write_json(path,state)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', default='toggle', choices=['toggle', 'status', 'cancel', 'doctor', 'transcribe', 'retry', 'paste', 'context', '_worker'])
    parser.add_argument('file', nargs='?')
    args = parser.parse_args()
    if args.command == '_worker':
        worker(args.file)
        return
    if args.command == 'cancel':
        cancel()
        return
    if args.command == 'retry':
        if not args.file:parser.error('retry requires the failed job directory')
        retry_job(args.file)
        return
    if args.command == 'status':
        base = runtime()
        for path in sorted(base.glob('job-*/state.json')):
            state = json.loads(path.read_text())
            print(json.dumps({k: state.get(k) for k in ('status', 'job', 'window', 'delivery', 'delivery_reason', 'anchor_error', 'error', 'error_category', 'outcome_unknown')}))
        return
    cfg, profile = load_config()
    if args.command == 'context':
        context = target_context()
        context['paste_chord'] = paste_chord(cfg, context)
        context['foreground_fallback_configured'] = cfg.get('foreground_fallback',True)
        try:
            context['background_insertion'] = accessible('probe', {'pid': context['window_pid']})
        except Exception as error:
            context['background_insertion'] = {'supported': False, 'reason': str(error)}
        print(json.dumps(context, indent=2))
    elif args.command == 'paste':
        # Explicit user action at the current field; never refocus an old target.
        context = target_context()
        xdo('key', '--clearmodifiers', paste_chord(cfg, context))
    elif args.command == 'doctor':
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
        print('Delivery:', cfg.get('delivery_mode', 'anchored'), '| guarded foreground fallback:', cfg.get('foreground_fallback',True))
        print('Changed/unverified targets: clipboard recovery; no refocus')
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
