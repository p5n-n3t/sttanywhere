#!/usr/bin/env python3
"""Real X11 RECORD shortcut/activity/privacy checks on a private Xvfb display."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lib import sttanywhere as stt


def main():
    with tempfile.TemporaryDirectory(prefix='sttanywhere-guard-test-') as folder:
        r,w=os.pipe()
        server=subprocess.Popen(['Xvfb','-displayfd',str(w),'-screen','0','800x600x24','-nolisten','tcp'],pass_fds=(w,),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        os.close(w)
        with os.fdopen(r) as stream:os.environ['DISPLAY']=':'+stream.readline().strip()
        os.environ.pop('XAUTHORITY',None)
        guard=None
        try:
            guard=stt.start_input_guard(Path(folder),{'shortcut':'<Alt>x'})
            assert guard,'X11 RECORD did not start'
            status=lambda:json.loads(Path(guard['path']).read_text())
            stt.xdo('key','--clearmodifiers','alt+x')
            time.sleep(.15)
            assert not status().get('dirty'),'Stop shortcut incorrectly marked input dirty'
            stt.xdo('mousemove','100','100');time.sleep(.1)
            assert not status().get('dirty'),'Pointer motion changed the text target'
            stt.xdo('key','a')
            end=time.monotonic()+3
            while not status().get('dirty') and time.monotonic()<end:time.sleep(.02)
            assert status().get('dirty'),'A normal key failed to invalidate the target'
            assert set(status()) <= {'ready','dirty','focus','reason'},'Input content was retained'
            print('PASS: Alt+X ignored, pointer motion allowed, ordinary input invalidates, no key contents stored')
        finally:
            stt.stop_input_guard(guard)
            server.terminate();server.wait(timeout=5)

if __name__=='__main__':main()
