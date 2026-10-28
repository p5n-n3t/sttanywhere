---
title: Repository discovery and GitHub visibility
description: Search phrases, topic taxonomy, badge policy, and organization repository dashboard troubleshooting for STT Anywhere.
keywords: [Linux voice dictation, Groq Whisper, GitHub topics, Xubuntu speech-to-text, repository dashboard]
---

# Repository discovery and GitHub visibility

## Search intent and keywords

Use these phrases naturally in the About description, README headings, configuration guide and release notes. They are content targets, not ranking guarantees.

| Intent | Search phrases | Destination |
| --- | --- | --- |
| Linux desktop dictation | Linux voice dictation; Xubuntu voice typing; XFCE speech-to-text; X11 dictation hotkey | Main README and installation |
| Provider choice | Groq Whisper dictation; whisper-large-v3-turbo; OpenAI-compatible speech-to-text; AssemblyAI dictation; Cloudflare Whisper | Configuration and provider profiles |
| Insertion behavior | AT-SPI dictation; background text insertion; preserve original dictation position; clipboard fallback | Anchored-delivery explanation and verification |
| Terminal workflows | terminal voice typing; Codex dictation workflow; configurable paste shortcuts | Context and paste rules, with capability limits |
| Migration | xhisper alternative; migrate xhisper; Alt+X dictation Linux | Installer and migration documentation |

GitHub topics classify the implementation and current use cases: `linux`, `x11`, `xfce`, `xubuntu`, `dictation`, `speech-to-text`, `voice-to-text`, `voice-dictation`, `whisper`, `groq`, `transcription`, `at-spi`, `accessibility`, `clipboard`, `keyboard-shortcuts`, `python`, `bash`, `openai-compatible`, `developer-tools`, `productivity`.

There are 20 topics, GitHub's documented maximum. Issue labels organize work; they are not a separate repository SEO category. No macOS/Windows support topic or badge is used until working ports exist.

## Badge policy

Badges must link to evidence: GitHub Actions status, the MIT license, current Linux/X11 scope, the AT-SPI implementation, issues and provider configuration. No coverage percentage, downloads, release version or cross-platform support is invented. SVG badges describe the current project; decorative badges do not improve search ranking by themselves.

GitHub renders README content and topics, but repository Markdown does not let us set arbitrary HTML meta tags for GitHub's page. YAML documentation metadata is reusable if documentation is later published as a website; it is not a promise that GitHub or Google uses those fields as ranking signals. A documentation site, demonstrations, meaningful releases, external links and satisfied users are separate future discovery channels.

## Why an organization repository may be missing from your personal dashboard

Inspection on 2026-10-28 confirmed:

- The repository is public and owned by `p5n-n3t`.
- The authenticated account `joeyqleq` is an active organization admin and has repository admin/push/pull permissions.
- GitHub's accessible-repositories API includes `p5n-n3t/sttanywhere`.
- GitHub repository search already returns the repository.
- Existing commits are attributed to `joeyqleq`.

These checks rule out an obvious missing-repository or missing-access problem for that authenticated account. They do **not** inspect your browser's selected account, active filters or exact dashboard screen. A permission diagnosis should not be invented from a sidebar omission.

Use the [repository dashboard](https://github.com/repos), choose **Admin access**, then filter to organization **p5n-n3t** and search **sttanywhere**. A saved organization view is useful if you manage many repositories. GitHub's home/global-navigation **top repositories** is a convenience list, not a complete ownership inventory. The personal profile's own repositories view is also distinct from the organization's repository list; organization ownership remains with `p5n-n3t`.

No account transfer, permission change, personal star, subscription or profile pin was made as part of these improvements.

Sources: [GitHub repository dashboard](https://docs.github.com/en/repositories/creating-and-managing-repositories/viewing-all-your-repositories), [personal dashboard](https://docs.github.com/en/account-and-profile/get-started/personal-dashboard-quickstart), [topics](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics).
