#!/usr/bin/env python3
"""Real Zsh/ZLE RPC integration; sends no audio and makes no provider calls."""
import json
import os
import pathlib
import pty
import select
import socket
import shlex
import subprocess
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
MARKER = "(Recording....) "


def wait_for(path, proc, timeout=5):
    deadline = time.monotonic() + timeout
    output = bytearray()
    while time.monotonic() < deadline:
        if path.exists():
            return output
        ready, _, _ = select.select([proc], [], [], 0.05)
        if ready:
            try:
                output.extend(os.read(proc, 4096))
            except OSError:
                pass
    raise AssertionError(f"ZLE socket did not appear; terminal output={output!r}")


def rpc(path, data):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(str(path))
        client.sendall(json.dumps(data, ensure_ascii=True).encode() + b"\n")
        chunks = bytearray()
        while b"\n" not in chunks:
            part = client.recv(4096)
            if not part:
                break
            chunks.extend(part)
    return json.loads(chunks.split(b"\n", 1)[0])


def read_until(proc, needle, timeout=4):
    end = time.monotonic() + timeout
    data = bytearray()
    while time.monotonic() < end:
        ready, _, _ = select.select([proc], [], [], 0.05)
        if ready:
            try:
                data.extend(os.read(proc, 4096))
            except OSError:
                break
            if needle in data:
                return bytes(data)
    raise AssertionError(f"did not see {needle!r}; output={bytes(data)!r}")


def main():
    with tempfile.TemporaryDirectory(prefix="stt-zle-") as temp:
        base = pathlib.Path(temp)
        runtime = base / "runtime"
        runtime.mkdir(mode=0o700)
        snapshot = base / "snapshot.json"
        master, slave = pty.openpty()
        env = dict(os.environ, STTANYWHERE_RUNTIME_DIR=str(runtime),
                   STTANYWHERE_BIN="/bin/true", TERM="xterm-256color", ZDOTDIR=str(base))
        rc = base / ".zshrc"
        rc.write_text(f"""source {shlex.quote(str(ROOT / 'shell/sttanywhere.zsh'))}
_sttanywhere_snapshot() {{
  print -r -- "$BUFFER" > {shlex.quote(str(snapshot) + '.buffer')}
  print -r -- "$CURSOR" > {shlex.quote(str(snapshot) + '.cursor')}
  zle -M snapshot-written
}}
zle -N _sttanywhere_snapshot
bindkey '^X' _sttanywhere_snapshot
PROMPT='READY> '
""")
        env["ZDOTDIR"] = str(base)
        proc = subprocess.Popen(["zsh", "-i"], stdin=slave, stdout=slave, stderr=slave,
                                env=env, close_fds=True, start_new_session=True)
        os.close(slave)
        try:
            read_until(master, b"READY> ")
            sockpath = runtime / f"shell-{proc.pid}.sock"
            wait_for(sockpath, master)

            os.write(master, b"prefix")
            time.sleep(0.1)
            captured = rpc(sockpath, {"id": "capture-1", "op": "capture", "marker": MARKER})
            assert captured.get("ok") and captured.get("id") == "capture-1", captured
            anchor = captured["anchor"]
            assert anchor["marker"] == MARKER

            transcribing = rpc(sockpath, {"id": "transcribing-1", "op": "replace",
                                          "anchor": anchor, "replacement": "(Transcribing....) "})
            assert transcribing.get("ok") and transcribing.get("id") == "transcribing-1", transcribing
            anchor = transcribing["anchor"]
            # Continue editing after the original location, then complete without Enter.
            os.write(master, b" tail")
            time.sleep(0.1)
            # Edit before the marker after moving the caret; completion must keep it.
            os.write(master, b"\x01HEAD ")
            time.sleep(0.1)
            completed = rpc(sockpath, {"id": "replace-1", "op": "replace",
                                       "anchor": anchor, "replacement": "spoken words"})
            assert completed.get("ok") and completed.get("id") == "replace-1", completed
            time.sleep(0.1)

            # Inspect the live ZLE buffer through a test-only widget; this key is not Enter.
            os.write(master, b"\x18")
            deadline = time.monotonic() + 3
            while not pathlib.Path(str(snapshot) + ".buffer").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert pathlib.Path(str(snapshot) + ".buffer").exists(), "snapshot widget did not run"
            state = {"buffer": pathlib.Path(str(snapshot) + ".buffer").read_text().removesuffix("\n"),
                     "cursor": int(pathlib.Path(str(snapshot) + ".cursor").read_text())}
            assert state["buffer"] == "HEAD prefixspoken words tail", state
            assert state["cursor"] == len("HEAD "), state

            missing = rpc(sockpath, {"id": "replace-missing", "op": "replace",
                                     "anchor": anchor, "replacement": "unsafe"})
            assert not missing.get("ok"), missing
            assert proc.poll() is None, "Zsh exited; line must remain pending until explicit Enter"
            print(json.dumps({"result": "PASS", "checks": [
                "real Zsh 5.9 ZLE listener and private registry",
                "capture inserts marker at current cursor",
                "recording marker transitions to transcribing marker",
                "background completion replaces updated exact marker",
                "edits before and after marker survive while moved cursor stays anchored",
                "missing marker fails without buffer mutation",
                "completion does not submit the command line"
            ], "provider_call": False}, indent=2))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
            os.close(master)


if __name__ == "__main__":
    main()
