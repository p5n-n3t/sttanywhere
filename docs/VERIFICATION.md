---
title: STT Anywhere verification record
description: Observed unit, desktop, credential migration and live Groq verification with explicit compatibility limits.
keywords: [dictation testing, AT-SPI Mousepad, Groq Whisper verification, Linux X11]
---

# Verification — 2026-10-28

Tested locally on JQ's Xubuntu X11 machine. This records observed checks, not a claim of universal application or provider compatibility.

| Check | Result |
| --- | --- |
| Python offline unit tests | 22 passed |
| Bash syntax, Python compilation, Git whitespace | Passed |
| Groq file transcription with migrated xhisper credential | Passed; `whisper-large-v3-turbo` |
| Isolated Xvfb editor, actual audio loopback capture and live Groq request | Passed |
| Exact 16/19 BackSpace replacement | Passed with one trailing padding space per placeholder |
| Original editor prefix preservation | Passed: `Before ` remained intact |
| Clipboard equals transcription | Passed |
| Successful audio removed | Passed |
| Detached stop invocation | Returned in 2.297 seconds; upload/response executed in separate session |
| Real XFCE terminal on isolated display | Passed Ctrl+Shift+V and prefix preservation using a stub transcription; no provider call in this test |
| Missing Groq key | Exit 1 and native notification path verified; actual configured credential remained present |
| Installed CLI symlink | `~/.local/bin/sttanywhere doctor` passed |
| Reinstall and shortcut change | Passed; old binding removed; final binding restored to Alt+X |
| Credentials/config permissions | Mode 0600, private configuration directory |
| Logo | SVG parsed successfully as XML |

The synthetic speech sample was transcribed as:

> Speech to text anywhere is working. This is a test of voice dictation.

The editor ended with exactly:

> Before Speech to text anywhere is working. This is a test of voice dictation.

Initial integration failures found and fixed Ubuntu xdotool's missing `getwindowclassname` command, incorrect placeholder padding, and isolated window-manager startup timing. The final editor run passed after these fixes. No test sent keyboard input to the user's active applications.

The old live binding was `/usr/local/bin/xhisper`. The final live binding is `/home/jq/sttanywhere/bin/sttanywhere toggle`. No xhisper user/system unit was found during inspection. The installer includes stop/disable and process/autostart cleanup for installations that have them. Private migration backups are outside Git, under `~/.config/sttanywhere/backups/`.

AssemblyAI, OpenAI and Cloudflare adapters have mocked request tests only. Their credentials and live API calls were not tested. No Merge-specific contract has been verified. Browser tab/caret restoration is not possible from a window ID alone; see README and the clipboard-only setting.

Reproduction:

```bash
bash -n bin/sttanywhere install.sh
python3 -m unittest discover -s tests -v
# Optional: creates an isolated display; one potentially billable Groq request
python3 tests/integration_x11.py
# Optional: isolated real terminal paste, no network
python3 tests/integration_terminal.py
```

## Background insertion correction — 2026-10-28

The original keyboard approach above could raise the original window and paste at a changed caret. Those results apply to the now-explicit `delivery_mode: legacy` path. The installed configuration and default example now use `delivery_mode: anchored`.

New verification:

- **29 offline tests passed**, including valid/missing/changed accessibility anchors, clipboard fallback without xdotool input, and foreground/title/custom paste rules.
- **Real Mousepad on an isolated Xvfb/D-Bus session passed** (`/usr/bin/python3 tests/integration_background.py`). The test inserted the marker after `first`, moved to another paragraph, typed `user elsewhere`, changed to a different Mousepad window, and ran the real accessibility delivery with a stubbed provider response. The original document became exactly `firstDICTATED\n\nsecond\nuser elsewhere`. The second window kept focus, and the original caret retained its logical position.
- Deleting the original marker caused clipboard fallback; no text was inserted or deleted and focus stayed in the other window.
- A real temporary PTY process named `codex` was correctly discovered as the sole foreground descendant. This tests OS process detection, not a real Codex provider session or actual Codex text insertion.
- Inspection of the user's active Warp window reported no accessible editable text field and no unambiguous foreground TTY. Therefore background terminal insertion and active Codex identification in that Warp window are **not verified or claimed**. Results there remain on the clipboard for manual insertion.
- Default rules select Ctrl+V for identifiable Codex/Claude foreground processes or matching window titles; other terminal contexts retain Ctrl+Shift+V fallback. Per-application rules are configurable.

AT-SPI edits are bounded to a stored application PID/start token, accessible object path, and a unique unchanged marker in that field. No full document text is written to state files. No `windowactivate`, paste key, or BackSpace event is used by anchored completion. It does not call caret/selection setters during replacement, letting editor buffer marks track user edits naturally.

The Mousepad regression uses no network request. Existing provider behavior remains covered by the prior live Groq check and current adapter tests. Background browser-tab support depends on the browser exposing and retaining the original editable object; it has not been validated here. Generic background insertion across arbitrary terminal applications is not implemented by X11 keystroke simulation.

## Guided terminal installer — 2026-10-28

The installer now offers a five-step terminal wizard, a final plan confirmation, masked key replacement, read-only preview, configuration overrides and explicit unattended mode. It makes no API calls or automatic microphone recordings.

- **41 offline unit tests passed**: previous runtime/provider coverage plus configuration preservation, credential precedence, data-only legacy parsing, preview redaction, dry-run with dependencies, no-bind preparation, shortcut-conflict preflight, invalid settings, masked replacement, cancellation and non-TTY behavior.
- **Real pseudo-terminal tests passed** (`python3 tests/integration_installer.py`), using isolated temporary HOME/config directories. They exercised dry-run, early cancellation and actual no-bind application. A replacement test key did not appear in terminal output; the private file was mode 0600, another key and an unrelated config field survived, and previous credentials were backed up.
- **Actual desktop noninteractive reinstall passed**: existing config.json and credentials.env stayed byte-for-byte identical; both remained mode 0600. The installed CLI symlink, current Alt+X binding and `doctor` output were verified. No secret value was printed.
- Shell syntax, Python compilation and whitespace checks passed.

Dependency installation is previewed and tested through mocks; these checks did not install operating-system packages. Packages are not automatically uninstalled on later failure. Config and credentials use atomic file replacement with private backups; the installer does not claim a transaction spanning package installation, systemd and desktop settings. Backups support manual recovery after an interrupted apply. Automatic rollback, resumable setup, a GUI and native macOS/Windows installers are not implemented.

## General text fields and retained-recording recovery — 2026-10-28

This update retains AT-SPI saved-position delivery and adds a generic, guarded foreground path. It is not a Mousepad whitelist. GTK selected text is now handled at capture, including an address bar selected with Ctrl+L. A cleanly unavailable AT-SPI target can use foreground delivery; an ambiguous/partially changed anchor cannot.

Verified locally:

- **67 offline unit tests passed**, covering foreground guards, GUI ASCII/Unicode/multiline paste, terminal ASCII typing, refusal after changed input/focus, transport classification/redaction, and explicit recovery without duplicate provider submissions after a transcript is saved.
- **Real X11 RECORD guard test passed** (`python3 tests/integration_guard.py`): Alt+X itself did not dirty the guard, pointer movement alone was allowed, normal typing invalidated it, and the state file retained only flags/focus/reason, not key contents.
- **Real field integration suite passed** (`STT_TEST_FIREFOX=1 /usr/bin/python3 tests/integration_fields.py`) using isolated Xvfb display and disposable application profiles:
  - Thunar selected path entry: AT-SPI replacement.
  - Chrome address bar: guarded clipboard paste.
  - Chrome web input: English/Arabic text preserved through clipboard insertion.
  - Chrome multiline textarea: both lines arrived in the field.
  - Later user edits were preserved and blocked fallback insertion.
  - Focus switching away and back invalidated the guard.
  - The real recorder/stop/detached-worker path delivered into Chrome through a silent PulseAudio sink and a stubbed provider response.
  - XFCE terminal input received ASCII text through normal key input without a paste chord.
  - Firefox address bar and Firefox web input received the expected text in a fresh profile. Snap startup required the normal user session bus; no sandbox was disabled.
- The separate **live Groq synthetic-speech test passed** through WAV-to-FLAC multipart upload using the configured model/key. The result was `This is the Speech-to-Text-Anywhere compatibility test.` GUI checks above did not make provider calls.
- The user's retained 101.1-second recording was recovered into a private 936-character transcript. One explicit provider submission completed; when a clipboard-side problem occurred, the saved transcript was reused for copying without another provider request. The original WAV remains retained. No original window/document was modified during recovery.
- The old network failure's exact cause is unknown because the prior implementation suppressed its underlying reason. New errors classify DNS/TLS/refusal/reset/timeout/HTTP/response failures and preserve outcome-unknown metadata without leaking request data or credentials. There are no automatic provider retries. The default request timeout is now 180 seconds; lossless FLAC reduced the retained recording from 3,235,278 to 2,077,648 bytes in a local conversion check.
- Home-folder enumeration still succeeded after GUI tests; isolated sessions retain `GVFS_DISABLE_FUSE=1`.

The generic foreground guard checks X11 input and focus, not arbitrary application-private document state. It does not create a saved cursor anchor in opaque browser widgets or terminal TUIs. Such targets require unchanged input/focus for automatic foreground insertion; normal focus transitions invalidate the guard even if focus later returns. Terminal multiline text stays on the clipboard for explicit paste. Actual 1Password controls and live Codex/Claude sessions were not exercised; no universal background-insertion guarantee is made.

The [field regression screenshot](../assets/screenshots/field-regression.png) shows only disposable test content. It is evidence of real widgets and a stubbed provider pipeline, not a screenshot of a live user transcription.
