#!/usr/bin/python3
"""Real X11 text fields and input guard, isolated session; no STT API calls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from integration_background import wait


def session():
    from lib import sttanywhere as stt
    from lib.accessibility import locate,text_of
    procs=[]
    firefox_profile=None
    audio_module=None
    with tempfile.TemporaryDirectory(prefix='sttanywhere-fields-') as folder:
        base=Path(folder)
        try:
            r,w=os.pipe()
            procs.append(subprocess.Popen(['Xvfb','-displayfd',str(w),'-screen','0','1280x800x24','-nolisten','tcp'],pass_fds=(w,),stderr=subprocess.DEVNULL))
            os.close(w)
            with os.fdopen(r) as f:os.environ['DISPLAY']=':'+f.readline().strip()
            os.environ.pop('XAUTHORITY',None)
            os.environ.pop('SESSION_MANAGER',None)
            os.environ.pop('DESKTOP_STARTUP_ID',None)
            os.environ.setdefault('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}')
            os.environ.update(XDG_CONFIG_HOME=str(base/'config'),XDG_CACHE_HOME=str(base/'cache'),XDG_DATA_HOME=str(base/'data'),GTK_USE_PORTAL='0')
            subprocess.run(['dbus-update-activation-environment','DISPLAY','GVFS_DISABLE_FUSE'],check=True)
            wm_log=(base/'wm.log').open('wb')
            procs.append(subprocess.Popen(['xfwm4','--replace','--sm-client-disable','--compositor=off','--vblank=off'],stdout=wm_log,stderr=wm_log))
            wm_log.close()
            try:wait(lambda:'_NET_ACTIVE_WINDOW' in subprocess.check_output(['xprop','-root','_NET_SUPPORTED'],text=True))
            except Exception:
                print('Window manager:',(base/'wm.log').read_text(errors='replace'),flush=True)
                raise
            def launch(command,pattern):
                log=(base/(str(len(procs))+'.log')).open('wb')
                p=subprocess.Popen(command,stdout=log,stderr=log);log.close();procs.append(p)
                def find():
                    try:return stt.xdo('search','--onlyvisible','--class',pattern).splitlines()[0]
                    except (subprocess.CalledProcessError,IndexError):return None
                try:window=wait(find,25)
                except Exception:
                    print('App launch log:',(base/(str(len(procs)-1)+'.log')).read_text(errors='replace')[-1800:],flush=True)
                    raise
                stt.xdo('windowactivate','--sync',window);time.sleep(1.5)
                return window
            def read_selection():
                time.sleep(.3)
                stt.xdo('key','--clearmodifiers','ctrl+a','ctrl+c')
                time.sleep(.2)
                return subprocess.check_output(['xclip','-selection','clipboard','-o','-t','UTF8_STRING'],text=True)
            def fallback(window,text,dirty=False):
                job=base/('guard-'+str(time.time_ns()));job.mkdir(mode=0o700)
                guard=stt.start_input_guard(job,{'shortcut':'<Alt>x'})
                assert guard,'Input monitor did not start'
                state={'window':window,'input_guard':guard,'window_class':stt.run('xprop','-id',window,'WM_CLASS')}
                try:
                    if dirty:
                        stt.xdo('type','--clearmodifiers','--delay','10','--','user edit')
                        wait(lambda:json.loads(Path(guard['path']).read_text()).get('dirty'))
                    delivered,reason=stt.foreground_deliver(state,text)
                    assert delivered != dirty,(delivered,reason)
                    return guard
                finally:stt.stop_input_guard(guard)
            thunar=launch(['thunar',str(base)],'Thunar')
            stt.xdo('key','--clearmodifiers','ctrl+l')
            time.sleep(.2)
            # Ctrl+L selects the current path: capture must replace that selection.
            pid=int(stt.xdo('getwindowpid',thunar))
            anchor=stt.accessible('capture',{'pid':pid,'marker':stt.RECORDING+' '})
            anchor=stt.accessible('replace',{**anchor,'replacement':'/tmp/DICTATION-ADDRESS'})
            assert text_of(locate(anchor))[1]=='/tmp/DICTATION-ADDRESS',repr(text_of(locate(anchor))[1])
            print('Thunar selected address bar: PASS',flush=True)
            chrome=launch(['google-chrome','--user-data-dir='+str(base/'chrome'),'--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-sync','--password-store=basic','about:blank'],'Google-chrome')
            time.sleep(2)
            stt.xdo('windowactivate','--sync',chrome)
            print('Chrome target:',chrome,stt.xdo('getwindowname',chrome),flush=True)
            stt.xdo('key','--clearmodifiers','ctrl+l')
            time.sleep(.3)
            fallback(chrome,'dictation address test')
            assert read_selection()=='dictation address test'
            print('Chrome address bar guarded paste: PASS',flush=True)
            # A local form supplies a visible title mirroring its nonsensitive input.
            page=base/'fields.html'
            page.write_text('<title>STT Fields</title><h1>STT Anywhere text-field test</h1><input id="f" autofocus style="font-size:24px;width:90%" oninput="document.title=\'Value:\'+this.value"><textarea style="width:90%;height:160px"></textarea>')
            page.write_text(page.read_text()+"<script>document.querySelector('textarea').oninput=function(){document.title='Area:'+this.value.split(String.fromCharCode(10)).join('|')}</script>")
            stt.xdo('key','--clearmodifiers','ctrl+l');stt.type_text(page.as_uri());stt.xdo('key','Return')
            wait(lambda:'STT Fields' in stt.xdo('getwindowname',chrome))
            fallback(chrome,'Hello مرحبا')
            wait(lambda:'Value:Hello مرحبا' in stt.xdo('getwindowname',chrome))
            print('Chrome web input with Unicode: PASS',flush=True)
            stt.xdo('key','--clearmodifiers','Tab');time.sleep(.2)
            fallback(chrome,'line one\nline two')
            wait(lambda:'Area:line one|line two' in stt.xdo('getwindowname',chrome))
            print('Chrome multiline textarea paste: PASS',flush=True)
            stt.xdo('key','--clearmodifiers','shift+Tab');time.sleep(.2)

            fallback(chrome,'MUST NOT INSERT',dirty=True)
            wait(lambda:'user edit' in stt.xdo('getwindowname',chrome))
            title=stt.xdo('getwindowname',chrome)
            assert 'user edit' in title and 'MUST NOT INSERT' not in title,title
            print('Changed field: guarded fallback leaves user edits untouched: PASS',flush=True)
            focus_job=base/'focus-guard';focus_job.mkdir(mode=0o700)
            focus_guard=stt.start_input_guard(focus_job,{'shortcut':'<Alt>x'})
            assert focus_guard
            stt.xdo('windowactivate','--sync',thunar)
            stt.xdo('windowactivate','--sync',chrome)
            wait(lambda:json.loads(Path(focus_guard['path']).read_text()).get('dirty'))
            delivered,reason=stt.foreground_deliver({'window':chrome,'input_guard':focus_guard},'MUST NOT INSERT')
            assert not delivered
            stt.stop_input_guard(focus_guard)
            print('Focus change and return cannot redirect insertion: PASS',flush=True)

            # Full record/stop/detached-worker pipeline against the real web field.
            # A private silent loopback avoids recording the host microphone.
            sink='stt_fields_'+str(os.getpid())
            audio_module=subprocess.check_output(['pactl','load-module','module-null-sink','sink_name='+sink],text=True).strip()
            local_runtime=base/'runtime'
            cfg=json.loads((ROOT/'config/config.example.json').read_text())
            cfg.update(audio_source=sink+'.monitor',notify_recording=False)
            profile=dict(cfg['providers']['groq'],api_key_env='STT_INTEGRATION_KEY')
            os.environ['STT_INTEGRATION_KEY']='test-only'
            stt.xdo('key','--clearmodifiers','ctrl+a','BackSpace')
            wait(lambda:'Value: -' in stt.xdo('getwindowname',chrome))
            def stub_worker(command,job,log=None):
                script='from pathlib import Path;from lib import sttanywhere as s;import sys;s.RUNTIME=Path(sys.argv[2]);s.transcribe=lambda *a:"toggle pipeline works";s.worker(sys.argv[1])'
                child=subprocess.Popen([sys.executable,'-c',script,job,str(local_runtime)],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                procs.append(child)
                return child
            with mock.patch.object(stt,'RUNTIME',local_runtime),mock.patch.object(stt,'detach',side_effect=stub_worker):
                stt.toggle(cfg,profile)
                assert (local_runtime/'active.json').exists()
                time.sleep(.4)
                stt.toggle(cfg,profile)
                assert not (local_runtime/'active.json').exists()
                def complete():
                    for state_file in local_runtime.glob('job-*/state.json'):
                        state=json.loads(state_file.read_text())
                        if state.get('status')=='failed':raise AssertionError(state.get('error'))
                        if state.get('status')=='done':return state
                completed=wait(complete,25)
                wait(lambda:'Value:toggle pipeline works' in stt.xdo('getwindowname',chrome))
            print('Actual record/stop/detached delivery pipeline in Chrome: PASS ('+completed.get('delivery','')+')',flush=True)

            capture=base/'capture.sh';result=base/'cli.txt'
            capture.write_text('#!/bin/bash\nIFS= read -r line\nprintf "%s" "$line" > "$1"\nsleep 60\n')
            terminal=launch(['xfce4-terminal','--disable-server','--title=STT Field CLI','--execute','/bin/bash',str(capture),str(result)],'Xfce4-terminal')
            fallback(terminal,'CLI typing without paste chords')
            stt.xdo('key','--clearmodifiers','Return');wait(result.exists)
            assert result.read_text()=='CLI typing without paste chords'
            print('Terminal prompt native typing: PASS',flush=True)
            if os.environ.get('STT_TEST_FIREFOX')=='1':
                import urllib.parse
                shared=Path.home()/'snap/firefox/common'
                shared.mkdir(parents=True,exist_ok=True)
                firefox_profile=tempfile.TemporaryDirectory(prefix='sttanywhere-test-',dir=shared)
                profile=Path(firefox_profile.name)
                (profile/'user.js').write_text('user_pref("browser.shell.checkDefaultBrowser",false);\nuser_pref("browser.startup.homepage_override.mstone","ignore");\nuser_pref("datareporting.policy.dataSubmissionEnabled",false);\n')
                private_bus=os.environ['DBUS_SESSION_BUS_ADDRESS']
                command=['env','DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/'+str(os.getuid())+'/bus','firefox','--no-remote','--profile',str(profile),'about:blank']
                firefox=launch(command,'firefox')
                time.sleep(1)
                stt.xdo('key','--clearmodifiers','ctrl+l');time.sleep(.3)
                fallback(firefox,'firefox address test')
                assert read_selection()=='firefox address test'
                print('Firefox address bar: PASS',flush=True)
                html='<title>STT Firefox</title><input autofocus oninput="document.title=\'Value:\'+this.value">'
                uri='data:text/html;charset=utf-8,'+urllib.parse.quote(html)
                subprocess.run(['xclip','-selection','clipboard'],input=uri.encode(),check=True)
                stt.xdo('key','--clearmodifiers','ctrl+l');time.sleep(.3)
                stt.xdo('key','--clearmodifiers','ctrl+v');time.sleep(.3)
                stt.xdo('key','Return')
                wait(lambda:'STT Firefox' in stt.xdo('getwindowname',firefox))
                fallback(firefox,'Firefox field works')
                wait(lambda:'Value:Firefox field works' in stt.xdo('getwindowname',firefox))
                print('Firefox web input: PASS',flush=True)

            stt.xdo('windowactivate','--sync',chrome)
            # Show only isolated, disposable test content in the screenshot.
            try:
                import gi
                gi.require_version('Gdk','3.0')
                from gi.repository import Gdk
                Gdk.init([]);root=Gdk.get_default_root_window()
                pix=Gdk.pixbuf_get_from_window(root,0,0,1280,800)
                pix.savev('/tmp/sttanywhere-fields-proof.png','png',[],[])
            except Exception:pass
            print('All field checks PASS; no provider calls',flush=True)
        finally:
            try:
                import gi
                gi.require_version('Gdk','3.0')
                from gi.repository import Gdk
                Gdk.init([]);root=Gdk.get_default_root_window()
                Gdk.pixbuf_get_from_window(root,0,0,1280,800).savev('/tmp/sttanywhere-fields-last.png','png',[],[])
            except Exception:pass
            for p in reversed(procs):
                if p.poll() is None:
                    p.terminate()
                    try:p.wait(timeout=4)
                    except subprocess.TimeoutExpired:p.kill()
            if audio_module:
                subprocess.run(['pactl','unload-module',audio_module],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if firefox_profile:firefox_profile.cleanup()

if __name__=='__main__':
    os.environ['GVFS_DISABLE_FUSE']='1'
    if '--session' in sys.argv:session()
    else:subprocess.run(['dbus-run-session','--','/usr/bin/python3',str(Path(__file__).resolve()),'--session'],check=True)
