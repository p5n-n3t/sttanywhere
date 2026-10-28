---
title: Interactive setup and macOS Windows roadmap
description: Shipped terminal setup wizard, remaining STT Anywhere setup improvements, future platform adapters, and a separate Loopback bridge roadmap.
keywords: [dictation setup wizard, macOS dictation port, Windows speech-to-text, configuration UI, Loopback MCP]
---

# Setup experience and platform roadmap

Status: **terminal setup wizard shipped; further setup and platform work remains planned**. The current application targets Linux X11 with an XFCE shortcut installer. This document does not announce a macOS, Windows or Wayland release.

## Shipped: guided terminal setup

`./install.sh` starts a five-step wizard when both stdin and stdout are TTYs. `--interactive` forces that mode; `--non-interactive` uses existing/default configuration without prompts. The wizard currently covers:

- Provider profile, model and HTTPS endpoint; custom profiles also prompt for adapter, credential variable name, and transcript response path.
- Microphone source listing and selection. It does not record a sample or report a microphone level.
- Shortcut configure/skip, shortcut value, and anchored, clipboard-only, or legacy delivery choice.
- Credential reuse or masked replacement, with private file before environment variable and legacy Groq `~/.env` lookup. Other assignments in `credentials.env` are retained.
- Optional Debian/Ubuntu package installation, followed by a visible plan and a final `yes` confirmation.

`--dry-run` previews without file, package, or shortcut mutations, including when combined with `--deps`. `--deps` selects apt package installation, `--no-bind` prepares config while leaving the existing shortcut and xhisper settings untouched, and command-line overrides are available for provider, model, endpoint, shortcut, audio source, and delivery mode. When shortcut setup is selected, the installer performs a read-only conflict preflight before writing config, saves private backups, and preserves unrelated config and credential entries.

The installer does not automatically call a provider, test an API key, capture microphone audio, open a GUI, or provide native platform ports. It prints recovery backup locations, but it does not promise automatic rollback after a partial failure. Isolated pseudo-terminal checks have exercised guided dry-run, cancellation, masked credential replacement, and `--no-bind` apply. See the repository's verification record for the current overall test evidence.

## Still planned: setup improvements

- Optional microphone level or short record/playback test, only after the user requests it.
- Optional live API credential/transcription check with a clear network and possible billing notice.
- Resumable wizard state for interrupted setup.
- More extensive failure-injection and recovery checks for interrupted package install, config replacement, and shortcut migration. Existing backups support manual recovery; automated all-or-nothing rollback is not implemented.

## A more configurable Loopback bridge

Loopback is a **separate project**, a portable MCP bridge rather than a dictation application. Read-only inspection of `/home/jq/loopback` on 2026-10-28 found an existing Bash installer with an interactive ingress choice, a noninteractive mode, port/host flags, and Cloudflare/Tailscale/local options. Its CLI already exposes configuration commands. A friendlier edition can therefore improve an existing flow rather than start from zero.

The assessment here is limited to its README and installer; no Loopback deployment or configuration was changed. Useful extensions would be a resumable wizard, named profiles, a dependency preflight, readable plan preview, ingress/auth health checks, masked credential handling, import/export that excludes secrets, and guided repair/rollback. A local settings UI could come later. Its remote-access and authentication boundaries need their own tests; STT Anywhere desktop tests say nothing about bridge security or public ingress correctness.

Loopback's documented Linux/macOS installer paths also do not establish native Windows support. Any Loopback implementation work belongs in that separate repository with its own verification.

## macOS and Windows STT Anywhere editions

The provider/configuration concepts can be reused. The desktop components must be replaced; packaging this Bash/X11 workflow inside a GUI is not sufficient.

| Component | Existing Linux implementation | macOS candidate | Windows candidate |
| --- | --- | --- | --- |
| Audio capture | ffmpeg PulseAudio/PipeWire input | AVFoundation/Core Audio adapter | WASAPI/audio capture adapter |
| Global shortcut | XFCE shortcut property | Native global shortcut/event registration | RegisterHotKey and native event loop |
| Clipboard | xclip | NSPasteboard | Windows clipboard APIs |
| Original-field identity | AT-SPI PID/start-token/object path/marker | Accessibility element and supported text attributes/ranges | UI Automation element and supported writable patterns |
| Credential storage | Private environment file | Keychain | Credential Manager or DPAPI-backed storage |
| Distribution | Source checkout and shell installer | Signed/notarized app or installer | Signed application/installer |

These are design candidates, not implemented or tested adapters. Accessibility is application-dependent on every OS. Windows TextPattern does not itself provide arbitrary multiline text editing; ValuePattern is available only on supporting controls. A native port must retain clipboard fallback rather than promise silent background writing to every terminal or browser tab. macOS accessibility attributes also need per-application capability and permission checks.

A practical sequence:

1. Extract the provider/job layer behind small audio, hotkey, clipboard, target-capture and insertion interfaces.
2. Add a native clipboard-first MVP on one additional OS with real microphone, hotkey, cancellation and error-path testing.
3. Add anchored insertion only for controls with a verified writable API. Track compatibility by app/version and test switching focus and moving the caret.
4. Add signing, packaging, secure credential storage, upgrade/rollback and real-device CI/manual validation.
5. Consider a common settings shell, such as Tauri or a native UI, once the platform interfaces are clear. A UI framework does not remove OS permissions or supply universal text insertion.

Relative difficulty: terminal wizard **small-to-medium**; a polished settings UI **medium**; each supported native OS edition **substantial**; universal background insertion across arbitrary applications **not a credible blanket promise**. Reliable estimates require target OS versions, an app compatibility list and test machines.

References: [Apple accessibility elements](https://developer.apple.com/documentation/applicationservices/axuielement), [Apple distribution packaging](https://developer.apple.com/documentation/xcode/packaging-mac-software-for-distribution), [Windows global hotkeys](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey), [UI Automation text-editing limits](https://learn.microsoft.com/en-us/dotnet/framework/ui-automation/add-content-to-a-text-box-using-ui-automation).
