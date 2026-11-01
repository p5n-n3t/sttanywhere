#!/usr/bin/env python3
"""Real isolated Chromium extension/native-host end-to-end checks; no STT API calls.

Requires Playwright's bundled Chromium (or PLAYWRIGHT_CHROMIUM_EXECUTABLE), Xvfb,
and the project browser-host installer. The temporary browser profile, config,
and bridge socket are removed at exit. The user's Chrome profile is never opened.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def wait(check, timeout=15):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        try:
            last = check()
            if last:
                return last
        except Exception as error:  # browser startup/navigation can be transient
            last = error
        time.sleep(.1)
    raise AssertionError(f"Integration condition timed out: {last!r}")


HTML = """<!doctype html><meta charset=utf-8><title>STT Browser QA</title>
<input id=text value="ab cd"><textarea id=area>line one\nline two</textarea>
<div id=edit contenteditable=true>editable seed</div><input id=password type=password>
<input id=other placeholder="Other tab target">
"""


def session():
    from playwright.sync_api import sync_playwright

    required = ("Xvfb", "xfwm4", "xprop", "dbus-run-session")
    missing = [name for name in required if not shutil.which(name)]
    if missing:
        raise SystemExit("Missing integration dependencies: " + ", ".join(missing))
    extension = ROOT / "browser"
    if not (extension / "manifest.json").is_file() or not (extension / "background.js").is_file():
        raise SystemExit("Browser extension build is incomplete")
    installer = ROOT / "bin/install-browser-bridge"
    if not installer.is_file():
        raise SystemExit("Native bridge installer is not available yet")

    procs = []
    server = None
    context = None
    playwright_browsers = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", Path.home() / ".cache/ms-playwright"))
    with tempfile.TemporaryDirectory(prefix="sttanywhere-browser-qa-") as folder:
        base = Path(folder)
        home = base / "home"
        home.mkdir(mode=0o700)
        xdg_data = base / "data"
        browser_config = home / ".config"
        runtime = base / "runtime"
        for path in (xdg_data, browser_config, runtime):
            path.mkdir(mode=0o700)

        # Each run uses its own X server and native bridge runtime.
        readfd, writefd = os.pipe()
        xvfb = subprocess.Popen(["Xvfb", "-displayfd", str(writefd), "-screen", "0", "1280x900x24", "-nolisten", "tcp"],
                                pass_fds=(writefd,), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        os.close(writefd)
        procs.append(xvfb)
        with os.fdopen(readfd) as display_pipe:
            display = display_pipe.readline().strip()
        assert display.isdigit(), "Xvfb failed to allocate display"

        env = os.environ.copy()
        env.update({
            "HOME": str(home), "DISPLAY": ":" + display,
            "XDG_CONFIG_HOME": str(browser_config), "XDG_DATA_HOME": str(xdg_data),
            "PLAYWRIGHT_BROWSERS_PATH": str(playwright_browsers),
            "STTANYWHERE_BROWSER_CONFIG_ROOT": str(browser_config),
            "STTANYWHERE_BROWSER_RUNTIME_DIR": str(runtime),
            "GTK_USE_PORTAL": "0", "NO_AT_BRIDGE": "0",
        })
        for key in ("XAUTHORITY", "SESSION_MANAGER", "DESKTOP_STARTUP_ID"):
            env.pop(key, None)
        env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        os.environ.update(env)
        if shutil.which("dbus-update-activation-environment"):
            subprocess.run(["dbus-update-activation-environment", "DISPLAY", "XDG_RUNTIME_DIR"], env=env, check=True)
        wm = shutil.which("xfwm4")
        procs.append(subprocess.Popen([wm, "--sm-client-disable", "--compositor=off"], env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        wait(lambda: "_NET_ACTIVE_WINDOW" in subprocess.check_output(["xprop", "-root", "_NET_SUPPORTED"], env=env, text=True))
        install = subprocess.run([str(installer)], cwd=ROOT, env=env, text=True, capture_output=True)
        if install.returncode:
            raise AssertionError(f"Browser host install failed ({install.returncode}): {install.stdout}\n{install.stderr}")
        # Recent Chrome builds resolve Native Messaging registrations relative
        # to the isolated user data directory. Mirror this test registration
        # there while preserving the ordinary config-root registration too.
        user_data = str(base / "chrome-profile")
        profile_hosts = Path(user_data) / "NativeMessagingHosts"
        profile_hosts.mkdir(parents=True, mode=0o700)
        registered = browser_config / "google-chrome" / "NativeMessagingHosts" / "org.sttanywhere.bridge.json"
        shutil.copyfile(registered, profile_hosts / registered.name)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_port}/"
        executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        with sync_playwright() as playwright:
            chromium_path = executable or shutil.which("google-chrome-stable") or shutil.which("google-chrome") or playwright.chromium.executable_path
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=user_data,
                executable_path=chromium_path,
                headless=False,
                ignore_default_args=["--disable-extensions"],
                args=["--no-first-run", "--no-default-browser-check", "--disable-background-networking",
                      "--enable-unsafe-extension-debugging",
                      "--disable-sync", "--password-store=basic"],
            )
            cdp = context.browser.new_browser_cdp_session()
            loaded = cdp.send("Extensions.loadUnpacked", {"path": str(extension)})
            assert loaded.get("id"), f"Chrome did not load the extension: {loaded!r}"
            worker_logs = []
            def attach_worker(worker):
                worker.on("console", lambda message: worker_logs.append(f"{message.type}: {message.text}"))
            context.on("serviceworker", attach_worker)
            page = context.new_page()
            page.goto(url)
            page.locator("#text").focus()
            # Access through the native bridge's public client, so each request
            # traverses Unix socket -> native host stdio -> MV3 worker -> content script.
            from lib import browser_bridge

            socket_path = Path(f"/tmp/sttanywhere-{os.getuid()}/browser.sock")
            # The environment override is expected to isolate this socket.
            socket_path = runtime / "browser.sock"
            try:
                wait(lambda: socket_path.exists())
            except AssertionError:
                print("Native host manifest:", list((browser_config / "google-chrome" / "NativeMessagingHosts").glob("*.json")))
                print("Extension service workers:", [worker.url for worker in context.service_workers])
                print("Chrome targets:", [(target.get("type"), target.get("url")) for target in cdp.send("Target.getTargets")["targetInfos"]])
                print("Extension worker console:", worker_logs)
                raise

            def capture(selector):
                page.locator(selector).focus()
                return browser_bridge.request("capture", marker="(Recording....) ")

            def transition_and_finish(anchor, value, selector, field_kind="input"):
                status = browser_bridge.request("replace", anchor=anchor, replacement="(Transcribing....) ")
                assert status.get("state") == "transcribing" and status.get("inserted") is False, status
                if field_kind == "input":
                    current = page.locator(selector).input_value()
                else:
                    current = page.locator(selector).inner_text()
                assert "(Transcribing....) " in current, current
                final = browser_bridge.request("replace", anchor=anchor, replacement=value)
                assert final.get("inserted") is True, final

            # Input: capture at an interior caret, continue editing while the
            # marker is present, then focus a different tab before completion.
            page.locator("#text").evaluate("el => el.setSelectionRange(3, 3)")
            anchor = capture("#text")["anchor"]
            recording = page.locator("#text").input_value()
            assert recording.startswith("ab (Recording....) ") and recording.endswith("cd"), recording
            page.locator("#text").press("End")
            page.keyboard.insert_text(" USER")
            other = context.new_page()
            other.goto(url)
            other.locator("#other").focus()
            transition_and_finish(anchor, "DICTATED ", "#text")
            value = page.locator("#text").input_value()
            assert value == "ab DICTATED cd USER", value
            assert other.locator("#other").input_value() == "", "Completion was redirected to the other tab"
            assert other.evaluate("document.hasFocus()"), "Completion stole focus from the other tab"
            print("Native input capture, edited caret, other-tab completion, transcribing and final: PASS")

            # Textarea and contenteditable each use the same live native path.
            page.bring_to_front()
            page.locator("#area").focus()
            page.locator("#area").evaluate("el => el.setSelectionRange(5, 5)")
            anchor = capture("#area")["anchor"]
            assert "(Recording....) " in page.locator("#area").input_value()
            transition_and_finish(anchor, "WORDS ", "#area")
            assert page.locator("#area").input_value() == "line WORDS one\nline two"
            print("Native textarea capture and replacement: PASS")

            page.locator("#edit").focus()
            page.locator("#edit").evaluate("el => { const r=document.createRange(); r.selectNodeContents(el); r.collapse(false); const s=getSelection(); s.removeAllRanges(); s.addRange(r); }")
            anchor = capture("#edit")["anchor"]
            transition_and_finish(anchor, " WORDS", "#edit", "editable")
            assert page.locator("#edit").inner_text() == "editable seed WORDS"
            print("Native contenteditable capture and replacement: PASS")

            # Sensitive fields reject before any marker is inserted.
            page.locator("#password").focus()
            try:
                browser_bridge.request("capture", marker="(Recording....) ")
            except browser_bridge.BrowserBridgeError as error:
                assert "password" in str(error).lower(), str(error)
            else:
                raise AssertionError("Password field was accepted for capture")
            assert page.locator("#password").input_value() == ""
            print("Password field rejected without placeholder: PASS")

            # Navigation invalidates the document capability; a later result
            # cannot be delivered into the new page or a newly focused field.
            page.locator("#text").focus()
            stale = capture("#text")["anchor"]
            page.goto(url + "?navigated=1")
            page.locator("#other").focus()
            try:
                browser_bridge.request("replace", anchor=stale, replacement="MUST NOT INSERT")
            except browser_bridge.BrowserBridgeError:
                pass
            else:
                raise AssertionError("Navigation did not expire the captured anchor")
            assert page.locator("#other").input_value() == ""
            print("Navigation invalidation and stale-result rejection: PASS")

            print(json.dumps({"result": "PASS", "provider_call": False,
                              "browser_binary": chromium_path,
                              "native_manifest_root": str(browser_config),
                              "checks": ["real MV3 content/background scripts", "real native messaging host",
                                         "recording marker", "transcribing marker", "final replacement",
                                         "input edit and changed caret", "completion while another tab is focused",
                                         "textarea", "contenteditable", "password rejection", "navigation invalidation"]}, indent=2))
            context.close()
            context = None
        if server:
            server.shutdown()
            server.server_close()
        for proc in reversed(procs):
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    if "--session" in sys.argv:
        session()
    else:
        subprocess.run(["dbus-run-session", "--", sys.executable,
                        str(Path(__file__).resolve()), "--session"], check=True)
