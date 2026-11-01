#!/usr/bin/env python3
"""Real XFCE/tmux terminal bridge flow under Xvfb; no audio or provider call."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib import sttanywhere as stt


def wait_for(check, timeout=15):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        try:
            last = check()
            if last:
                return last
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for integration condition; last={last!r}")


def main():
    procs = []
    env = os.environ.copy()
    env["GVFS_DISABLE_FUSE"] = "1"
    env["GTK_USE_PORTAL"] = "0"
    with tempfile.TemporaryDirectory(prefix="stt-terminal-bridge-") as folder:
        base = Path(folder)
        runtime = base / "runtime"
        runtime.mkdir(mode=0o700)
        env["STTANYWHERE_RUNTIME_DIR"] = str(runtime)
        env["XDG_CONFIG_HOME"] = str(base / "config")
        env["XDG_CACHE_HOME"] = str(base / "cache")
        env["XDG_DATA_HOME"] = str(base / "data")
        try:
            readfd, writefd = os.pipe()
            procs.append(subprocess.Popen(
                ["Xvfb", "-displayfd", str(writefd), "-screen", "0", "1024x768x24", "-nolisten", "tcp"],
                pass_fds=(writefd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            os.close(writefd)
            with os.fdopen(readfd) as stream:
                env["DISPLAY"] = ":" + stream.readline().strip()
            env.pop("XAUTHORITY", None)
            os.environ.update({key: env[key] for key in (
                "DISPLAY", "GVFS_DISABLE_FUSE", "GTK_USE_PORTAL", "STTANYWHERE_RUNTIME_DIR",
                "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME")})
            procs.append(subprocess.Popen(
                ["xfwm4", "--replace", "--sm-client-disable", "--compositor=off"],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

            wait_for(lambda: "_NET_ACTIVE_WINDOW" in subprocess.check_output(
                ["xprop", "-root", "_NET_SUPPORTED"], env=env, text=True))

            mock_cli = base / "mock_cli.py"
            result_file = base / "submitted.txt"
            mock_cli.write_text(
                "import os, pathlib, sys\n"
                "print('MOCK> ', end='', flush=True)\n"
                "line = sys.stdin.readline()\n"
                "pathlib.Path(os.environ['STT_MOCK_SUBMITTED']).write_text(line)\n"
                "print('SUBMITTED', flush=True)\n"
            )
            env["STT_MOCK_SUBMITTED"] = str(result_file)
            title = "STT Managed Terminal Test"
            terminal = subprocess.Popen(
                ["xfce4-terminal", "--disable-server", f"--title={title}", "--execute",
                 str(ROOT / "bin/sttanywhere-terminal"), sys.executable, str(mock_cli)],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            procs.append(terminal)

            def xdo(*args):
                return subprocess.check_output(["xdotool", *args], env=env, text=True,
                                               stderr=subprocess.DEVNULL).strip()

            def get_terminal_window():
                windows = xdo("search", "--name", f"^{title}$").splitlines()
                return windows[0] if windows else None

            window = wait_for(get_terminal_window)
            xdo("windowactivate", "--sync", window)
            def mock_prompt_ready():
                registrations = list(runtime.glob("terminal-*.json"))
                if not registrations:
                    return False
                reg = json.loads(registrations[0].read_text())
                pane = subprocess.check_output(
                    ["tmux", "-L", reg["socket"], "capture-pane", "-p", "-t", reg["pane"]],
                    env=env, text=True)
                return "MOCK>" in pane

            wait_for(mock_prompt_ready)

            context = stt.target_context()
            assert str(context["window"]) == str(window), context
            marker = stt.RECORDING + " "
            anchor = stt.capture_anchor(context, marker)
            assert anchor and anchor.get("backend") == "terminal", anchor

            # Stopping recording replaces only the captured marker; this is
            # the same bridge seam used by the controller before worker dispatch.
            anchor = stt.accessible("replace", {**anchor, "replacement": stt.TRANSCRIBING + " "})
            assert anchor.get("marker") == stt.TRANSCRIBING + " ", anchor

            # The completion worker must update the original pane in background,
            # without activating or unminimizing the XFCE terminal.
            xdo("windowminimize", window)
            other = base / "other.txt"
            other.write_text("other window")
            other_title = "STT Unrelated Window"
            other_term = subprocess.Popen(
                ["xfce4-terminal", "--disable-server", f"--title={other_title}", "--execute",
                 "/bin/sleep", "60"], env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            procs.append(other_term)
            other_window = wait_for(lambda: (xdo("search", "--name", f"^{other_title}$").splitlines() or [None])[0])
            xdo("windowactivate", "--sync", other_window)
            assert xdo("getactivewindow") == other_window
            anchor = stt.accessible("replace", {**anchor, "replacement": "final words"})
            assert anchor.get("marker") == "final words", anchor
            assert xdo("getactivewindow") == other_window, "Background completion stole focus"
            assert result_file.exists() is False, "Terminal line was submitted"

            # Capture a second recording marker, advance to transcribing, then
            # simulate user edits to the live CLI line before final completion.
            xdo("windowactivate", "--sync", window)
            context = stt.target_context()
            changed_anchor = stt.capture_anchor(context, marker)
            changed_anchor = stt.accessible("replace", {
                **changed_anchor, "replacement": stt.TRANSCRIBING + " "})
            reg = json.loads(Path(changed_anchor["registry"]).read_text())
            subprocess.run(["tmux", "-L", reg["socket"], "send-keys", "-t", reg["pane"],
                            "-l", "--", " user-edit"], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            xdo("windowminimize", window)
            xdo("windowactivate", "--sync", other_window)
            before = subprocess.check_output(
                ["tmux", "-L", reg["socket"], "capture-pane", "-p", "-t", reg["pane"]], text=True)
            try:
                stt.accessible("replace", {**changed_anchor, "replacement": "must not insert"})
            except ValueError as error:
                assert "changed" in str(error).lower() or "clipboard" in str(error).lower(), str(error)
            else:
                raise AssertionError("Changed terminal input was accepted")
            after = subprocess.check_output(
                ["tmux", "-L", reg["socket"], "capture-pane", "-p", "-t", reg["pane"]], text=True)
            assert after == before, "Fail-safe changed the edited terminal line"
            assert "user-edit" in after and stt.TRANSCRIBING in after, after
            assert xdo("getactivewindow") == other_window, "Rejected completion stole focus"
            assert not result_file.exists(), "The mock CLI received Enter unexpectedly"
            print(json.dumps({"result": "PASS", "checks": [
                "real XFCE terminal with private managed tmux session",
                "recording marker inserted into the mock CLI line",
                "transcribing marker replaces recording marker",
                "final text replaces transcribing marker while target window is minimized",
                "completion leaves the unrelated active window focused",
                "changed terminal input is rejected and left unchanged",
                "no Enter was sent; mock CLI line remains unsubmitted"
            ], "provider_call": False, "audio_capture": False}, indent=2))
        finally:
            for process in reversed(procs):
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)


if __name__ == "__main__":
    main()
