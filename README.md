# STT Anywhere

[![Checks](https://github.com/p5n-n3t/sttanywhere/actions/workflows/check.yml/badge.svg?branch=main)](https://github.com/p5n-n3t/sttanywhere/actions/workflows/check.yml) [![MIT license](https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square)](LICENSE) [![Linux X11](https://img.shields.io/badge/platform-Linux%20X11-333333.svg?style=flat-square&logo=linux)](#platform-support) [![Python and Bash](https://img.shields.io/badge/runtime-Python%20%2B%20Bash-3776AB.svg?style=flat-square&logo=python)](lib/sttanywhere.py) [![Groq Whisper](https://img.shields.io/badge/default-Groq%20Whisper-F55036.svg?style=flat-square)](config/config.example.json) [![AT-SPI anchored insertion](https://img.shields.io/badge/insertion-AT--SPI-20A99A.svg?style=flat-square)](lib/accessibility.py) [![Open issues](https://img.shields.io/github/issues/p5n-n3t/sttanywhere.svg?style=flat-square)](https://github.com/p5n-n3t/sttanywhere/issues) [![Early development](https://img.shields.io/badge/status-early%20development-orange.svg?style=flat-square)](docs/ROADMAP.md)

<p align="center"><img src="assets/logo.svg" alt="STT Anywhere microphone and cursor logo" width="144"></p>

**Linux voice dictation and speech-to-text with Groq Whisper, configurable providers, and an Alt+X global hotkey.** Built for Xubuntu/XFCE on X11. Press **Alt+X** to start or stop recording; STT Anywhere transcribes the audio and, when the focused application exposes a supported editable text field through AT-SPI, replaces its recording marker with the transcript in that same field.

STT Anywhere uses a small Bash launcher and Python client. Audio capture and clipboard/X11 integration use Linux desktop utilities; anchored insertion uses the system Python with PyGObject and AT-SPI. Transcription is sent to a provider you configure. The project does not bundle a speech model or make provider calls until you record or transcribe a file.

[Quick start](#install) · [Provider configuration](config/config.example.json) · [Tested behavior](docs/VERIFICATION.md) · [Alternatives](docs/ALTERNATIVES.md) · [Roadmap](docs/ROADMAP.md) · [Contributing](CONTRIBUTING.md)

## Platform support

| Platform or delivery path | Current status |
| --- | --- |
| Xubuntu / XFCE / X11 | Implemented; local microphone, shortcut and insertion checks recorded in verification |
| Other Linux X11 desktops | Desktop integration needs verification; supplied shortcut installer is XFCE-specific |
| Background insertion in Mousepad | Tested with a moved caret and another window in front |
| Arbitrary browser tabs and terminal prompts | Not guaranteed; unsupported targets use clipboard recovery |
| Linux Wayland | No supported desktop backend yet |
| macOS and Windows | Planned assessment only; no native builds or installers yet |

STT Anywhere is open source under the MIT license. Provider API usage may have separate charges. It is an API client, not an offline speech-recognition engine; only the configured provider receives submitted microphone audio.

## What it does

- Records from the default microphone and transcribes on toggle, or transcribes an existing audio file.
- Supports Groq (the example default) and OpenAI-compatible multipart transcription, AssemblyAI's asynchronous upload/transcription flow, and Cloudflare's base64 JSON transcription endpoint through provider profiles. A custom OpenAI-compatible profile is also included as a template.
- Captures the focused editable AT-SPI text object and inserts a unique marker there. At completion it replaces that exact marker in the same object, even if the caret moved meanwhile.
- Provides clipboard-only fallback, status, cancellation, diagnostics, foreground context, and an explicit paste command.
- Offers an installer for the **Alt+X** Xfce keyboard shortcut and migration from an existing xhisper setup.

Anchored insertion uses AT-SPI editable-text APIs; it does not activate a window or send typing keys at transcription completion. It records the target process ID and start token, accessible object path, and marker, then replaces the marker only if that exact marker remains unique in the original editable object. If the field is unsupported, the anchor is ambiguous or removed, or the app process changes, STT Anywhere leaves the destination untouched and keeps the transcript on the clipboard and in the private recovery file; it does not type the transcript into another target. If an anchor was captured but cannot be replaced, or automatic replacement is disabled, the marker may remain in the field and should be replaced manually. Browser tabs and rich editors are supported only when they expose the focused editable object through AT-SPI; STT Anywhere does not enumerate tabs or infer which one the user intends. Anchored mode is not universal terminal support. For editor workflows that need keyboard paste, see `delivery_mode: "legacy"` and the explicit `paste` command below.

## Requirements

- Xubuntu (or a compatible Linux desktop) using X11 and Xfce for the supplied shortcut setup.
- Bash, Python 3, and the system audio, clipboard, accessibility, and X11 utilities installed by `./install.sh --deps`, including `python3-gi`, `gir1.2-atspi-2.0`, `xdotool`, and `xprop`.
- An account and API key for one of the configured transcription providers.
- Network access when requesting a transcription.

The installer and `doctor` command report missing local prerequisites. Provider HTTP requests use Python's standard library. The accessibility bridge runs with `/usr/bin/python3` and the system-installed GI/AT-SPI bindings; no pip package installation is required.

## Install

From a checkout, run:

```bash
./install.sh
```

The installer creates the user configuration directory, prepares a private credentials file, and configures the Xfce **Alt+X** binding. If it finds the legacy xhisper `~/.env` setup, it migrates the Groq credential and disables the old binding/services so they do not compete with the new shortcut. Inspect the installer before running it if you want to review those changes.

Configuration lives in `~/.config/sttanywhere/config.json`. Credentials belong in `~/.config/sttanywhere/credentials.env`; keep this file private and never commit it. The example provider profiles are in [`config/config.example.json`](config/config.example.json).

Choose a provider by setting `provider` in the config, then put its API key in `credentials.env` using the `api_key_env` name shown in that provider's profile. For example, the default Groq profile uses `GROQ_API_KEY`; OpenAI uses `OPENAI_API_KEY`. Cloudflare also needs the account identifier used by the configured endpoint. Set a valid profile and key before attempting a transcription. Run:

```bash
sttanywhere doctor
sttanywhere status
```

`doctor` checks local setup and configuration; it does not verify provider credentials by making a live API request.

## Use

The installer provides the Alt+X toggle. The command-line interface is also available directly from the checkout as `bin/sttanywhere`:

```bash
sttanywhere toggle             # start or stop a microphone dictation
sttanywhere status             # show recording/transcription state
sttanywhere cancel             # cancel the active operation
sttanywhere doctor             # inspect local dependencies and configuration
sttanywhere context            # describe the currently focused application and paste chord
sttanywhere paste              # paste clipboard into the currently focused application
sttanywhere transcribe clip.wav # transcribe an existing audio file
```

The toggle records from the PulseAudio/PipeWire default input and submits the audio once to the selected provider. A successful result is copied to the clipboard. With the default `delivery_mode: "anchored"`, the result replaces the unique recording marker in the original AT-SPI editable object. If an anchor cannot be safely captured or verified, the status is `clipboard`; the transcript stays on the clipboard and in the recovery file, with no typing sent to another target. `auto_paste: false` disables automatic replacement; if a marker was inserted, replace it manually and paste the clipboard text. Completion notifications are off by default (`notify_completion: false`).

`sttanywhere context` prints JSON with `window_class`, `window_name`, `window_pid`, `foreground_process`, and the selected `paste_chord` (as well as the X11 window ID). It uses `xdotool` for the active window ID/name and `xprop` for `WM_CLASS`, since Ubuntu's `xdotool` does not provide a `getwindowclassname` command. Foreground process detection only reports a terminal descendant when exactly one TTY candidate is unambiguous; multiple tabs or sessions produce an unknown value instead of a guess. The `paste` command sends the configured chord to the field that is focused when you invoke it; it does not refocus the window captured at recording start.

`transcribe FILE` submits the named file through the selected provider profile without inserting it into an application. Provider requests require network access and may consume provider quota or incur charges under that provider's terms. Requests are not automatically retried.

Recordings and per-job status are kept under `/tmp/sttanywhere-UID/job-*` with private permissions. A successful transcription removes its audio file and retains the transcript for recovery; failed or cancelled jobs may leave audio and logs there. Remove job directories when you no longer need their recovery files; `/tmp` is normally cleared when the machine reboots.

The installer also supports `./install.sh --deps` to install system dependencies and `./install.sh --no-bind` to skip the Xfce shortcut setup. These options are useful for reviewing or separating the setup steps.

The legacy keyboard mode uses one trailing space on each placeholder so its fixed Backspace counts can remove them: `(Recording....) ` has 16 characters, and `(Transcribing....) ` has 19. Anchored mode inserts and replaces these markers through the captured accessible text object. The single trailing space is marker padding, not part of the transcript.

## Configuration and privacy

- `config.json` selects and configures a provider profile. Start from [`config/config.example.json`](config/config.example.json).
- `credentials.env` stores API keys separately from the non-secret configuration. Keep it readable only by your user account.
- Microphone audio is sent to the provider selected by the active profile when a recording is transcribed. Consult that provider's privacy and retention terms for its service.
- Local diagnostics do not demonstrate successful authentication or a completed provider transcription.

### Settings

| Setting | Example default | Purpose |
| --- | --- | --- |
| `provider` | `groq` | Name of the active entry under `providers`. |
| `shortcut` | `<Alt>x` | Xfce key binding configured by the installer. |
| `audio_source` | `default` | PulseAudio/PipeWire source name passed to `ffmpeg`. |
| `max_recording_seconds` | `600` | Maximum capture duration per microphone recording. |
| `max_audio_bytes` | `25000000` | Upper bound on the audio file submitted. |
| `request_timeout` | `90` | Timeout in seconds for an individual HTTP request. |
| `job_timeout` | `300` | AssemblyAI asynchronous job deadline. |
| `delivery_mode` | `anchored` | `anchored` replaces the original AT-SPI marker in place. `legacy` opts into the older focus-and-keyboard insertion flow. |
| `auto_paste` | `true` | In anchored mode, automatically replace the marker in the captured editable object. In legacy mode, control the older keyboard paste behavior. |
| `notify_completion` | `false` | Show a desktop notification when a transcription finishes. |
| `paste_rules` | app-specific | Ordered matches for context fields such as `foreground_process`, `window_name`, and `window_class`; the first match selects a chord. |
| `paste_mode` | `auto` | Fallback chord: terminal paste for a `window_class` matching `terminal_pattern`, otherwise regular paste. `terminal` always uses the terminal chord. |

The example config has two paste rules for Codex/Claude contexts: first `foreground_process`, then `window_name`, each mapped to `ctrl+v`. If neither matches, the default terminal fallback uses `ctrl+shift+v`; other windows use `ctrl+v`. Rules choose a chord for the explicit `sttanywhere paste` command; anchored delivery edits the accessible text object directly and does not use paste chords.

For example, add or adjust per-app rules like this:

```json
{
  "delivery_mode": "anchored",
  "paste_mode": "auto",
  "paste_rules": [
    {"match": {"foreground_process": "codex|claude"}, "chord": "ctrl+v"},
    {"match": {"window_name": "codex|claude"}, "chord": "ctrl+v"},
    {"match": {"window_class": "my-terminal"}, "chord": "ctrl+shift+v"}
  ]
}
```

`delivery_mode: "legacy"` is an explicit opt-in for the older keyboard flow. It activates the captured X11 window at stop/completion and sends Backspace/paste keystrokes, so it can move desktop focus and still cannot restore a browser tab or the original caret. The `paste` command is also a keyboard action, but it targets whichever field is currently focused when you invoke it.

Provider profiles specify an adapter (`openai`, `assemblyai`, `json_base64`, or `raw`), HTTPS endpoint, model, credential variable name, and response path as needed. The example includes Groq, OpenAI, AssemblyAI, Cloudflare Workers AI, and a custom OpenAI-compatible profile. Compatibility depends on the selected service's API; custom endpoints have not been validated against every provider.

### Provider references

- [Groq speech-to-text API](https://console.groq.com/docs/speech-to-text)
- [OpenAI speech-to-text guide](https://platform.openai.com/docs/guides/speech-to-text)
- [AssemblyAI speech-to-text documentation](https://www.assemblyai.com/docs/speech-to-text)
- [Cloudflare Whisper Large v3 Turbo model](https://developers.cloudflare.com/workers-ai/models/whisper-large-v3-turbo/)

## Development checks

Run the shell syntax check and standard-library unit tests from the repository root:

```bash
bash -n bin/sttanywhere
bash -n install.sh
python3 -m unittest discover -s tests
```

The GitHub Actions workflow runs the same checks on pushes and pull requests. These checks do not make live provider requests.

## License

MIT. See [`LICENSE`](LICENSE).

## Live integration checks

The opt-in test below opens an isolated Xvfb desktop and loops generated speech through a private PulseAudio sink, then sends **one live, potentially billable Groq request**. It checks the legacy keyboard-paste path only; it does not verify anchored insertion in a live Codex or Claude application. It does not type into the host desktop or play through your speakers. Extra test dependencies: `xvfb xfwm4 dbus-x11 python3-tk espeak pulseaudio-utils`.

```bash
python3 tests/integration_x11.py
```

`/usr/bin/python3 tests/integration_background.py` exercises the anchored path against a real Mousepad editor in an isolated Xvfb session, with a mocked transcription response and no provider request. It checks replacement in the original accessible object after the caret moves, preservation of other edits, no focus stealing, and clipboard fallback when the marker is gone. `tests/integration_x11.py` and `tests/integration_terminal.py` cover the legacy keyboard flow; the terminal check uses a stub transcription and makes no network request. These checks do not establish universal browser or terminal support.

The default Groq model is `whisper-large-v3-turbo`, matching this machine's normal xhisper recording path. The real API endpoint is `https://api.groq.com/openai/v1/audio/transcriptions`; `https://groq.com` is the provider website.

A provider such as Merge needs a documented speech-to-text contract before a correct profile can be supplied. Use the custom profile if it accepts OpenAI-compatible multipart audio; otherwise add an adapter. Changing a model name alone cannot make a text-only model transcribe audio.

## Change providers and shortcuts

Edit `~/.config/sttanywhere/config.json` and set `"provider": "assemblyai"`, `"cloudflare"`, `"openai"`, or your own profile name. Add the matching variable to the private `~/.config/sttanywhere/credentials.env`:

```bash
ASSEMBLYAI_API_KEY='your-key'
CLOUDFLARE_API_TOKEN='your-token'
CLOUDFLARE_ACCOUNT_ID='your-account-id'
OPENAI_API_KEY='your-key'
```

For OpenAI-compatible services, copy the `custom` profile and change `endpoint`, `model`, and `api_key_env`. `options` adds provider request fields, such as `"language": "en"` or a transcription prompt. `response_path` selects a nested JSON result such as `result.text`. The `raw` adapter sends file bytes directly; `json_base64` sends an `audio` field containing base64 plus any configured options. AssemblyAI uses its separate upload, submission, and polling flow. Only speech-to-text models and supported API contracts work.

To change the hotkey, edit `shortcut` (for example `<Super>d`) and rerun `./install.sh`. It removes the previous STT Anywhere binding and installs the new one. It refuses to overwrite a shortcut belonging to an unrelated application. Changes to provider or audio settings take effect on the next recording; a running job keeps the settings it started with.

## Restore the previous setup

Installation saves private backups under `~/.config/sttanywhere/backups/<timestamp>/`. The first full migration's `shortcuts.json` records xhisper's old live shortcuts; `systemd-units.txt` and `migration.json` record service state and migration actions. Later reinstall backups may record STT Anywhere instead, so choose the original migration backup.

Use Xfce **Settings → Keyboard → Application Shortcuts** to remove the STT Anywhere command and restore the old command from `shortcuts.json` (on this machine, `/usr/local/bin/xhisper` on Alt+X). Restore any backed-up autostart `.desktop` files, and re-enable only the xhisper units listed as disabled in the original `migration.json` if they were enabled previously. STT Anywhere does not delete the old xhisper binary or its credential source. Remove the `~/.local/bin/sttanywhere` symlink if uninstalling. Save any recovery transcripts you want before deleting its private config and `/tmp` state.

## How STT Anywhere compares

Hotkey voice typing, Whisper dictation and bring-your-own-key transcription already exist in other projects. STT Anywhere focuses on a small, inspectable Linux client, provider profiles, and anchored insertion in supported accessible editors with clipboard recovery. See the [sourced alternatives review](docs/ALTERNATIVES.md); no “only one of its kind” claim is made.

## Documentation and project discovery

- [Documentation index](docs/README.md)
- [Keyword, topic and dashboard guide](docs/DISCOVERABILITY.md)
- [Interactive setup and native platform roadmap](docs/ROADMAP.md)
- [Bug reports and feature requests](https://github.com/p5n-n3t/sttanywhere/issues/new/choose)

Related searches: Linux voice dictation, Xubuntu voice typing, XFCE speech-to-text, Groq Whisper hotkey, AT-SPI background insertion, OpenAI-compatible transcription, and xhisper migration. Terminal and browser workflows remain subject to the capability limits above.
