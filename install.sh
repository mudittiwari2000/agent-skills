#!/usr/bin/env bash
# Deploy agent-skills into ~/.codex via symlinks. Idempotent.
#
# Usage:
#   bash install.sh                      # symlink skills + prompts
#   bash install.sh --adopt              # first move unmanaged real dirs in
#                                        # ~/.codex/skills into this repo, then symlink
#   bash install.sh --bootstrap-secrets  # also create/fill ~/.config/agent-secrets/.env
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEX_SKILLS="$HOME/.codex/skills"
CODEX_PROMPTS="$HOME/.codex/prompts"

ADOPT=false
BOOTSTRAP=false
for arg in "$@"; do
  case "$arg" in
    --adopt) ADOPT=true ;;
    --bootstrap-secrets) BOOTSTRAP=true ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$CODEX_SKILLS" "$CODEX_PROMPTS"

# --- 1. Adopt unmanaged skills (real dirs, not .system) into the repo -------
if $ADOPT; then
  for dir in "$CODEX_SKILLS"/*/; do
    [ -d "$dir" ] || continue
    name="$(basename "$dir")"
    [ "$name" = ".system" ] && continue
    [ -L "${dir%/}" ] && continue                     # already a symlink
    if [ -e "$REPO_DIR/codex/skills/$name" ]; then
      echo "adopt: SKIP $name — repo already has codex/skills/$name (resolve manually)"
      continue
    fi
    echo "adopt: moving $name into repo"
    mv "${dir%/}" "$REPO_DIR/codex/skills/$name"
    prompt="$CODEX_PROMPTS/$name.md"
    if [ -f "$prompt" ] && [ ! -L "$prompt" ] && [ ! -e "$REPO_DIR/codex/prompts/$name.md" ]; then
      echo "adopt: moving prompt $name.md into repo"
      mv "$prompt" "$REPO_DIR/codex/prompts/$name.md"
    fi
  done
fi

# --- 2. Symlink skills -------------------------------------------------------
for src in "$REPO_DIR"/codex/skills/*/; do
  [ -d "$src" ] || continue
  name="$(basename "$src")"
  target="$CODEX_SKILLS/$name"
  if [ -L "$target" ]; then
    ln -sfn "${src%/}" "$target"
    echo "skill:  $name -> repo (symlink refreshed)"
  elif [ -e "$target" ]; then
    echo "skill:  WARN $name — real dir occupies $target; run with --adopt or remove it" >&2
  else
    ln -s "${src%/}" "$target"
    echo "skill:  $name -> repo (symlinked)"
  fi
done

# --- 3. Symlink prompts ------------------------------------------------------
for src in "$REPO_DIR"/codex/prompts/*.md; do
  [ -f "$src" ] || continue
  name="$(basename "$src")"
  target="$CODEX_PROMPTS/$name"
  if [ -L "$target" ] || [ ! -e "$target" ]; then
    ln -sfn "$src" "$target"
    echo "prompt: $name -> repo (symlinked)"
  else
    echo "prompt: WARN $name — real file occupies $target; run with --adopt or remove it" >&2
  fi
done

# --- 4. Secrets bootstrap ----------------------------------------------------
if $BOOTSTRAP; then
  python3 "$REPO_DIR/lib/env_resolve.py" bootstrap
fi

echo "done. run 'bash doctor.sh' to verify."
