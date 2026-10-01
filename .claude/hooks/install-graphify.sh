#!/bin/bash
# Installs the graphify CLI in Claude Code on the web sessions.
set -euo pipefail
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi
if ! command -v graphify >/dev/null 2>&1; then
  pip install --quiet graphifyy
fi
