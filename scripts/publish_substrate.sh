#!/usr/bin/env bash
# publish_substrate.sh
#
# Generate the rebranded tree from the (already upstream-synced) fork and
# publish it to the downstream repo as an incremental commit. Runs ALL
# guardrails before pushing. Designed to run from the fork repo root, in CI
# or locally.
#
# Steps:
#   1. Run scripts/rebrand.py against the working tree.
#   2. Guardrail: residual check (no "UNEXPECTED RESIDUAL").
#   3. Guardrail: idempotency (a 2nd rebrand changes nothing).
#   4. Guardrail: leak check (no `omnigent` / `substrate-ai` in published text,
#      except the allowlisted backward-compat lines and binary assets).
#   5. Stage the publishable tree (rebranded tree minus publish_exclude.txt).
#   6. Push to downstream as an incremental commit (version-derived message,
#      neutral bot identity). No-op if nothing changed.
#
# This script MUTATES the working tree (applies the rebrand). In CI that tree
# is a throwaway checkout. Locally, run it in a git worktree, never in a repo
# whose changes you want to keep.
#
# Required env (push step):
#   DOWNSTREAM_URL    - e.g. https://x-access-token:${TOKEN}@github.com/rimon-fc/substrate.git
#                       or  https://github.com/rimon-fc/substrate.git with creds via header
#   SUBSTRATE_DEPLOY_TOKEN - PAT with Contents:RW on rimon-fc/substrate (CI secret)
# Optional env:
#   DOWNSTREAM_REPO   - default: rimon-fc/substrate (used to build URL if DOWNSTREAM_URL unset)
#   DOWNSTREAM_REF    - default: main
#   BOT_NAME          - default: substrate-bot
#   BOT_EMAIL         - default: substrate-bot@users.noreply.github.com
#   DRY_RUN           - if set to 1, do everything except the final push
set -euo pipefail

DOWNSTREAM_REPO="${DOWNSTREAM_REPO:-rimon-fc/substrate}"
DOWNSTREAM_REF="${DOWNSTREAM_REF:-main}"
BOT_NAME="${BOT_NAME:-substrate-bot}"
BOT_EMAIL="${BOT_EMAIL:-substrate-bot@users.noreply.github.com}"
EXCLUDE_FILE="scripts/publish_exclude.txt"

log()  { printf '[publish] %s\n' "$*"; }
fail() { printf '[publish] ERROR: %s\n' "$*" >&2; exit 1; }

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# --------------------------------------------------------------------------- #
# 1. Rebrand
# --------------------------------------------------------------------------- #
log "running rebrand..."
python3 scripts/rebrand.py > /tmp/rebrand_report.txt 2>&1 || {
  cat /tmp/rebrand_report.txt >&2; fail "rebrand.py failed";
}

# --------------------------------------------------------------------------- #
# 2. Residual guardrail
# --------------------------------------------------------------------------- #
if grep -q "UNEXPECTED RESIDUAL" /tmp/rebrand_report.txt; then
  grep -A20 "UNEXPECTED RESIDUAL" /tmp/rebrand_report.txt >&2
  fail "rebrand reported unexpected residual occurrences"
fi
log "residual check: clean"

# --------------------------------------------------------------------------- #
# 3. Idempotency guardrail
# --------------------------------------------------------------------------- #
git add -A
TREE1="$(git write-tree)"
python3 scripts/rebrand.py > /tmp/rebrand_report2.txt 2>&1 || fail "2nd rebrand failed"
git add -A
TREE2="$(git write-tree)"
[ "$TREE1" = "$TREE2" ] || fail "rebrand is not idempotent ($TREE1 != $TREE2)"
log "idempotency check: identical tree ($TREE1)"

# --------------------------------------------------------------------------- #
# 4. Leak guardrail
# --------------------------------------------------------------------------- #
# After excluding the pipeline tooling (stripped before publish) and the
# allowlisted backward-compat files, no tracked TEXT file may contain
# `omnigent` or `substrate-ai`. Binary files are ignored by `git grep -I`.
# The tooling exclusions mirror scripts/publish_exclude.txt + rebrand SKIP set.
LEAK="$(git grep -I -in -e omnigent -e substrate-ai -- \
  ':!scripts/rebrand.py' \
  ':!scripts/sync_upstream.sh' \
  ':!scripts/publish_substrate.sh' \
  ':!scripts/publish_exclude.txt' \
  ':!.github/workflows/publish-substrate.yml' \
  ':!substrate/_env_compat.py' \
  ':!substrate/cli.py' || true)"
if [ -n "$LEAK" ]; then
  printf '%s\n' "$LEAK" >&2
  fail "leak check: forbidden token in published text files"
fi
log "leak check: clean (allowlist: _env_compat.py, cli.py, pipeline tooling, binary assets)"

# Sanity: the allowlisted compat files must contain ONLY legacy compat refs.
NONCOMPAT="$(git grep -I -in "omnigent" -- substrate/_env_compat.py substrate/cli.py \
  | grep -viE "OMNIGENT_|OMNIGENTS_|OMNIAGENTS_|\.omnigent|\.omnigents|legacy" || true)"
if [ -n "$NONCOMPAT" ]; then
  printf '%s\n' "$NONCOMPAT" >&2
  fail "allowlisted file has a non-compat omnigent reference"
fi

# --------------------------------------------------------------------------- #
# 5. Stage publishable tree
# --------------------------------------------------------------------------- #
VERSION="$(grep -E '^version *= *"' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
[ -n "$VERSION" ] || fail "could not read version from pyproject.toml"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
log "staging rebranded tree -> $STAGE (version $VERSION)"

# Export every tracked file (post-rebrand, from the index) into the stage.
# `git add -A` above put all rebrand changes in the index; archiving the index
# tree preserves renames, symlinks (verbatim, even if dangling) and modes, and
# includes ONLY tracked content -- safer than rsync'ing the working dir.
git add -A
STAGE_TREE="$(git write-tree)"
git archive --format=tar "$STAGE_TREE" | tar -x -C "$STAGE"

# Apply exclusions.
if [ -f "$EXCLUDE_FILE" ]; then
  while IFS= read -r line; do
    case "$line" in
      ''|\#*) continue ;;
    esac
    case "$line" in
      */) rm -rf "${STAGE:?}/${line%/}" ;;
      *)  rm -f  "${STAGE:?}/${line}" ;;
    esac
  done < "$EXCLUDE_FILE"
fi

# Post-exclusion leak re-check directly on the staged tree (defence in depth).
if grep -rIl -e omnigent -e substrate-ai "$STAGE" \
   | grep -vE "_env_compat.py$|/cli.py$" | grep -q .; then
  grep -rIl -e omnigent -e substrate-ai "$STAGE" \
    | grep -vE "_env_compat.py$|/cli.py$" >&2
  fail "staged tree leak: forbidden token after exclusion"
fi
log "staged tree leak re-check: clean"

# --------------------------------------------------------------------------- #
# 6. Publish (incremental commit)
# --------------------------------------------------------------------------- #
if [ -n "${DOWNSTREAM_URL:-}" ]; then
  PUSH_URL="$DOWNSTREAM_URL"
elif [ -n "${SUBSTRATE_DEPLOY_TOKEN:-}" ]; then
  PUSH_URL="https://x-access-token:${SUBSTRATE_DEPLOY_TOKEN}@github.com/${DOWNSTREAM_REPO}.git"
else
  # No credentials. A dry run can still succeed (the staged tree is built and
  # validated above); only a real push strictly needs the token.
  if [ "${DRY_RUN:-0}" = "1" ]; then
    log "DRY_RUN=1 and no DOWNSTREAM_URL/SUBSTRATE_DEPLOY_TOKEN -> staged tree validated; skipping downstream clone/diff/push."
    log "staged tree is in: $STAGE"
    exit 0
  fi
  fail "no DOWNSTREAM_URL or SUBSTRATE_DEPLOY_TOKEN set for push"
fi

WORK="$(mktemp -d)"; trap 'rm -rf "$STAGE" "$WORK"' EXIT
log "cloning downstream ${DOWNSTREAM_REPO}..."
if ! git clone --depth 1 --branch "$DOWNSTREAM_REF" "$PUSH_URL" "$WORK" 2>/dev/null; then
  # Empty repo (no branch yet): init fresh.
  git clone --depth 1 "$PUSH_URL" "$WORK" 2>/dev/null || { git init -q "$WORK"; git -C "$WORK" remote add origin "$PUSH_URL"; }
  git -C "$WORK" checkout -q -b "$DOWNSTREAM_REF" 2>/dev/null || true
fi

# Replace downstream working tree with the staged tree (preserve its .git).
rsync -a --delete --exclude '.git/' "$STAGE"/ "$WORK"/

cd "$WORK"
git add -A
if git diff --cached --quiet; then
  log "no downstream changes; skipping commit."
  exit 0
fi

git -c user.name="$BOT_NAME" -c user.email="$BOT_EMAIL" \
  commit -q -m "release: v${VERSION}"
log "committed release: v${VERSION}"

if [ "${DRY_RUN:-0}" = "1" ]; then
  log "DRY_RUN=1 -> skipping push. Commit is in $WORK"
  git log --oneline -1
  exit 0
fi

git push origin "HEAD:${DOWNSTREAM_REF}"
log "pushed to ${DOWNSTREAM_REPO}@${DOWNSTREAM_REF}"
