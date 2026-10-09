# Shared by install.sh and doctor.sh: where each agent harness looks for
# user-level skills. Sourced, not executed.
#
# A "harness" here is any agent runtime that discovers skills as
# <dir>/<name>/SKILL.md. Add one by extending the three functions below.

KNOWN_HARNESSES="claude codex agents"

# Directory the harness reads user skills from.
harness_skills_dir() {
  case "$1" in
    claude) echo "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills" ;;
    codex)  echo "${CODEX_HOME:-$HOME/.codex}/skills" ;;
    # Cross-harness location read by Codex and other Agent Skills runtimes.
    agents) echo "$HOME/.agents/skills" ;;
    *) return 1 ;;
  esac
}

# Directory for slash-command prompt files, if the harness has one.
harness_prompts_dir() {
  case "$1" in
    codex) echo "${CODEX_HOME:-$HOME/.codex}/prompts" ;;
    *) return 1 ;;
  esac
}

# Whether the harness looks installed on this machine (used by --harness auto).
harness_present() {
  case "$1" in
    claude) [ -d "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" ] || command -v claude >/dev/null 2>&1 ;;
    codex)  [ -d "${CODEX_HOME:-$HOME/.codex}" ] || command -v codex >/dev/null 2>&1 ;;
    agents) [ -d "$HOME/.agents" ] ;;
    *) return 1 ;;
  esac
}

# Resolve a path to its physical location without GNU readlink -f (macOS).
physical_path() {
  if [ -d "$1" ]; then (cd -P "$1" 2>/dev/null && pwd); else
    python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$1"
  fi
}

# Locate the private overlay: --overlay, $AGENT_SKILLS_OVERLAY, an existing
# ~/.config/agent-skills/overlay link, then a sibling agent-skills-private
# checkout next to this repo. Prints nothing when there is none.
find_overlay() {
  local repo_dir="$1" explicit="${2:-}"
  local candidate
  for candidate in "$explicit" "${AGENT_SKILLS_OVERLAY:-}" \
      "$HOME/.config/agent-skills/overlay" "$(dirname "$repo_dir")/agent-skills-private"; do
    [ -n "$candidate" ] || continue
    if [ -d "$candidate" ] && { [ -f "$candidate/secrets.conf" ] || [ -d "$candidate/overlays" ] || [ -d "$candidate/skills" ]; }; then
      physical_path "$candidate"
      return 0
    fi
  done
  return 0
}
