Use the `mr-review` skill (at ~/.codex/skills/mr-review/SKILL.md) to perform a
grounded, whole-codebase review of this merge request:

$ARGUMENTS

Follow the skill exactly: fetch into an isolated worktree, trace every changed
symbol through its real callers/tests/config, verify claims by running the
repo's own checks where feasible, and emit the severity-ranked report. Keep the
review local — do not post to GitLab unless I explicitly ask.
