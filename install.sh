#!/usr/bin/env bash
# Install agent-skills into one or more agent harnesses by symlinking each
# skill directory. Idempotent; safe to re-run after every `git pull`.
#
# Usage:
#   bash install.sh                         # every harness detected on this machine
#   bash install.sh --harness claude,codex  # specific harnesses (claude|codex|agents|all)
#   bash install.sh --target DIR            # any other harness: link skills into DIR (repeatable)
#   bash install.sh --overlay DIR           # private overlay checkout (default: auto-detect)
#   bash install.sh --replace               # back up real dirs that occupy a skill's slot, then link
#   bash install.sh --adopt                 # move unmanaged skill dirs into the overlay (asks first)
#   bash install.sh --bootstrap-secrets     # create/fill ~/.config/agent-secrets/.env
#   bash install.sh --no-deps               # skip `npm ci` for skills that ship a package-lock.json
#   bash install.sh --uninstall             # remove only the links this repo created
#   bash install.sh --dry-run               # print what would happen, change nothing
#   bash install.sh --yes                   # do not prompt (for --adopt)
#
# Skills come from ./skills/*, plus <overlay>/skills/* when a private overlay
# is found. The overlay is also linked at ~/.config/agent-skills/overlay,
# which is where skills look for their organisation profiles.
set -euo pipefail

REPO_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/harnesses.sh
. "$REPO_DIR/lib/harnesses.sh"

HARNESSES="auto"; TARGETS=(); OVERLAY_ARG=""
REPLACE=false; ADOPT=false; BOOTSTRAP=false; DEPS=true; UNINSTALL=false; DRY=false; YES=false
while [ $# -gt 0 ]; do
  case "$1" in
    --harness) HARNESSES="${2:?--harness needs a value}"; shift ;;
    --harness=*) HARNESSES="${1#*=}" ;;
    --target) TARGETS+=("${2:?--target needs a directory}"); shift ;;
    --target=*) TARGETS+=("${1#*=}") ;;
    --overlay) OVERLAY_ARG="${2:?--overlay needs a directory}"; shift ;;
    --overlay=*) OVERLAY_ARG="${1#*=}" ;;
    --replace) REPLACE=true ;;
    --adopt) ADOPT=true ;;
    --bootstrap-secrets) BOOTSTRAP=true ;;
    --no-deps) DEPS=false ;;
    --uninstall) UNINSTALL=true ;;
    --dry-run) DRY=true ;;
    --yes|-y) YES=true ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done

run() { if $DRY; then echo "  [dry-run] $*"; else "$@"; fi; }
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_ROOT="${XDG_STATE_HOME:-$HOME/.local/state}/agent-skills/backup/$STAMP"

# --- Resolve harness skill directories --------------------------------------
DESTS=()      # "label|skills_dir|prompts_dir"
if [ "$HARNESSES" = "auto" ]; then
  for h in $KNOWN_HARNESSES; do
    if harness_present "$h"; then DESTS+=("$h|$(harness_skills_dir "$h")|$(harness_prompts_dir "$h" || true)"); fi
  done
  [ ${#DESTS[@]} -gt 0 ] || [ ${#TARGETS[@]} -gt 0 ] || {
    echo "no harness detected; pass --harness claude|codex|agents|all or --target DIR" >&2; exit 2; }
else
  [ "$HARNESSES" = "all" ] && HARNESSES="${KNOWN_HARNESSES// /,}"
  IFS=',' read -r -a wanted <<<"$HARNESSES"
  for h in "${wanted[@]}"; do
    dir="$(harness_skills_dir "$h")" || { echo "unknown harness: $h (known: $KNOWN_HARNESSES)" >&2; exit 2; }
    DESTS+=("$h|$dir|$(harness_prompts_dir "$h" || true)")
  done
fi
for t in "${TARGETS[@]+"${TARGETS[@]}"}"; do DESTS+=("target|$t|"); done
[ ${#DESTS[@]} -gt 0 ] || { echo "nothing to install into" >&2; exit 2; }

OVERLAY="$(find_overlay "$REPO_DIR" "$OVERLAY_ARG")"
if [ -n "$OVERLAY_ARG" ] && [ -z "$OVERLAY" ]; then
  echo "overlay not found or not an overlay checkout: $OVERLAY_ARG" >&2; exit 2
fi

# --- Collect skill sources (public first; overlay adds private-only skills) --
SOURCES=()
add_sources() {
  local root="$1" src name existing dup
  [ -d "$root" ] || return 0
  for src in "$root"/*/; do
    [ -f "$src/SKILL.md" ] || continue
    name="$(basename "$src")"; dup=false
    for existing in "${SOURCES[@]+"${SOURCES[@]}"}"; do
      [ "$(basename "$existing")" = "$name" ] && dup=true
    done
    if $dup; then echo "skip:   $name in $root duplicates a public skill; the public one wins" >&2; continue; fi
    SOURCES+=("${src%/}")
  done
}
add_sources "$REPO_DIR/skills"
[ -n "$OVERLAY" ] && add_sources "$OVERLAY/skills"

owned_by_us() {   # is this symlink one we created (points into repo or overlay)?
  local link="$1" dest
  [ -L "$link" ] || return 1
  dest="$(physical_path "$link" 2>/dev/null || true)"
  case "$dest" in "$REPO_DIR"/*) return 0 ;; esac
  if [ -n "$OVERLAY" ]; then case "$dest" in "$OVERLAY"/*) return 0 ;; esac; fi
  # A dangling link that used to point into this repo (e.g. after a rename).
  case "$(readlink "$link")" in "$REPO_DIR"/*) return 0 ;; esac
  return 1
}

# --- Uninstall ---------------------------------------------------------------
if $UNINSTALL; then
  for d in "${DESTS[@]}"; do
    IFS='|' read -r label skills_dir prompts_dir <<<"$d"
    for link in "$skills_dir"/* ${prompts_dir:+"$prompts_dir"/*}; do
      [ -e "$link" ] || [ -L "$link" ] || continue
      if owned_by_us "$link"; then run rm "$link"; echo "removed: $link"; fi
    done
  done
  link="$HOME/.config/agent-skills/overlay"
  if [ -L "$link" ]; then run rm "$link"; echo "removed: $link"; fi
  exit 0
fi

# --- Adopt: pull unmanaged skills into the private overlay -------------------
if $ADOPT; then
  [ -n "$OVERLAY" ] || { echo "--adopt needs a private overlay (it never moves skills into the public repo)" >&2; exit 2; }
  candidates=()
  for d in "${DESTS[@]}"; do
    IFS='|' read -r label skills_dir _ <<<"$d"
    for dir in "$skills_dir"/*/; do
      dir="${dir%/}"; name="$(basename "$dir")"
      if [ ! -f "$dir/SKILL.md" ] || [ -L "$dir" ]; then continue; fi
      case "$name" in .*|synced) continue ;; esac          # harness-managed dirs
      if [ -e "$REPO_DIR/skills/$name" ] || [ -e "$OVERLAY/skills/$name" ]; then continue; fi
      candidates+=("$dir")
    done
  done
  if [ ${#candidates[@]} -gt 0 ]; then
    echo "adopt: these unmanaged skills would move into the PRIVATE overlay ($OVERLAY/skills):"
    printf '  %s\n' "${candidates[@]}"
    if ! $YES && ! $DRY; then
      read -r -p "move them? [y/N] " answer
      [[ "$answer" =~ ^[Yy] ]] || { echo "adopt: skipped"; candidates=(); }
    fi
    for dir in "${candidates[@]+"${candidates[@]}"}"; do
      run mv "$dir" "$OVERLAY/skills/$(basename "$dir")"
      $DRY || SOURCES+=("$OVERLAY/skills/$(basename "$dir")")
    done
  else
    echo "adopt: nothing unmanaged to adopt"
  fi
fi

# --- Link the overlay where skills look for it -------------------------------
if [ -n "$OVERLAY" ]; then
  link="$HOME/.config/agent-skills/overlay"
  run mkdir -p "$(dirname "$link")"
  if [ -L "$link" ] || [ ! -e "$link" ]; then
    run ln -sfn "$OVERLAY" "$link"
    echo "overlay: $link -> $OVERLAY"
  else
    echo "overlay: WARN $link exists and is not a symlink; leaving it" >&2
  fi
else
  echo "overlay: none found (public skills only; see README → Private overlay)"
fi

# --- Link skills (and Codex prompts) into every destination ------------------
link_into() {   # link_into <src> <dest> <label>
  local src="$1" dest="$2" label="$3"
  if [ -L "$dest" ]; then
    if [ "$(physical_path "$dest" 2>/dev/null || true)" = "$(physical_path "$src")" ]; then
      echo "  ok      $label"; return
    fi
    run ln -sfn "$src" "$dest"; echo "  relink  $label"
  elif [ -e "$dest" ]; then
    if $REPLACE; then
      run mkdir -p "$BACKUP_ROOT/$(dirname "${dest#/}")"
      run mv "$dest" "$BACKUP_ROOT/${dest#/}"
      run ln -s "$src" "$dest"; echo "  replace $label (old copy backed up under $BACKUP_ROOT)"
    else
      echo "  WARN    $label: a real file/dir occupies $dest; re-run with --replace (backs it up)" >&2
    fi
  else
    run ln -s "$src" "$dest"; echo "  link    $label"
  fi
}

for d in "${DESTS[@]}"; do
  IFS='|' read -r label skills_dir prompts_dir <<<"$d"
  echo "[$label] $skills_dir"
  run mkdir -p "$skills_dir"
  for src in "${SOURCES[@]}"; do link_into "$src" "$skills_dir/$(basename "$src")" "$(basename "$src")"; done
  # Remove our own links whose source no longer exists (renamed/deleted skills).
  for link in "$skills_dir"/*; do
    if [ -L "$link" ] && [ ! -e "$link" ] && owned_by_us "$link"; then
      run rm "$link"; echo "  prune   $(basename "$link") (source gone)"
    fi
  done
  if [ -n "$prompts_dir" ] && [ -d "$REPO_DIR/prompts/$label" ]; then
    run mkdir -p "$prompts_dir"
    for src in "$REPO_DIR/prompts/$label"/*.md; do
      if [ -f "$src" ]; then link_into "$src" "$prompts_dir/$(basename "$src")" "prompt $(basename "$src")"; fi
    done
  fi
done

# --- Script dependencies -----------------------------------------------------
if $DEPS; then
  for src in "${SOURCES[@]}"; do
    for lock in "$src"/scripts/package-lock.json; do
      [ -f "$lock" ] || continue
      if command -v npm >/dev/null 2>&1; then
        echo "deps:   npm ci in $(basename "$src")/scripts"
        $DRY || (cd "$(dirname "$lock")" && npm ci --no-audit --no-fund --loglevel=error) \
          || echo "deps:   WARN npm ci failed for $(basename "$src"); its scripts may not run" >&2
      else
        echo "deps:   WARN npm not found; $(basename "$src") scripts need 'npm ci' in scripts/" >&2
      fi
    done
  done
fi

# --- Public-safety pre-commit hook for this repo -----------------------------
if [ -d "$REPO_DIR/.git" ] || [ -f "$REPO_DIR/.git" ]; then
  current="$(git -C "$REPO_DIR" config --get core.hooksPath || true)"
  if [ "$current" != ".githooks" ]; then
    run git -C "$REPO_DIR" config core.hooksPath .githooks
    echo "hooks:  pre-commit public-safety check enabled (.githooks)"
  fi
fi

# --- Secrets bootstrap -------------------------------------------------------
if $BOOTSTRAP; then
  run python3 "$REPO_DIR/lib/env_resolve.py" bootstrap
fi

echo "done. run 'bash doctor.sh' to verify."
