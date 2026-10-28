#!/usr/bin/env bash
# Migration is intentional: back up xhisper configuration, stop and disable its
# user services/processes/autostart, remove xhisper shortcuts, then bind STT Anywhere.
# No existing configuration or credential is deleted. Run without sudo.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == --deps ]]; then
  sudo apt-get update
  sudo apt-get install -y python3 ffmpeg pulseaudio-utils xdotool xclip x11-utils libnotify-bin xfconf
  shift
fi
exec python3 "$ROOT/lib/install.py" "$@"
