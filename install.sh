#!/usr/bin/env bash
# Guided on a terminal; --non-interactive for scripts; --dry-run previews only.
# Applying shortcut setup backs up xhisper config, stops/disables its user
# services/processes/autostart, and replaces its XFCE shortcuts. Run without sudo.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$ROOT/lib/install.py" "$@"
