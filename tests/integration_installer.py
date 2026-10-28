#!/usr/bin/env python3
"""Real terminal setup regression, isolated HOME; no provider or host UI calls."""
import errno
import json
import os
from pathlib import Path
import pty
import select
import signal
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def scenario(base, mode):
    home = base/mode
    config = home/'.config/sttanywhere'
    config.mkdir(parents=True,mode=0o700)
    cfg = json.loads((ROOT/'config/config.example.json').read_text())
    cfg['custom_user_field'] = {'preserve':True}
    (config/'config.json').write_text(json.dumps(cfg))
    (config/'credentials.env').write_text("GROQ_API_KEY='test-old-private'\nOTHER_KEY='keep-me'\n")
    original = {p.relative_to(home):p.read_bytes() for p in home.rglob('*') if p.is_file()}
    pid,fd=pty.fork()
    if pid==0:
        os.environ['HOME']=str(home)
        os.environ['XDG_CONFIG_HOME']=str(home/'.config')
        os.environ.pop('GROQ_API_KEY',None)
        flags=['--interactive','--no-bind']
        if mode=='dry-run': flags.append('--dry-run')
        os.execv(str(ROOT/'install.sh'),[str(ROOT/'install.sh'),*flags])
    output=b''
    def expect(needle):
        nonlocal output
        deadline=time.monotonic()+15
        while needle.encode() not in output:
            if time.monotonic()>deadline:
                raise AssertionError('Prompt timeout: '+needle+'\n'+output.decode(errors='replace'))
            if select.select([fd],[],[],.2)[0]:
                chunk=os.read(fd,65536)
                if not chunk:raise AssertionError('Installer exited before '+needle)
                output+=chunk
        # Search subsequent prompts only in later output.
        end=output.index(needle.encode())+len(needle.encode())
        prior=output[:end]
        output=output[end:]
        return prior
    transcript=b''
    try:
        prompts=['Choose number or name','Model [','HTTPS endpoint [','Source (','Choose number or name','XFCE shortcut [','Choose number or name','Choose number or name']
        for index,prompt in enumerate(prompts):
            transcript+=expect(prompt)
            if mode=='cancel' and index==0:
                os.write(fd,b'cancel\n');break
            os.write(fd,b'replace\n' if mode=='apply' and index==7 else b'\n')
        if mode!='cancel':
            if mode=='apply':
                transcript+=expect('(hidden; blank cancels):')
                os.write(fd,b'test-new-private-secret\n')
            transcript+=expect('Dependency installation')
            transcript+=expect('Choose number or name')
            os.write(fd,b'\n')
            if mode!='dry-run':
                transcript+=expect('Apply this plan?')
                os.write(fd,b'yes\n')
        deadline=time.monotonic()+15
        status=None
        while time.monotonic()<deadline:
            if select.select([fd],[],[],.1)[0]:
                try:
                    chunk=os.read(fd,65536)
                    if chunk:output+=chunk
                except OSError as error:
                    if error.errno!=errno.EIO:raise
            finished,result=os.waitpid(pid,os.WNOHANG)
            if finished:status=result;break
        assert status is not None,'Installer did not exit'
        assert os.waitstatus_to_exitcode(status)==0,output.decode(errors='replace')
        transcript+=output
        assert b'test-new-private-secret' not in transcript,'Hidden input leaked to terminal'
        assert b'test-old-private' not in transcript,'Existing key leaked to terminal'
        if mode in ('dry-run','cancel'):
            actual={p.relative_to(home):p.read_bytes() for p in home.rglob('*') if p.is_file()}
            assert actual==original,'Preview or cancellation mutated files'
            assert not (home/'.local').exists()
        else:
            after=json.loads((config/'config.json').read_text())
            assert after['custom_user_field']==cfg['custom_user_field']
            assert 'test-new-private-secret' in (config/'credentials.env').read_text()
            assert "OTHER_KEY='keep-me'" in (config/'credentials.env').read_text()
            assert (config/'credentials.env').stat().st_mode & 0o777==0o600
            assert (home/'.local/bin/sttanywhere').resolve()==ROOT/'bin/sttanywhere'
            assert list((config/'backups').glob('*/credentials.env'))
        print(mode+': PASS')
    finally:
        os.close(fd)
        try:os.kill(pid,signal.SIGTERM)
        except ProcessLookupError:pass


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='sttanywhere-installer-') as folder:
        for name in ('dry-run','cancel','apply'):
            scenario(Path(folder),name)
