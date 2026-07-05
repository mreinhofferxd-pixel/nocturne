#!/usr/bin/env bash
# nocturne installer: copies the skill into ~/.claude/skills so /nocturne
# works in every repo. Safe to re-run; overwrites a previous install.
set -euo pipefail

REPO_TARBALL="https://github.com/mreinhofferxd-pixel/nocturne/archive/refs/heads/master.tar.gz"
DEST="${CLAUDE_HOME:-$HOME/.claude}/skills/nocturne"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

command -v curl >/dev/null || { echo "error: curl is required" >&2; exit 1; }
command -v tar  >/dev/null || { echo "error: tar is required" >&2; exit 1; }

echo "Downloading nocturne..."
curl -fsSL "$REPO_TARBALL" | tar -xz -C "$TMP"

SRC="$TMP/nocturne-master/.claude/skills/nocturne"
[ -d "$SRC" ] || { echo "error: skill folder missing in download" >&2; exit 1; }

mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"
cp -R "$SRC" "$DEST"

echo "Installed: $DEST"
command -v claude >/dev/null || echo "note: Claude Code CLI not found on PATH"
command -v python >/dev/null || command -v python3 >/dev/null || echo "note: python 3.10+ not found on PATH (the harness needs it)"
echo "Next: open Claude Code in the repo you want looped and run /nocturne"
