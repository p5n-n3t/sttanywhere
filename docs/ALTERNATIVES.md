---
title: STT Anywhere alternatives and positioning
description: Sourced comparison of Linux voice dictation, Whisper hotkey tools, and bring-your-own-key speech-to-text applications.
keywords: [Linux dictation alternatives, Whisper hotkey, Groq dictation, speech-to-text, AT-SPI]
---

# Alternatives and positioning

Research date: **2026-10-28**. STT Anywhere is **not the only hotkey dictation application**, nor the only configurable or bring-your-own-key speech-to-text tool. Do not advertise it as the world's first, only, or universally compatible dictation utility.

## Related open-source projects

| Project | Upstream-described overlap | What this review establishes |
| --- | --- | --- |
| [xhisper](https://github.com/imaginalnika/xhisper) | Linux dictation at the cursor using Groq, a user-selected hotkey, and local configuration. | A direct predecessor to the workflow STT Anywhere replaces. |
| [OpenWhispr](https://github.com/OpenWhispr/openwhispr) | Desktop hotkey dictation, local and BYOK cloud transcription, macOS/Windows/Linux packages. | Substantial category overlap; its [Linux target-probing issue](https://github.com/OpenWhispr/openwhispr/issues/1810) also documents AT-SPI target discovery. |
| [Handy](https://github.com/cjpais/Handy) | Configurable shortcut, local speech recognition and desktop text insertion on Windows, macOS and Linux. | A mature offline-oriented alternative to API-based dictation. |
| [WhisperWriter](https://github.com/savbell/whisper-writer) | Toggle or hold recording, settings UI, local Whisper or a configurable API endpoint, active-window text insertion. | Configurable recording and API integration are not exclusive features. |
| [Loquivox](https://github.com/Xhelliom/loquivox) | Linux hotkey dictation, pluggable transcription backends, settings UI and additional voice tools. | Linux provider choice and an interactive settings experience already exist elsewhere. |
| [libretype](https://github.com/atheerium/voxtype) | Linux hotkey dictation with configurable cloud providers and a setup script. | Multiple cloud providers and automated Linux setup are established approaches. Follow redirects if the upstream repository is renamed. |
| [Dictate](https://github.com/3choff/dictate) | Windows desktop dictation with multiple speech-to-text services, hotkeys, insertion and a settings UI. | A relevant reference for a future Windows edition. |
| [whisper-hud on GitLab](https://gitlab.com/ai-agent-skills/whisper-hud) | macOS system-wide hotkey dictation, BYOK OpenAI/Gemini, Apple Speech and local models. | Similar tools are hosted outside GitHub too. |
| [nerd-dictation on GitLab](https://gitlab.com/blixxen/nerd-dictation) | A hackable offline Vosk speech-to-text project. | Another public dictation implementation; this review does not establish its relationship to every upstream fork. |

These are upstream descriptions and selected source/issue inspection, **not runtime tests of competing applications**. Lack of a feature mention in a README is not proof that a project lacks that feature. In particular, this review does not establish whether any competitor implements the exact same saved-marker replacement algorithm.

## Defensible STT Anywhere positioning

> Lightweight, provider-configurable Linux dictation with anchored insertion in supported editors and safe clipboard fallback.

The current implementation combines:

- A Bash launcher and inspectable Python provider/client code.
- JSON profiles for Groq, OpenAI-compatible endpoints, AssemblyAI upload/polling and Cloudflare base64 JSON requests.
- An AT-SPI application/process/object anchor and unchanged-marker check, with background replacement verified in Mousepad.
- Clipboard recovery when background delivery cannot be verified.
- Configurable process/title paste rules and an xhisper-to-XFCE migration path.

These describe actual product choices. Their combination is a useful focus, not a proven exclusivity claim. STT Anywhere currently has a smaller platform and compatibility scope than several alternatives.

## Search scope and limits

The review used GitHub repository pages/source, GitLab project pages and its dictation topic, and indexed web queries across GitHub, GitLab and Codeberg. Example queries included `Linux Groq Whisper hotkey dictation`, `dictation AT-SPI`, `dictation background original marker`, and host-specific Whisper/dictation searches. No sufficiently verified Codeberg candidate is included here; that is not evidence of absence.

The search is not exhaustive. Public indexing misses new, private, renamed and unindexed repositories. Even an exhaustive negative search would not establish a patent or legal novelty claim. Recheck upstream claims before publishing future comparisons.
