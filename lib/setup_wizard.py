"""Terminal setup planning: no filesystem or desktop mutations before apply."""
import argparse
import copy
import getpass
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from urllib.parse import urlparse

DEPENDENCIES = ('xdotool', 'xprop', 'xclip', 'ffmpeg', 'notify-send', 'xfconf-query', 'pactl')
PACKAGES = ('python3', 'python3-gi', 'gir1.2-atspi-2.0', 'ffmpeg', 'pulseaudio-utils', 'xdotool', 'xclip', 'x11-utils', 'libnotify-bin', 'xfconf')


class Cancelled(Exception):
    pass


def parser():
    result = argparse.ArgumentParser(description='STT Anywhere terminal setup. Changes are previewed before applying.')
    mode = result.add_mutually_exclusive_group()
    mode.add_argument('--interactive', action='store_true', help='Run the guided setup (requires a terminal)')
    mode.add_argument('--non-interactive', action='store_true', help='Apply existing/default settings without prompts')
    result.add_argument('--dry-run', action='store_true', help='Preview only; do not change files, install packages or bind shortcuts')
    result.add_argument('--deps', action='store_true', help='Install Debian/Ubuntu dependencies after confirming the plan')
    result.add_argument('--no-bind', action='store_true', help='Configure only; leave xhisper and keyboard shortcuts untouched')
    for field in ('provider', 'model', 'endpoint', 'shortcut', 'audio-source'):
        result.add_argument('--'+field, help='Override '+field.replace('-', ' '))
    result.add_argument('--delivery-mode', choices=('anchored','clipboard','legacy'), help='Choose insertion behavior')
    return result


def assignments(text):
    values = {}
    for line in text.splitlines():
        match = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$', line)
        if not match:
            continue
        try:
            words = shlex.split(match[2], comments=True)
        except ValueError:
            continue
        if len(words) == 1:
            values[match[1]] = words[0]
    return values


def set_assignment(text, name, value):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) or any(c in value for c in ('\n', '\r', '\0')):
        raise ValueError('Credentials must use a valid variable name and a single-line value')
    replacement = name+'='+shlex.quote(value)
    lines = text.splitlines()
    pattern = re.compile(r'^\s*(?:export\s+)?'+re.escape(name)+r'\s*=')
    result, replaced = [], False
    for line in lines:
        if pattern.match(line):
            if not replaced:
                result.append(replacement)
                replaced = True
        else:
            result.append(line)
    if not replaced:
        result.append(replacement)
    return '\n'.join(result)+'\n'


def ask(label, default):
    answer = input(f'{label} [{default}]: ').strip()
    if answer.lower() in ('quit', 'cancel'):
        raise Cancelled()
    return answer or default


def choose(label, choices, default):
    print('\n'+label)
    for i, (value, description) in enumerate(choices, 1):
        print(f'  {i}. {value} — {description}')
    while True:
        answer = ask('Choose number or name', default)
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer)-1][0]
        if answer in [x[0] for x in choices]:
            return answer
        print('Choose one of the listed options, or type cancel.')


def microphone_sources():
    try:
        proc = subprocess.run(['pactl','list','short','sources'], text=True, capture_output=True, timeout=4)
        return [line.split('\t')[1] for line in proc.stdout.splitlines() if len(line.split('\t')) > 1]
    except (OSError, subprocess.TimeoutExpired):
        return []


def validate(cfg):
    if cfg.get('provider') not in cfg.get('providers', {}):
        raise ValueError('Provider must name an entry in providers')
    profile = cfg['providers'][cfg['provider']]
    if profile.get('adapter') not in ('openai','raw','json_base64','assemblyai'):
        raise ValueError('Unsupported provider adapter')
    if '${'+profile.get('api_key_env','')+'}' in profile.get('endpoint',''):
        raise ValueError('Keep API credentials in the authorization header, not in the endpoint')
    url = urlparse(profile.get('endpoint','').replace('${model}', profile.get('model','')))
    if url.scheme != 'https' or not url.netloc or url.username or url.password:
        raise ValueError('Provider endpoint must be HTTPS without credentials in the URL')
    if any(word in profile['endpoint'] for word in ('YOUR-PROVIDER','YOUR-MODEL')) or profile.get('model') == 'YOUR-MODEL':
        raise ValueError('Replace the custom endpoint and model placeholders before applying')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', profile.get('api_key_env','')):
        raise ValueError('api_key_env must be an environment variable name')
    if not isinstance(profile.get('model'),str) or not profile['model'].strip():
        raise ValueError('Model cannot be empty')
    shortcut = cfg.get('shortcut','')
    if not re.fullmatch(r'(?:<(?:Alt|Control|Ctrl|Shift|Super|Primary)>)+[A-Za-z0-9_]+',shortcut):
        raise ValueError('Use an XFCE shortcut such as <Alt>x or <Control><Shift>space')
    if not cfg.get('audio_source','').strip():
        raise ValueError('Audio source cannot be empty')


def plan(root, args, config_home=None, home=None):
    home = home or Path.home()
    config_home = config_home or Path(os.environ.get('XDG_CONFIG_HOME', home/'.config'))
    dest = config_home/'sttanywhere'
    config_path, credentials = dest/'config.json', dest/'credentials.env'
    cfg = json.loads((config_path if config_path.exists() else root/'config/config.example.json').read_text())
    cfg = copy.deepcopy(cfg)
    original = credentials.read_text() if credentials.exists() else '# Private STT Anywhere credentials. Never commit this file.\n'
    credential_text = original
    for name, field in [('provider','provider'),('shortcut','shortcut'),('audio_source','audio_source')]:
        if getattr(args,name,None) is not None:
            cfg[field] = getattr(args,name)
    if cfg.get('provider') not in cfg['providers']:
        raise ValueError('Unknown provider profile; add it to config.json first')
    profile = cfg['providers'][cfg['provider']]
    for name in ('model','endpoint'):
        if getattr(args,name,None) is not None:
            profile[name] = getattr(args,name)
    if args.delivery_mode:
        cfg['delivery_mode'] = 'anchored' if args.delivery_mode == 'clipboard' else args.delivery_mode
        cfg['auto_paste'] = args.delivery_mode != 'clipboard'
    interactive = args.interactive or (not args.non_interactive and sys.stdin.isatty() and sys.stdout.isatty())
    if args.interactive and not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ValueError('--interactive requires a terminal; use --non-interactive or --dry-run for scripts')
    if interactive:
        print('\nSTT Anywhere · guided terminal setup\nPress Enter to keep each current value. Type cancel at a prompt to leave setup.\nNo files, packages or shortcuts change until the final confirmation.')
        provider = choose('1/5  Speech-to-text provider', [(name, 'current profile' if name==cfg['provider'] else item.get('adapter','')) for name,item in cfg['providers'].items()], cfg['provider'])
        cfg['provider'] = provider
        profile = cfg['providers'][provider]
        profile['model'] = ask('Model', profile['model'])
        profile['endpoint'] = ask('HTTPS endpoint', profile['endpoint'])
        if provider == 'custom':
            profile['adapter'] = choose('API request format',[(x,x) for x in ('openai','raw','json_base64','assemblyai')],profile['adapter'])
            profile['api_key_env'] = ask('Credential variable name',profile['api_key_env'])
            profile['response_path'] = ask('JSON transcript path',profile.get('response_path','text'))
        print('\n2/5  Microphone')
        sources = microphone_sources()
        for source in sources:
            print('  '+source+(' (output monitor)' if '.monitor' in source else ''))
        if not sources:
            print('  Audio service unavailable; source can still be configured for later.')
        cfg['audio_source'] = ask('Source (default follows your desktop microphone)',cfg.get('audio_source','default'))
        print('\n3/5  Desktop shortcut and delivery')
        args.no_bind = choose('Shortcut setup',[('configure','install the XFCE shortcut and migrate xhisper'),('skip','leave shortcuts and xhisper untouched')], 'skip' if args.no_bind else 'configure') == 'skip'
        cfg['shortcut'] = ask('XFCE shortcut',cfg.get('shortcut','<Alt>x'))
        current = 'clipboard' if not cfg.get('auto_paste',True) else cfg.get('delivery_mode','anchored')
        delivery = choose('How should text arrive?',[('anchored','replace marker in supported accessible fields; otherwise clipboard'),('clipboard','copy result for manual paste; no automatic replacement'),('legacy','raises original window and pastes at its current caret')],current)
        cfg['delivery_mode'] = 'legacy' if delivery == 'legacy' else 'anchored'
        cfg['auto_paste'] = delivery != 'clipboard'
        print('\n4/5  Credentials (values are never displayed)')
    name = profile['api_key_env']
    # Existing values win. Legacy Groq import is data parsing, not shell execution.
    private = assignments(credential_text)
    legacy = assignments((home/'.env').read_text()) if (home/'.env').is_file() and name == 'GROQ_API_KEY' else {}
    key = private.get(name) or os.environ.get(name) or legacy.get(name)
    if interactive:
        print(f'{name}: '+('available; reuse is the default' if key else 'not configured'))
        action = choose('Credential action',[('reuse','keep/import available key'),('replace','enter a new key with hidden input'),('later','configure later; dictation will require a key')],'reuse' if key else 'later')
        if action == 'replace':
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',name):
                raise ValueError('Invalid credential environment variable name')
            key = getpass.getpass(f'{name} (hidden; blank cancels): ')
            if not key:
                raise Cancelled()
            credential_text = set_assignment(credential_text,name,key)
        elif action == 'later':
            # Never erase an existing credential just because setup is deferred.
            key = private.get(name)
    if key and not assignments(credential_text).get(name):
        credential_text = set_assignment(credential_text,name,key)
    if '${'+name+'}' in profile['endpoint']:
        raise ValueError('Do not put API credential variables in the endpoint')
    missing_vars = re.findall(r'\$\{([A-Z_][A-Z0-9_]*)\}',profile['endpoint'])
    for variable in missing_vars:
        values = assignments(credential_text)
        value = values.get(variable) or os.environ.get(variable)
        if interactive:
            value = ask(variable, value or '')
        if value:
            credential_text = set_assignment(credential_text,variable,value)
    validate(cfg)
    missing = [binary for binary in DEPENDENCIES if not shutil.which(binary)]
    if interactive:
        print('\n5/5  Dependencies and review')
        print('Missing tools: '+(', '.join(missing) if missing else 'none'))
        args.deps = choose('Dependency installation',[('skip','use existing system packages'),('install','run apt-get after confirmation')],'install' if args.deps else 'skip') == 'install'
    return dict(config=cfg,credentials=credential_text,dest=dest,home=home,config_home=config_home,
                credential_present=bool(assignments(credential_text).get(name)),interactive=interactive,
                no_bind=args.no_bind,deps=args.deps,missing=missing,dry_run=args.dry_run)


def preview(plan):
    cfg = plan['config'];p = cfg['providers'][cfg['provider']]
    print('\nSetup plan — no changes applied yet')
    print('  Provider:',cfg['provider'],'| model:',p['model'],'| adapter:',p['adapter'])
    print('  Endpoint:',p['endpoint'])
    print('  Microphone:',cfg['audio_source'])
    print('  Delivery:',cfg.get('delivery_mode','anchored'),'| automatic replacement:',cfg.get('auto_paste',True))
    print('  Shortcut:',cfg['shortcut'],'(unchanged)' if plan['no_bind'] else '(configure; migrate xhisper)')
    print('  Credentials:', 'available (hidden)' if plan['credential_present'] else 'not configured; set before dictating')
    print('  Private config:',plan['dest'])
    print('  Packages:', 'apt-get install '+', '.join(PACKAGES) if plan['deps'] else 'no package installation')
    print('  Backups: previous configuration and affected shortcuts/services are recorded before changes')
    print('  API calls: none; this installer never sends audio or tests a provider automatically')
