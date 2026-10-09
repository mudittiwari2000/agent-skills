#!/usr/bin/env bash
# Health check for the agent-skills setup. Never prints secret values.
#
#   bash doctor.sh                  # harnesses detected on this machine
#   bash doctor.sh --harness all    # or a comma list: claude,codex,agents
#   bash doctor.sh --offline        # skip the API reachability checks
set -uo pipefail

REPO_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/harnesses.sh
. "$REPO_DIR/lib/harnesses.sh"

HARNESSES="auto"; OFFLINE=false
while [ $# -gt 0 ]; do
  case "$1" in
    --harness) HARNESSES="${2:?}"; shift ;;
    --harness=*) HARNESSES="${1#*=}" ;;
    --offline) OFFLINE=true ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done
FAIL=0

if [ "$HARNESSES" = "auto" ]; then
  list=""; for h in $KNOWN_HARNESSES; do if harness_present "$h"; then list="$list $h"; fi; done
elif [ "$HARNESSES" = "all" ]; then list="$KNOWN_HARNESSES"
else list="${HARNESSES//,/ }"; fi

OVERLAY="$(find_overlay "$REPO_DIR")"
echo "== overlay =="
if [ -n "$OVERLAY" ]; then
  echo "  found: $OVERLAY"
  link="$HOME/.config/agent-skills/overlay"
  if [ -L "$link" ] && [ "$(physical_path "$link")" = "$OVERLAY" ]; then
    echo "  link:  $link OK"
  else
    echo "  link:  $link missing or stale — run 'bash install.sh'"; FAIL=1
  fi
else
  echo "  none (public skills only)"
fi

sources=()
for root in "$REPO_DIR/skills" ${OVERLAY:+"$OVERLAY/skills"}; do
  for src in "$root"/*/; do [ -f "$src/SKILL.md" ] && sources+=("${src%/}"); done
done

echo "== skill frontmatter =="
for src in "${sources[@]}"; do
  name="$(basename "$src")"
  declared="$(sed -n '2,/^---$/s/^name:[[:space:]]*//p' "$src/SKILL.md" | head -1)"
  if [ "$(head -1 "$src/SKILL.md")" != "---" ] || [ -z "$declared" ]; then
    echo "  $name: MISSING frontmatter name"; FAIL=1
  elif [ "$declared" != "$name" ]; then
    echo "  $name: frontmatter name '$declared' differs from directory"; FAIL=1
  elif ! grep -q '^description:' "$src/SKILL.md"; then
    echo "  $name: MISSING description"; FAIL=1
  fi
done
echo "  checked ${#sources[@]} skills"

for h in $list; do
  dir="$(harness_skills_dir "$h")" || { echo "unknown harness: $h"; FAIL=1; continue; }
  echo "== $h: $dir =="
  for src in "${sources[@]}"; do
    name="$(basename "$src")"
    if [ -L "$dir/$name" ] && [ "$(physical_path "$dir/$name")" = "$(physical_path "$src")" ]; then
      echo "  $name: OK"
    else
      echo "  $name: missing or not linked to this repo — run 'bash install.sh --harness $h'"; FAIL=1
    fi
  done
  if pdir="$(harness_prompts_dir "$h")" && [ -d "$REPO_DIR/prompts/$h" ]; then
    for src in "$REPO_DIR/prompts/$h"/*.md; do
      [ -f "$src" ] || continue
      name="$(basename "$src")"
      if [ -L "$pdir/$name" ] && [ "$(physical_path "$pdir/$name")" = "$(physical_path "$src")" ]; then
        echo "  prompt $name: OK"
      else
        echo "  prompt $name: missing — run 'bash install.sh --harness $h'"; FAIL=1
      fi
    done
  fi
done

echo "== script dependencies =="
for src in "${sources[@]}"; do
  if [ -f "$src/scripts/package-lock.json" ]; then
    if [ -d "$src/scripts/node_modules" ]; then echo "  $(basename "$src"): node_modules OK"
    else echo "  $(basename "$src"): node_modules missing — run 'bash install.sh'"; FAIL=1; fi
  fi
done

echo "== public-safety hook =="
if [ "$(git -C "$REPO_DIR" config --get core.hooksPath 2>/dev/null)" = ".githooks" ]; then
  echo "  pre-commit check enabled"
else
  echo "  NOT enabled — run 'bash install.sh'"; FAIL=1
fi

echo "== secrets + manifests$($OFFLINE || echo ' + reachability') =="
if $OFFLINE; then
  python3 - "$REPO_DIR" <<'PY' || FAIL=1
import sys
sys.path.insert(0, sys.argv[1] + "/lib")
import env_resolve
values, _ = env_resolve.resolve_all()
bad = 0
for path in env_resolve.skill_manifests():
    m = env_resolve.parse_manifest(path)
    for group in m["required"]:
        ok = any(values.get(k) for k in group)
        print(f"  [{m['name']}] {' | '.join(group)}: {'PRESENT' if ok else 'MISSING'}")
        bad += not ok
sys.exit(1 if bad else 0)
PY
else
  python3 "$REPO_DIR/lib/env_resolve.py" doctor || FAIL=1
fi

store="$HOME/.config/agent-secrets/.env"
if [ -f "$store" ]; then
  perms="$(stat -c '%a' "$store" 2>/dev/null || stat -f '%Lp' "$store")"
  if [ "$perms" = "600" ]; then echo "== permissions: dedicated store is 600 =="
  else echo "== permissions: WARN dedicated store is $perms (expected 600) =="; FAIL=1; fi
fi

if [ "$FAIL" -eq 0 ]; then echo "ALL CHECKS PASSED"; else echo "PROBLEMS FOUND"; fi
exit "$FAIL"
