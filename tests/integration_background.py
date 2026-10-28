#!/usr/bin/python3
"""Isolated real Mousepad background/changed-caret regression; no API call."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def wait(check, timeout=15):
    end = time.monotonic()+timeout
    while time.monotonic()<end:
        result = check()
        if result:
            return result
        time.sleep(.1)
    raise AssertionError('Integration condition timed out')


def session():
    from lib import sttanywhere as stt
    from lib.accessibility import locate, text_of
    procs = []
    with tempfile.TemporaryDirectory(prefix='sttanywhere-background-') as folder:
        base = Path(folder)
        try:
            readfd, writefd = os.pipe()
            procs.append(subprocess.Popen(['Xvfb','-displayfd',str(writefd),'-screen','0','1024x768x24','-nolisten','tcp'],pass_fds=(writefd,),stderr=subprocess.DEVNULL))
            os.close(writefd)
            with os.fdopen(readfd) as f:
                os.environ['DISPLAY'] = ':'+f.readline().strip()
            os.environ.pop('XAUTHORITY',None)
            os.environ['GTK_USE_PORTAL']='0'
            os.environ['XDG_CONFIG_HOME']=str(base/'config')
            os.environ['XDG_CACHE_HOME']=str(base/'cache')
            os.environ['XDG_DATA_HOME']=str(base/'data')
            subprocess.run(['dbus-update-activation-environment','DISPLAY'],check=True)
            procs.append(subprocess.Popen(['xfwm4','--replace','--sm-client-disable','--compositor=off'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
            wait(lambda: '_NET_ACTIVE_WINDOW' in subprocess.check_output(['xprop','-root','_NET_SUPPORTED'],text=True))
            def launch(name, contents):
                file = base/name
                file.write_text(contents)
                proc = subprocess.Popen(['mousepad','--disable-server',str(file)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                procs.append(proc)
                def find():
                    try:
                        return stt.xdo('search','--all','--onlyvisible','--pid',proc.pid,'--class','Mousepad').splitlines()[0]
                    except (subprocess.CalledProcessError,IndexError):
                        return None
                window = wait(find)
                stt.xdo('windowactivate','--sync',window)
                time.sleep(.4)
                return proc.pid,window
            pid,window=launch('original.txt','first\n\nsecond')
            stt.xdo('key','--clearmodifiers','ctrl+Home','End')
            anchor=stt.accessible('capture',{'pid':pid,'marker':stt.RECORDING+' '})
            # User changes paragraph and continues typing during transcription.
            stt.xdo('key','--clearmodifiers','ctrl+End')
            stt.xdo('key','--clearmodifiers','Return')
            stt.type_text('user elsewhere')
            anchor=stt.accessible('replace',{**anchor,'replacement':stt.TRANSCRIBING+' '})
            node=locate(anchor)
            text,before=text_of(node)
            oldcaret=text.get_caret_offset()
            _,other=launch('other.txt','another application')
            assert stt.xdo('getactivewindow')==other
            job=base/'job';job.mkdir(mode=0o700)
            (job/'audio.wav').write_bytes(b'test audio')
            (job/'state.json').write_text(json.dumps({'status':'transcribing','window':window,'window_class':'Mousepad','anchor':anchor,'config':{'auto_paste':True},'profile':{}}))
            with mock.patch.object(stt,'transcribe',return_value='DICTATED'):
                stt.worker(job)
            state=json.loads((job/'state.json').read_text())
            assert state['status']=='done',state
            assert stt.xdo('getactivewindow')==other,('Focus was stolen',stt.xdo('getactivewindow'),other,stt.xdo('getwindowname',stt.xdo('getactivewindow')))
            text,after=text_of(locate(state['anchor']))
            assert after=='firstDICTATED\n\nsecond\nuser elsewhere',repr(after)
            assert text.get_caret_offset()==oldcaret+len('DICTATED')-19,(text.get_caret_offset(),oldcaret)
            # A second job with a removed marker must not touch the moved caret.
            stt.xdo('windowactivate','--sync',window)
            stt.xdo('key','--clearmodifiers','ctrl+Home')
            second=stt.accessible('capture',{'pid':pid,'marker':stt.RECORDING+' '})
            node=locate(second)
            current=text_of(node)[1]
            node.get_editable_text_iface().set_text_contents(current.replace(stt.RECORDING+' ',''))
            unchanged=text_of(node)[1]
            stt.xdo('windowactivate','--sync',other)
            job2=base/'job2';job2.mkdir(mode=0o700)
            (job2/'audio.wav').write_bytes(b'test audio')
            (job2/'state.json').write_text(json.dumps({'status':'transcribing','window':window,'window_class':'Mousepad','anchor':second,'config':{'auto_paste':True},'profile':{}}))
            with mock.patch.object(stt,'transcribe',return_value='SHOULD NOT INSERT'):
                stt.worker(job2)
            assert json.loads((job2/'state.json').read_text())['status']=='clipboard'
            assert text_of(node)[1]==unchanged
            assert stt.xdo('getactivewindow')==other
            print(json.dumps({'result':'PASS','checks':['real Mousepad background replacement','no focus stealing','original marker position despite moved caret','new paragraph preserved','caret position preserved','removed marker leaves document untouched','clipboard fallback without focus'],'provider_call':False},indent=2))
        finally:
            for proc in reversed(procs):
                proc.terminate()
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:proc.kill()

if __name__=='__main__':
    if '--session' in sys.argv:
        session()
    else:
        subprocess.run(['dbus-run-session','--','/usr/bin/python3',str(Path(__file__).resolve()),'--session'],check=True)
