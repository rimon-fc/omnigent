#!/usr/bin/env python3
"""Rebrand the upstream ``omnigent`` codebase to ``substrate``.

Single source of truth for the omnigent -> substrate rebrand. Designed to be
re-run after every upstream sync (``git fetch upstream && git merge
upstream/main``, or a fresh re-clone): ALL rebrand logic lives here -- never
hand-edit rebranded files outside this script.

Properties:
  * Idempotent  -- running twice produces no net change (``git diff`` empty).
  * Offline     -- makes no network calls.
  * Git-aware   -- path renames go through ``git mv`` so history is preserved.
  * Safe        -- only touches ``git ls-files`` (so ``.git/`` is never read),
                   skips itself, and never edits binary/art assets.

Casing map (applied to file CONTENTS and PATH components):
    OMNIGENT -> SUBSTRATE
    Omnigent -> Substrate
    omnigent -> substrate

Everything is rebranded, including upstream GitHub coordinates: plain text
replacement turns ``omnigent-ai/omnigent`` -> ``rimon-fc/substrate`` and
``omnigent-ai`` -> ``rimon-fc``. Nothing in the tree is left reading
"omnigent". (The git ``upstream`` remote lives in ``.git/config`` -- untracked,
never touched by this script -- so ``git fetch upstream`` still works.)

Dedicated, non-mechanical handling (so backward-compat is not destroyed):
  * ``_env_compat.py`` env-var prefixes: ``SUBSTRATE_`` is current; ``OMNIGENT_``
    / ``OMNIGENTS_`` / ``OMNIAGENTS_`` are read as fallbacks (old value used when
    the new one is unset).
  * ``cli.py`` ``_LEGACY_STATE_DIRS``: ``~/.substrate`` is current; ``~/.omnigent``
    (+ older) are migrated on first run.

Reported at the end: (a) files changed, (b) paths renamed, (c) deliberately-
unchanged occurrences with file:line + reason (compat fallbacks, art assets),
plus a residual safety net that flags any unexpected leftover "omnigent".

Art note: logo/wordmark image assets are renamed but their pixel/vector art
still depicts "Omnigent" and needs a manual redesign.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

CASE_MAP: list[tuple[str, str]] = [
    ("OMNIGENT", "SUBSTRATE"),
    ("Omnigent", "Substrate"),
    ("omnigent", "substrate"),
]

# GitHub coordinate rewrite. Applied BEFORE CASE_MAP so the org/repo slug is
# rewritten as a unit; otherwise the bare ``omnigent -> substrate`` rule would
# turn ``omnigent-ai/omnigent`` into ``substrate-ai/substrate`` (leaking a
# nonexistent org). Ordered longest-first so the full slug matches before the
# bare org. Downstream output points at ``rimon-fc/substrate``.
COORD_MAP: list[tuple[str, str]] = [
    ("omnigent-ai/omnigent", "rimon-fc/substrate"),
    ("omnigent-ai", "rimon-fc"),
]

# After rebranding, vowel-initial "Omnigent" was often preceded by the article
# "an"; "Substrate" is consonant-initial, so fix "an Substrate" -> "a Substrate"
# (both case combos). Idempotent: "a Substrate" contains no "an Substrate".
ARTICLE_FIX_RE = re.compile(r"\b([Aa])n(\s+[Ss]ubstrate)")

# The upstream shipped a short ``omni`` alias alongside the full CLI name. After
# rebranding the full name is ``substrate``; the ``omni`` alias is dropped
# entirely (it duplicates ``substrate`` and collides with prior installs). The
# console-script entry is removed by fix_project_scripts(); here we rewrite
# ``omni <subcommand>`` command references and ``bin/omni`` paths to substrate.
# The subcommand lookahead means model IDs (``qwen3-omni-...``), hostnames
# (``omni.example.com``), temp dirs (``/tmp/omni-...``) and bare data strings
# are NOT matched -- none of them are ``omni <subcommand>``.
_OMNI_SUBCMDS = (
    "upgrade host run server setup sandbox stop status resume attach "
    "claude codex pi config debug version login polly debby"
).split()
OMNI_CMD_RE = re.compile(r"\bomni\b(?=\s+(?:" + "|".join(_OMNI_SUBCMDS) + r")\b)")
OMNI_BIN_RE = re.compile(r"\bbin/omni\b")
# A now-false sentence ("`omni` is an alias for `substrate`, so ...").
OMNI_ALIAS_SENTENCE_RE = re.compile(r"`omni` is an alias for `substrate`,?\s*(?:so\s*)?")

# pyproject [project.scripts]: drop the ``omni`` alias line, keep ``substrate``.
SCRIPTS_RE = re.compile(r'\[project\.scripts\].*?\nomni = "substrate\.cli:main"\n', re.S)
SCRIPTS_CANON = (
    "[project.scripts]\n"
    "# Console entry point for the Substrate CLI.\n"
    'substrate = "substrate.cli:main"\n'
)

# Files whose CONTENTS need dedicated logic (a blind replace would destroy
# backward-compat). Matched by basename; excluded from the generic text pass.
SPECIAL_CONTENT_BASENAMES = {"_env_compat.py"}

# This script: never process or rename it (it holds the mapping literals, and
# its own strings would otherwise be matched by the special-case fixups).
SELF_RELPATH = "scripts/rebrand.py"

# The fork->downstream pipeline tooling. Like ``rebrand.py`` itself, these files
# contain the literal token ``omnigent`` (in comments, upstream URLs, and leak-
# check patterns) on purpose; rebranding them would corrupt the tooling (e.g.
# turn a ``grep omnigent`` leak check into ``grep substrate``). They are also
# stripped before publishing (see scripts/publish_exclude.txt), so they never
# reach the downstream tree. Skipped from every rebrand pass.
SKIP_RELPATHS = {
    SELF_RELPATH,
    "scripts/sync_upstream.sh",
    "scripts/publish_substrate.sh",
    "scripts/publish_exclude.txt",
    ".github/workflows/publish-substrate.yml",
}

# Directory prefixes skipped entirely. ``substrate-overlay/`` holds the curated
# README, art, and example set in their FINAL form; they must not be rebranded
# (they are already correct) and are layered onto the published tree by
# publish_substrate.sh, never shipped from here.
SKIP_PREFIXES = (
    "substrate-overlay/",
)


def _skip(relpath: str) -> bool:
    """True if a tracked path is rebrand-exempt tooling/overlay."""
    return relpath in SKIP_RELPATHS or relpath.startswith(SKIP_PREFIXES)

RASTER_IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".icns", ".bmp",
    ".tif", ".tiff",
}
# Binary / art: path-renamed only, contents never edited. .svg is XML text but
# is brand artwork, so it is skipped from the text pass and flagged instead.
BINARY_OR_ART_EXTS = RASTER_IMAGE_EXTS | {
    ".svg", ".pdf", ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp4", ".mov", ".webm", ".mp3", ".wav",
    ".zip", ".gz", ".tgz", ".bz2", ".xz",
    ".car", ".provisionprofile", ".keystore", ".p12", ".cer", ".der",
}
ART_REPORT_EXTS = RASTER_IMAGE_EXTS | {".svg", ".icns", ".ico", ".car", ".tiff", ".tif"}

# Canonical content for the env-var backward-compat shim after rebrand.
ENV_COMPAT_CONTENT = '''\
"""Backward-compatibility shim for the env-var prefix renames -> ``SUBSTRATE_*``.

The project's env-var prefix has evolved as the name changed:
``OMNIAGENTS_`` -> ``OMNIGENTS_`` -> ``OMNIGENT_`` -> ``SUBSTRATE_`` (current).
All current code reads the new ``SUBSTRATE_`` names. To keep existing
deployments, CI configs, and shell profiles that still export an older prefix
working, this shim mirrors every legacy variable onto its ``SUBSTRATE_``
equivalent at process startup -- but only when the new name is unset, so an
explicitly-set ``SUBSTRATE_`` value always wins.

The mirror is installed once, as early as possible, from
``substrate/__init__.py`` so it runs before any submodule reads the
environment. Out-of-package entry points that read env *before* importing the
``substrate`` package (the Docker / Databricks deploy entrypoints) call
:func:`mirror_legacy_env` directly.
"""

from __future__ import annotations

import os

# The current prefix, and every legacy prefix that maps onto it. Ordered
# newest-first so that when more than one legacy prefix is set for the same
# variable, the newer one wins (``setdefault`` keeps the first mirrored value).
# ``OMNIGENT_`` is a legacy prefix here: a deployment that still exports
# ``OMNIGENT_FOO`` transparently populates ``SUBSTRATE_FOO`` when the latter is
# unset.
_NEW_PREFIX = "SUBSTRATE_"
_LEGACY_PREFIXES = ("OMNIGENT_", "OMNIGENTS_", "OMNIAGENTS_")

# Module-level guard so repeated imports/calls don't rescan the environment.
_mirrored = False


def mirror_legacy_env() -> None:
    """
    Mirror legacy ``OMNIGENT_*`` / ``OMNIGENTS_*`` / ``OMNIAGENTS_*`` env vars
    onto ``SUBSTRATE_*``.

    For every environment variable whose name starts with one of the legacy
    prefixes in :data:`_LEGACY_PREFIXES`, set the corresponding ``SUBSTRATE_``
    variable if (and only if) it is not already present -- so an explicitly-set
    new-name variable always takes precedence over a legacy one, and a newer
    legacy prefix takes precedence over an older one. Idempotent and cheap:
    calls after the first are no-ops.

    Example: with ``OMNIGENT_SKIP_WEB_UI=1`` in the environment and no
    ``SUBSTRATE_SKIP_WEB_UI`` set, this leaves ``SUBSTRATE_SKIP_WEB_UI=1``.

    :returns: ``None``. Mutates :data:`os.environ` in place.
    """
    global _mirrored
    if _mirrored:
        return
    for legacy_prefix in _LEGACY_PREFIXES:
        for name, value in list(os.environ.items()):
            if name.startswith(legacy_prefix):
                new_name = _NEW_PREFIX + name[len(legacy_prefix):]
                os.environ.setdefault(new_name, value)
    _mirrored = True
'''

# Canonical ``_LEGACY_STATE_DIRS`` block for cli.py. ``~/.omnigent`` is added as
# the newest legacy dir so an existing install migrates to ``~/.substrate``.
LEGACY_DIRS_RE = re.compile(
    r"_LEGACY_STATE_DIRS:\s*tuple\[Path, \.\.\.\]\s*=\s*\(.*?\n\)",
    re.S,
)
LEGACY_DIRS_CANON = (
    "_LEGACY_STATE_DIRS: tuple[Path, ...] = (\n"
    "    # Pre-rebrand / pre-rename dirs, newest first; migrate the newest that\n"
    "    # still exists. The immediate pre-rebrand dir is the next entry.\n"
    '    Path.home() / ".omnigent",\n'
    '    Path.home() / ".omnigents",\n'
    '    Path.home() / ".omniagents",\n'
    ")"
)


# --------------------------------------------------------------------------- #
# Git helpers
# --------------------------------------------------------------------------- #

def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def repo_root() -> Path:
    cp = _run(["git", "rev-parse", "--show-toplevel"], Path.cwd())
    if cp.returncode != 0:
        sys.exit("error: not inside a git repository")
    return Path(cp.stdout.strip())


def tracked_files(repo: Path) -> list[str]:
    cp = _run(["git", "ls-files"], repo)
    return [line for line in cp.stdout.splitlines() if line]


def git_mv(repo: Path, old: str, new: str) -> None:
    (repo / new).parent.mkdir(parents=True, exist_ok=True)
    cp = _run(["git", "mv", old, new], repo)
    if cp.returncode != 0:
        sys.exit(f"error: git mv {old} -> {new} failed:\n{cp.stderr}")


# --------------------------------------------------------------------------- #
# Text transform
# --------------------------------------------------------------------------- #

def rebrand_text(text: str) -> str:
    for src, dst in COORD_MAP:
        text = text.replace(src, dst)
    for src, dst in CASE_MAP:
        text = text.replace(src, dst)
    return ARTICLE_FIX_RE.sub(r"\1\2", text)


def scrub_omni_cli(text: str) -> str:
    text = OMNI_CMD_RE.sub("substrate", text)
    text = OMNI_BIN_RE.sub("bin/substrate", text)
    text = OMNI_ALIAS_SENTENCE_RE.sub("", text)
    return text


def fix_project_scripts(repo: Path, changed: list[str]) -> str | None:
    """Remove the ``omni`` console-script alias from pyproject (keep substrate)."""
    f = "pyproject.toml"
    p = repo / f
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    new = SCRIPTS_RE.sub(lambda _m: SCRIPTS_CANON, text)
    if new != text:
        p.write_text(new, encoding="utf-8")
        if f not in changed:
            changed.append(f)
        return f
    return None


def rebrand_component(comp: str) -> str:
    for src, dst in CASE_MAP:
        comp = comp.replace(src, dst)
    return comp


def has_token(s: str) -> bool:
    return "omnigent" in s.lower()


def iter_lines(text: str, pat: re.Pattern):
    for i, line in enumerate(text.splitlines(), start=1):
        if pat.search(line):
            yield i, line.strip()


# --------------------------------------------------------------------------- #
# Phases
# --------------------------------------------------------------------------- #

def rename_directories(repo: Path, renamed: list[tuple[str, str]]) -> None:
    """Rename token-bearing directories (shallowest-first), re-scanning each
    pass so nested renames compose correctly. Terminates when no directory
    component contains the token."""
    while True:
        target = None
        for f in tracked_files(repo):
            if _skip(f):
                continue
            parts = f.split("/")
            for i in range(len(parts) - 1):  # directory components only
                if has_token(parts[i]):
                    old = "/".join(parts[: i + 1])
                    new = "/".join(parts[:i] + [rebrand_component(parts[i])])
                    target = (old, new)
                    break
            if target:
                break
        if not target:
            return
        git_mv(repo, *target)
        renamed.append(target)


def rename_files(repo: Path, renamed: list[tuple[str, str]]) -> None:
    """Rename token-bearing file basenames (directories already handled)."""
    for f in tracked_files(repo):
        if _skip(f):
            continue
        head, _, base = f.rpartition("/")
        if has_token(base):
            new = (f"{head}/" if head else "") + rebrand_component(base)
            if new != f:
                git_mv(repo, f, new)
                renamed.append((f, new))


def rebrand_symlinks(repo: Path, changed: list[str]) -> None:
    """Rewrite symlink TARGETS that contain the brand token.

    A symlink's target is not file content (``rewrite_contents`` reads through
    the link, and would skip ``.svg`` links anyway), and renaming a link's
    target file leaves the link text stale -- producing a dangling link. This
    pass reads each tracked symlink's target with ``os.readlink`` and, if it
    carries the token, re-points the link via ``rebrand_text``. Idempotent.
    """
    for f in tracked_files(repo):
        if _skip(f):
            continue
        p = repo / f
        if not p.is_symlink():
            continue
        target = os.readlink(p)
        new_target = rebrand_text(target)
        if new_target != target:
            p.unlink()
            os.symlink(new_target, p)
            _run(["git", "add", f], repo)
            changed.append(f)


def rewrite_contents(repo: Path, changed: list[str]) -> None:
    for f in tracked_files(repo):
        if _skip(f):
            continue
        base = f.rsplit("/", 1)[-1]
        if base in SPECIAL_CONTENT_BASENAMES:
            continue
        if os.path.splitext(f)[1].lower() in BINARY_OR_ART_EXTS:
            continue
        p = repo / f
        try:
            text = p.read_bytes().decode("utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable
        new = scrub_omni_cli(rebrand_text(text))
        if new != text:
            p.write_text(new, encoding="utf-8")
            changed.append(f)


def fix_env_compat(repo: Path, changed: list[str]) -> str | None:
    for f in tracked_files(repo):
        if _skip(f):
            continue
        if f.rsplit("/", 1)[-1] == "_env_compat.py":
            p = repo / f
            if p.read_text(encoding="utf-8") != ENV_COMPAT_CONTENT:
                p.write_text(ENV_COMPAT_CONTENT, encoding="utf-8")
                if f not in changed:
                    changed.append(f)
            return f
    return None


def fix_cli_legacy_dirs(repo: Path, changed: list[str]) -> list[str]:
    fixed = []
    for f in tracked_files(repo):
        if _skip(f) or not f.endswith(".py"):
            continue
        p = repo / f
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "_LEGACY_STATE_DIRS" not in text or not LEGACY_DIRS_RE.search(text):
            continue
        new = LEGACY_DIRS_RE.sub(lambda _m: LEGACY_DIRS_CANON, text)
        if new != text:
            p.write_text(new, encoding="utf-8")
            if f not in changed:
                changed.append(f)
            fixed.append(f)
    return fixed


# --------------------------------------------------------------------------- #
# Reporting: deliberately-unchanged occurrences + residual safety net
# --------------------------------------------------------------------------- #

def build_unchanged_report(repo: Path, brand_assets: set[str]):
    compat, art, residual = [], [], []
    bare = re.compile(r"omnigent", re.IGNORECASE)
    for f in tracked_files(repo):
        if _skip(f):
            continue
        base = f.rsplit("/", 1)[-1]
        ext = os.path.splitext(f)[1].lower()
        if ext in ART_REPORT_EXTS:
            if f in brand_assets:
                art.append((f, "RENAMED brand asset — logo/wordmark art still depicts 'Omnigent'; manual redesign required"))
            else:
                art.append((f, "image asset — review; manual redesign only if it embeds the brand mark"))
            if ext == ".svg":
                try:
                    t = (repo / f).read_text(encoding="utf-8")
                    for ln, snip in iter_lines(t, bare):
                        art.append((f"{f}:{ln}", f"SVG markup contains brand text: {snip[:80]}"))
                except (UnicodeDecodeError, OSError):
                    pass
            continue
        if ext in BINARY_OR_ART_EXTS:
            continue
        try:
            text = (repo / f).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for ln, snip in iter_lines(text, bare):
            if base == "_env_compat.py":
                compat.append((f"{f}:{ln}", "intentional legacy env prefix (read old if new unset): " + snip[:80]))
            elif base == "cli.py" and ".omnigent" in snip:
                compat.append((f"{f}:{ln}", "intentional legacy state dir (migrated to ~/.substrate): " + snip[:80]))
            else:
                residual.append((f"{f}:{ln}", snip[:100]))
    return compat, art, residual


def section(title: str, rows):
    print(f"\n## {title} ({len(rows)})")
    for a, b in rows:
        print(f"  {a}\n      {b}")


def main() -> None:
    repo = repo_root()
    print(f"Rebranding repo: {repo}")

    renamed: list[tuple[str, str]] = []
    rename_directories(repo, renamed)
    rename_files(repo, renamed)

    changed: list[str] = []
    rebrand_symlinks(repo, changed)
    rewrite_contents(repo, changed)
    fix_env_compat(repo, changed)
    cli_fixed = fix_cli_legacy_dirs(repo, changed)
    fix_project_scripts(repo, changed)

    brand_assets = {
        new for _old, new in renamed
        if os.path.splitext(new)[1].lower() in ART_REPORT_EXTS
    }
    compat, art, residual = build_unchanged_report(repo, brand_assets)

    print("\n" + "=" * 70)
    print("REBRAND SUMMARY")
    print("=" * 70)

    print(f"\n## (a) Files changed (contents rewritten): {len(changed)}")
    for f in sorted(changed):
        print(f"  {f}")
    if cli_fixed:
        print(f"  [cli legacy-dir fixups applied to: {', '.join(cli_fixed)}]")

    print(f"\n## (b) Paths renamed: {len(renamed)}")
    for old, new in renamed:
        print(f"  {old}  ->  {new}")

    print("\n## (c) Deliberately left unchanged (with reasons)")
    section("Backward-compat fallbacks (env prefixes / state dirs)", compat)
    section("Art assets needing manual redesign", art)
    if residual:
        section("!!! UNEXPECTED RESIDUAL 'omnigent' (review)", residual)
    else:
        print("\n## No unexpected residual occurrences. (clean)")

    print("\nDone. Review with `git status` / `git diff`, then commit.")


if __name__ == "__main__":
    main()
