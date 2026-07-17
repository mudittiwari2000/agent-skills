#!/usr/bin/env bash
# Health check for the agent-skills setup. Never prints secret values.
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEX_SKILLS="$HOME/.codex/skills"
CODEX_PROMPTS="$HOME/.codex/prompts"
FAIL=0

echo "== codex cli =="
if command -v codex >/dev/null 2>&1; then
  echo "  codex: $(codex --version 2>/dev/null)"
else
  echo "  codex: NOT INSTALLED"; FAIL=1
fi
if [ -f "$HOME/.codex/auth.json" ]; then
  echo "  auth:  ~/.codex/auth.json present"
else
  echo "  auth:  MISSING — run 'codex login'"; FAIL=1
fi

echo "== symlink integrity =="
for src in "$REPO_DIR"/codex/skills/*/; do
  [ -d "$src" ] || continue
  name="$(basename "$src")"
  target="$CODEX_SKILLS/$name"
  if [ -L "$target" ] && [ "$(readlink -f "$target")" = "$(readlink -f "${src%/}")" ]; then
    echo "  skill $name: OK"
  else
    echo "  skill $name: BROKEN or missing — run 'bash install.sh'"; FAIL=1
  fi
done
for src in "$REPO_DIR"/codex/prompts/*.md; do
  [ -f "$src" ] || continue
  name="$(basename "$src")"
  target="$CODEX_PROMPTS/$name"
  if [ -L "$target" ] && [ "$(readlink -f "$target")" = "$(readlink -f "$src")" ]; then
    echo "  prompt $name: OK"
  else
    echo "  prompt $name: BROKEN or missing — run 'bash install.sh'"; FAIL=1
  fi
done

echo "== secrets + manifests + reachability =="
python3 "$REPO_DIR/lib/env_resolve.py" doctor || FAIL=1

if [ -f "$HOME/.config/agent-secrets/.env" ]; then
  perms="$(stat -c '%a' "$HOME/.config/agent-secrets/.env")"
  if [ "$perms" = "600" ]; then
    echo "== permissions: dedicated store is 600 =="
  else
    echo "== permissions: WARN dedicated store is $perms (expected 600) =="; FAIL=1
  fi
fi

if [ "$FAIL" -eq 0 ]; then echo "ALL CHECKS PASSED"; else echo "PROBLEMS FOUND"; fi
exit "$FAIL"
