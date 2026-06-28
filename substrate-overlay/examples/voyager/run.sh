#!/usr/bin/env bash
# omni-keel-test launcher — runs the Voyager multi-agent travel concierge.
#
# Voyager (SUBSTRATE) orchestrates four specialists (flights / stays /
# experiences / context), all of which call the co-consult KEEL MCP server at
# http://127.0.0.1:8000/mcp (declared in the specs as a url).
#
# START THE KEEL SERVER FIRST (separate terminal, leave running):
#   cd ../keel-usage-tests-etc/co-consult && ./run.sh http
#
# Prereqs:
#   1. substrate installed and credentials configured:  substrate setup
#      No API keys needed — runs on subscriptions/CLIs you already have:
#        claude-sdk agents  -> your Claude Pro/Max subscription (claude CLI)
#        experiences        -> codex-native = your authenticated codex CLI
#      (To run everything on Claude, set experiences' harness to claude-sdk.)
#   2. co-consult/.env filled in (Sabre / Expedia / SerpAPI / LIVN creds). The
#      server loads tools either way; live calls need real keys. See
#      ../keel-usage-tests-etc/co-consult/.env.example.
#
# Usage:
#   ./run.sh            -> interactive REPL
#   ./run.sh server     -> substrate server (web UI) at :6767
set -euo pipefail

AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-repl}"

if [ "$MODE" = "server" ]; then
  exec substrate server start
else
  exec substrate run "$AGENT_DIR"
fi
