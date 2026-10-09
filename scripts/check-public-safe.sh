#!/usr/bin/env bash
# Fail when files bound for this public repo contain secrets or
# organisation-specific strings.
#
#   scripts/check-public-safe.sh            # staged changes (pre-commit default)
#   scripts/check-public-safe.sh --all      # every tracked + untracked, non-ignored file
#   scripts/check-public-safe.sh --history [REV-RANGE]  # commits in range (default: every ref)
#   scripts/check-public-safe.sh PATH...    # specific files
#
# Two pattern sets:
#   - generic secret shapes (below, public);
#   - the private overlay's denylist.txt, if an overlay is installed
#     ($AGENT_SKILLS_OVERLAY, else ~/.config/agent-skills/overlay). The
#     denylist is never committed here, so CI runs the generic set only.
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OVERLAY="${AGENT_SKILLS_OVERLAY:-$HOME/.config/agent-skills/overlay}"
cd "$REPO_DIR"

patterns="$(mktemp)"; trap 'rm -f "$patterns"' EXIT
cat > "$patterns" <<'PAT'
ATATT[0-9A-Za-z_=-]{20,}
glpat-[0-9A-Za-z_-]{20}
xox[abprs]-[0-9A-Za-z-]{10,}
(AKIA|ASIA)[0-9A-Z]{16}
gh[pousr]_[0-9A-Za-z]{30,}
sk-(ant-)?[A-Za-z0-9_-]{30,}
-----BEGIN [A-Z ]*PRIVATE KEY-----
/home/[a-z][a-z0-9_-]+/|/Users/[A-Za-z][A-Za-z0-9_-]+/
PAT
if [[ -f "$OVERLAY/denylist.txt" ]]; then
  grep -vE '^\s*(#|$)' "$OVERLAY/denylist.txt" >> "$patterns"
  echo "check-public-safe: using overlay denylist ($(grep -vcE '^\s*(#|$)' "$OVERLAY/denylist.txt") patterns)" >&2
else
  echo "check-public-safe: no overlay denylist found; generic secret patterns only" >&2
fi

# This script and the docs that explain the overlay may name the denylist file.
self_ok='^(scripts/check-public-safe\.sh)$'

hits=0
scan_files() {
  local f
  while IFS= read -r f; do
    [[ -f "$f" ]] || continue
    [[ "$f" =~ $self_ok ]] && continue
    if grep -nIiE -f "$patterns" -- "$f" >/dev/null 2>&1; then
      grep -nIiE -f "$patterns" -- "$f" | sed "s#^#$f:#" | cut -c1-200
      hits=1
    fi
  done
}

case "${1:-}" in
  --all)
    scan_files < <(git ls-files --cached --others --exclude-standard) ;;
  --history)
    revs=("${2:---all}")
    if git log -p --no-color "${revs[@]}" | grep -nIiE -f "$patterns" | cut -c1-200; then hits=1; fi
    # Author/committer identities are not in the patch text.
    if git log --format='%ae%n%ce' "${revs[@]}" | sort -u | grep -iE -f "$patterns"; then hits=1; fi ;;
  "")
    scan_files < <(git diff --cached --name-only --diff-filter=ACMR) ;;
  *)
    scan_files < <(printf '%s\n' "$@") ;;
esac

if [[ $hits -ne 0 ]]; then
  echo "check-public-safe: FAIL — move these into the private overlay or genericize them." >&2
  exit 1
fi
echo "check-public-safe: OK" >&2
