# STT Anywhere

<p align="center"><img src="assets/logo.svg" alt="STT Anywhere microphone and cursor logo" width="144"></p>

Local, keyboard-driven speech dictation for Xubuntu and other X11 desktops. Press **Alt+X** to start or stop recording; STT Anywhere transcribes the audio and pastes the result into the text field in the original X11 window.

STT Anywhere is a small Bash launcher and Python standard-library client. Audio capture and desktop integration use the X11/Linux utilities installed by the setup script; transcription is sent to a provider you configure. The project does not bundle a speech model or make provider calls until you record or transcribe a file.

## What it does

- Records from the default microphone and transcribes on toggle, or transcribes an existing audio file.
- Supports Groq (the example default) and OpenAI-compatible multipart transcription, AssemblyAI's asynchronous upload/transcription flow, and Cloudflare's base64 JSON transcription endpoint through provider profiles. A custom OpenAI-compatible profile is also included as a template.
- Inserts the result at the focused text cursor and provides status, cancellation, and diagnostics commands.
- Offers an installer for the **Alt+X** Xfce keyboard shortcut and migration from an existing xhisper setup.

Desktop text insertion depends on the target application accepting simulated keyboard input. The program saves and reactivates the original X11 window, but a window ID cannot restore a browser tab or a cursor position inside that window. If either changes before the result is pasted, it may land in a different tab or field. Review the destination before dictating sensitive text. Set `auto_paste` to `false` to keep the result on the clipboard and paste it yourself.

## Requirements

- Xubuntu (or a compatible Linux desktop) using X11 and Xfce for the supplied shortcut setup.
- Bash, Python 3, and the system audio, clipboard, and X11 utilities required by the installer and text insertion path, including `xdotool` and `xprop`.
- An account and API key for one of the configured transcription providers.
- Network access when requesting a transcription.

The installer and `doctor` command report missing local prerequisites. The implementation uses Python's standard library for the provider HTTP requests; no Python package installation is required.

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
sttanywhere transcribe clip.wav # transcribe an existing audio file
```

The toggle records from the PulseAudio/PipeWire default input and submits the audio once to the selected provider. A successful result is copied to the clipboard. With the default `auto_paste: true`, STT Anywhere tries to replace its placeholder in the original X11 window and paste the result there. It uses `xdotool` to capture the active window ID and window name, and `xprop` to read its `WM_CLASS`; Ubuntu's `xdotool` does not provide a `getwindowclassname` command. Set `auto_paste` to `false` to avoid automated window activation and paste; the result remains on the clipboard and you replace the placeholder and paste it yourself. `paste_mode` controls the paste chord (`auto` or `terminal`). `transcribe FILE` submits the named file through the selected provider profile without inserting it into an application. Provider requests require network access and may consume provider quota or incur charges under that provider's terms. Requests are not automatically retried.

Recordings and per-job status are kept under `/tmp/sttanywhere-UID/job-*` with private permissions. A successful transcription removes its audio file and retains the transcript for recovery; failed or cancelled jobs may leave audio and logs there. Remove job directories when you no longer need their recovery files; `/tmp` is normally cleared when the machine reboots.

The installer also supports `./install.sh --deps` to install system dependencies and `./install.sh --no-bind` to skip the Xfce shortcut setup. These options are useful for reviewing or separating the setup steps.

The insertion flow uses one trailing space on each placeholder so its fixed Backspace counts can remove them: `(Recording....) ` has 16 characters, and `(Transcribing....) ` has 19. The single trailing space is padding. It is not added to the dictated transcript.

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
| `auto_paste` | `true` | Try to return to the original window, replace the placeholder, and paste. |
| `paste_mode` | `auto` | Use terminal paste chord when the window class matches `terminal_pattern`; otherwise use regular paste. Set to `terminal` to always use the terminal chord. |

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

The opt-in test below opens an isolated Xvfb desktop and loops generated speech through a private PulseAudio sink, then sends **one live, potentially billable Groq request**. It checks the actual editor contents, prefix preservation, clipboard and audio cleanup. It does not type into the host desktop or play through your speakers. Extra test dependencies: `xvfb xfwm4 dbus-x11 python3-tk espeak pulseaudio-utils`.

```bash
python3 tests/integration_x11.py
```

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
