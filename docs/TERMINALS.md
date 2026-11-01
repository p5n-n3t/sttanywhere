---
title: Terminal dictation
description: Use STT Anywhere's managed tmux terminal for anchored dictation into a shell command line.
keywords: [STT Anywhere terminal, tmux dictation, shell command line, Warp terminal]
---

# Terminal dictation

STT Anywhere can anchor a dictation marker in a command line running inside its managed tmux terminal. This path is opt-in: start the shell or CLI with `sttanywhere-terminal`, then use the desktop **Alt+X** shortcut. The result replaces the marker in that pane without submitting the command. Review the line and press Enter yourself.

## Start a managed terminal

From the repository checkout:

```bash
./bin/sttanywhere-terminal
```

This starts the shell named by `$SHELL` (or `/bin/zsh` if unset) in a private tmux server and attaches to it. To start a CLI directly, pass its command and arguments:

```bash
./bin/sttanywhere-terminal codex
./bin/sttanywhere-terminal claude
```

The managed terminal requires `tmux` and an interactive terminal. Closing the managed wrapper stops its private tmux server. It does not attach to or take over an existing tmux session.

## What gets inserted

At capture, STT Anywhere writes a visible marker at the managed pane's current cursor. At completion it checks that the pane, foreground process, visible screen, and cursor still match the captured state, then replaces the marker. It does not send Enter. The adapter does not read or store the rest of the command line as a dictation transcript.

If the command line, pane output, cursor, process, or registration changed, STT Anywhere leaves the pane alone and keeps the transcript in the clipboard and private recovery file. Multiline results are clipboard-only. The adapter does not move terminal focus or infer a target in an unmanaged pane.

## Other terminals

The managed tmux path is the only terminal background anchor documented here. In other terminals, the existing guarded foreground fallback may type a single-line ASCII result only when the original window and input focus remain unchanged and the input monitor detected no user edits. GUI clipboard delivery rules, multiline behavior, and Unicode handling remain as described in the [compatibility guide](COMPATIBILITY.md). Unsafe or unavailable cases stay on the clipboard.

Warp and other terminal products are not universally supported. STT Anywhere does not infer which tab, shell, TUI, or command line the user intends in an arbitrary terminal. Use the managed wrapper when its tmux workflow fits; otherwise insert the clipboard result manually.

## Zsh line editor integration

An optional Zsh/ZLE adapter is available at [`shell/sttanywhere.zsh`](../shell/sttanywhere.zsh). It registers an interactive Zsh line editor and binds **Alt+X** in the Emacs and vi insert keymaps. It does not accept the command line. The adapter requires an interactive Zsh with `zsh/net/socket` and its matching STT Anywhere runtime.

The adapter's end-to-end desktop path is still being verified. Until that check is recorded, use the managed tmux wrapper for the documented terminal workflow. ZLE is not available while a child program owns the terminal input; this adapter does not make arbitrary TUI or terminal-tab targets safe.

## Verification

Real isolated XFCE/tmux integration passed recording and transcribing markers, final replacement while minimized, no focus stealing, changed-input rejection, and no Enter. Real Zsh PTY tests passed marker transitions and preservation of edits before and after a moved cursor. Run `env -u SESSION_MANAGER -u DESKTOP_STARTUP_ID dbus-run-session -- python3 tests/integration_terminal_bridge.py` and `python3 tests/integration_zsh.py`. Terminal-specific checks use disposable shells or panes and stub transcription; they make no provider request. They do not establish compatibility with every terminal emulator, live Codex or Claude session, TUI, or moved command-line cursor.
