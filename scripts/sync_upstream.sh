#!/usr/bin/env bash
# sync_upstream.sh
#
# Sync the fork (rimon-fc/omnigent) with upstream (omnigent-ai/omnigent).
# Adds the `upstream` remote if missing, fetches, and merges upstream/main
# into the current branch. Fails hard on merge conflict so a half-merged tree
# is never published.
#
# Idempotent: safe to re-run. Makes no downstream push (that is publish_substrate.sh).
#
# Env overrides:
#   UPSTREAM_URL   - upstream git URL (default: omnigent-ai/omnigent)
#   UPSTREAM_REF   - branch to merge (default: main)
set -euo pipefail

UPSTREAM_URL="${UPSTREAM_URL:-https://github.com/omnigent-ai/omnigent.git}"
UPSTREAM_REF="${UPSTREAM_REF:-main}"

log() { printf '[sync] %s\n' "$*"; }

# Ensure we are in a git repo.
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  echo "error: not inside a git repository" >&2
  exit 1
}

# Add or update the upstream remote.
if git remote get-url upstream >/dev/null 2>&1; then
  git remote set-url upstream "$UPSTREAM_URL"
else
  git remote add upstream "$UPSTREAM_URL"
fi
log "upstream = $UPSTREAM_URL ($UPSTREAM_REF)"

git fetch --no-tags upstream "$UPSTREAM_REF"

BEFORE="$(git rev-parse HEAD)"
UPSTREAM_SHA="$(git rev-parse "upstream/${UPSTREAM_REF}")"
log "fork HEAD     = $BEFORE"
log "upstream HEAD = $UPSTREAM_SHA"

if [ "$BEFORE" = "$UPSTREAM_SHA" ] || git merge-base --is-ancestor "$UPSTREAM_SHA" HEAD; then
  log "already up to date with upstream; nothing to merge."
  exit 0
fi

# Merge upstream. Abort + fail on conflict.
if ! git merge --no-edit "upstream/${UPSTREAM_REF}"; then
  log "merge conflict detected; aborting (no publish)."
  git merge --abort || true
  exit 2
fi

AFTER="$(git rev-parse HEAD)"
log "merged: $BEFORE -> $AFTER"
