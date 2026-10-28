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
