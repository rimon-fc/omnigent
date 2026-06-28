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

# Merge upstream. Abort + fail on genuine content conflicts.
#
# The fork intentionally DELETES the inherited upstream CI (everything under
# .github/workflows/ except publish-substrate.yml, plus .github/dependabot.yml)
# so those jobs never run on the fork. Upstream still ships and edits those
# files, which produces "deleted by us / modified by them" merge conflicts on
# every sync. Those are EXPECTED and resolved in favour of the fork (stay
# deleted); only OTHER conflicts are real and must halt the publish.
if ! git merge --no-edit "upstream/${UPSTREAM_REF}"; then
  # Resolve the expected CI deletions: anything under .github/workflows (bar
  # publish-substrate.yml) or .github/dependabot.yml -> keep removed.
  while IFS= read -r path; do
    case "$path" in
      .github/workflows/publish-substrate.yml) : ;;  # keep ours (already present)
      .github/workflows/*|.github/dependabot.yml)
        git rm -f --quiet --ignore-unmatch "$path" >/dev/null 2>&1 || true
        ;;
    esac
  done < <(git diff --name-only --diff-filter=U)

  # Any remaining unmerged paths are genuine conflicts -> abort + fail.
  if [ -n "$(git diff --name-only --diff-filter=U)" ]; then
    log "genuine merge conflict detected; aborting (no publish):"
    git diff --name-only --diff-filter=U | sed 's/^/  /' >&2
    git merge --abort || true
    exit 2
  fi

  # Re-assert the full CI removal (covers files upstream re-added cleanly), then
  # complete the merge commit.
  find .github/workflows -type f ! -name 'publish-substrate.yml' -delete 2>/dev/null || true
  rm -f .github/dependabot.yml 2>/dev/null || true
  git add -A .github >/dev/null 2>&1 || true
  git commit --no-edit >/dev/null 2>&1 || true
  log "merge: resolved expected CI deletions in favour of fork."
fi

# Belt-and-braces: even on a clean merge, upstream may have cleanly re-added a
# workflow we deleted. Re-assert removal so the fork's main never regains CI.
find .github/workflows -type f ! -name 'publish-substrate.yml' -delete 2>/dev/null || true
rm -f .github/dependabot.yml 2>/dev/null || true
if [ -n "$(git status --porcelain .github 2>/dev/null)" ]; then
  git add -A .github
  git -c user.name="${BOT_NAME:-substrate-bot}" \
      -c user.email="${BOT_EMAIL:-substrate-bot@users.noreply.github.com}" \
      commit -q -m "chore: prune inherited CI"
  log "re-pruned inherited CI re-added by upstream."
fi

AFTER="$(git rev-parse HEAD)"
log "merged: $BEFORE -> $AFTER"
