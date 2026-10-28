---
title: Application compatibility and recovery behavior
description: Verified X11 insertion paths, clipboard boundaries, and provider recovery behavior for STT Anywhere.
keywords: [STT Anywhere compatibility, X11 text fields, AT-SPI, foreground fallback, clipboard recovery]
---

# Compatibility and recovery

STT Anywhere has several ways to deliver text. The exact path depends on whether the focused field exposes an accessible editable object, whether focus and input remain unchanged during recording, and whether the transcript is safe to type. Passing a check for one widget or app version does not establish support for every field in that app.

## Delivery paths

### AT-SPI anchored insertion

At recording start, STT Anywhere asks `/usr/bin/python3` and AT-SPI for the focused, editable, non-password text object in the active application process. It inserts a recording marker at the current caret or replaces one selected range with the marker. It saves the application process ID and start token, accessible object path, and marker. At completion it searches that same object and replaces the marker only if it is still unique and unchanged.

This path does not activate a window, paste a key chord, or set the caret/selection during completion. Editor buffer marks handle caret movement as the field is edited. If the process changes, the field is no longer editable, the marker is missing/duplicated/changed, or replacement cannot be verified, the destination is left alone; the transcript remains in the clipboard and private recovery file. Anchored multiline insertion can work when the application exposes a compatible AT-SPI editable-text object.

### Guarded foreground fallback

The default `foreground_fallback: true` covers fields that cleanly report no AT-SPI editable target. It starts an X11 RECORD monitor before the AT-SPI focus capture. The monitor records only readiness, a clean/dirty flag, the initial X input focus ID, and a short reason string. It does not record or store key contents. Modifier keys and the configured start/stop shortcut are ignored. Other keyboard events, mouse button events, and normal FocusIn/FocusOut transitions mark the session dirty, even if focus later returns. Pointer motion by itself is not treated as a change.

At completion, fallback delivery requires a ready, clean monitor and the same active X11 window and X input focus as the initial snapshot. This guard is conservative: if the monitor is unavailable or any relevant key, button, or normal focus event is detected, the transcript stays on the clipboard. The code rechecks focus at delivery; it does not raise the old window or redirect text to a different field.

- In terminal-class windows, a single-line ASCII transcript is sent as ordinary XTest keystrokes through `xdotool type` with a 5 ms inter-key delay. It bypasses terminal paste chords, which avoids the Ctrl+V versus Ctrl+Shift+V problem for command-line tools.
- In regular GUI windows, single-line ASCII and Unicode transcripts are copied to the clipboard, then STT Anywhere rechecks input and focus and uses the configured `paste_rules` chord. The job state records this as `foreground-paste`; terminal ASCII typing is recorded as `foreground-typing`.
- GUI multiline text is pasted atomically. Terminal multiline text stays on the clipboard for explicit paste, without synthesizing Return or Tab keys.
- Unsupported fields do not receive a placeholder. When no AT-SPI anchor is captured, a start notification is enabled by default so the user knows recording began.

AT-SPI anchoring and guarded foreground fallback are separate paths. A supported accessible field can receive a background anchored replacement after focus changes. The foreground fallback requires the original window and input focus still to match at delivery. Neither path promises arbitrary browser-tab or terminal compatibility.

### Clipboard and legacy modes

The wizard's clipboard-only choice sets `auto_paste: false`, leaving the result for manual use. If an anchored marker was already inserted, it may need manual replacement. The explicit `sttanywhere paste` command applies the configured chord to whichever field is currently focused; it does not restore an earlier focus target.

`delivery_mode: "legacy"` preserves the former X11 window activation, fixed Backspace replacement, and keyboard-paste flow. It can move focus and cannot restore an original browser tab or caret. Use it only when that behavior is appropriate for the target application.

## Compatibility evidence

| Application or case | Path exercised | Evidence and limit |
| --- | --- | --- |
| Mousepad editable text | AT-SPI anchor | Real Mousepad in isolated Xvfb; moved caret, edits in another paragraph, and a second window did not redirect the replacement. A removed marker fell back to clipboard. Transcription was stubbed; no provider request. |
| Thunar path field after Ctrl+L | AT-SPI anchor | A selected range was replaced at capture. Isolated application check; no provider request. |
| Chrome address bar | Foreground clipboard paste | Isolated Xvfb; text was pasted only while the original window/focus and input guard remained clean. No provider request. |
| Chrome web form field with Unicode | Foreground clipboard and paste rule | Isolated Xvfb; Unicode text was pasted after the guard check. No provider request. |
| Chrome field edited during recording | Unsafe foreground fallback | The input guard marked the session dirty; the transcript was not inserted over the user's new text. |
| XFCE terminal prompt with a read-only test command | Foreground ASCII typing | Isolated Xvfb; `xdotool type` delivered the test line without a paste chord. This does not verify every terminal, TUI, or live Codex/Claude session. |
| Chrome toggle/stop/detached-worker pipeline | Foreground clipboard paste | Isolated Xvfb and silent PulseAudio sink; recorder and worker ran through the real path with a stub transcript. Delivery succeeded without a provider request. |
| Firefox address bar | Foreground clipboard paste | Isolated test passed for the address bar. Firefox web-field fixture remains under verification; no full Firefox dictation claim. |
| Chrome multiline textarea | Guarded GUI paste | Two lines arrived intact in the isolated form; no provider request. |
| Firefox address bar and web input | Guarded GUI paste | Both passed in a disposable Firefox profile and isolated display; no provider request. |
| Groq transcription from generated speech | Provider adapter | A live synthetic-speech request using the WAV-to-FLAC upload path succeeded. This proves one provider request path, not insertion compatibility in an application. |

The editor and field checks above exercise real application widgets, but they mock or bypass speech transcription. They are not live Codex, Claude, or 1Password dictation tests. Firefox address-bar and web-input checks passed with a fresh profile; its full live microphone-to-provider path was not exercised. The old `integration_x11.py`/`integration_terminal.py` checks exercise the explicitly selected legacy paste path; the X11 test makes a live provider request and may incur provider charges, while the terminal check uses a stub transcript.

## Provider errors and explicit recovery

The HTTPS transport does not log or include credentials, request bodies, response bodies, or full URLs in its sanitized errors. It classifies DNS, TLS, connection-refused, connection-reset, timeout, HTTP-status, redirect, invalid-response, and related failures. Timeout/reset and some generic connection failures are marked `outcome_unknown`: a provider may have accepted or completed the request even though the client did not receive the result. The client does not retry requests automatically.

Use `sttanywhere retry JOB` only as an explicit recovery action for a failed job with retained audio. It makes at most one provider submission per invocation and always recovers to the clipboard; it never modifies an old document, activates a window, or reuses an old caret. If `transcript.txt` was already saved, retry reuses it and does not send another provider request. On successful recovery, the original audio is retained. If no transcript was saved, the command sends the audio once, which may be billable; take `outcome_unknown` seriously before retrying.

One local 101-second recording failure was later recovered as a 936-character transcript after one provider POST and a local clipboard-side fix. The original network cause was not preserved in the logs. This incident does not identify a specific DNS/TLS/timeout cause or prove that an ambiguous provider request is safe to submit again.

For OpenAI-compatible multipart profiles, `lossless_upload: true` converts WAV input to a temporary FLAC file before upload; the source WAV remains intact. The example config sets `request_timeout` to 180 seconds. These settings do not change provider billing or make a request idempotent.

## Relevant settings

```json
{
  "delivery_mode": "anchored",
  "foreground_fallback": true,
  "notify_recording": true,
  "notify_completion": false,
  "lossless_upload": true,
  "request_timeout": 180
}
```

`foreground_fallback: false` disables the guarded no-anchor fallback. It does not disable AT-SPI anchored insertion. `lossless_upload: false` keeps WAV uploads in their original container for the OpenAI-compatible adapter.
