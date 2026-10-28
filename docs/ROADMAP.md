---
title: Interactive setup and macOS Windows roadmap
description: Implementation assessment for friendlier STT Anywhere configuration, platform adapters, and a separate Loopback bridge setup experience.
keywords: [dictation setup wizard, macOS dictation port, Windows speech-to-text, configuration UI, Loopback MCP]
---

# Setup experience and platform roadmap

Status: **design assessment, not shipped features**. The current application targets Linux X11 with an XFCE shortcut installer. This document does not announce a macOS, Windows or Wayland release.

## More interactive STT Anywhere installation

A terminal wizard is a small-to-medium extension of the current installer. A desktop settings application, secure OS-keychain integration, packaging and extensive recovery testing are a larger product effort. Reuse the current configuration and provider adapters rather than creating an incompatible fork.

A useful first-run flow:

1. Detect OS, X11/Wayland, XFCE, audio services, Python and AT-SPI bindings. Explain supported and unsupported paths before changing anything.
2. Offer dependency installation, with an explicit plan showing packages and privileges needed.
3. Select provider and model, with an advanced endpoint/adapter editor. Keep capability-specific request fields; endpoint/model alone cannot adapt every API.
4. Reuse an existing credential or collect a masked key into private storage. Never show it in logs, process arguments or preview output.
5. Select a microphone and run a local level/record-and-playback check only when requested.
6. Choose the shortcut, check conflicts, and preview exactly which old xhisper settings or services would be changed.
7. Explain anchored insertion versus clipboard fallback. Offer a sandbox text field and a capability probe.
8. Preview settings, then apply atomically with backup/rollback. Preserve rerun and noninteractive installation paths.
9. Offer a clearly labeled optional live API test, showing that it sends audio and may incur provider charges.
10. Finish with a compact result report, repair instructions and an uninstall/restore path.

Acceptance checks should cover cancellation before apply, rerun idempotency, shortcut collisions, unavailable microphones, missing keys, broken network responses, partial dependency failure and restoration of the previous configuration. A wizard must not automatically change an existing key or switch a working user's provider.

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
