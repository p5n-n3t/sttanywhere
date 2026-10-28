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
