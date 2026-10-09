# agent-skills

Engineering-workflow skills for AI coding agents: grounded code and doc review,
review-comment resolution, CI and deploy monitoring, root-cause write-ups,
scope audits, estimation and feature-flag release tracking.

Every skill is a folder with a `SKILL.md` ([Agent Skills](https://agentskills.io)
format), so the same skill works in Claude Code, Codex and any other harness
that reads `<dir>/<name>/SKILL.md`.

## Skills

| Skill | What it does |
|---|---|
| [mr-review](skills/mr-review) | Reviews a GitLab MR against the whole codebase in an isolated worktree: traces callers, runs the repo's own checks, checks the MR's tests catch the bug, emits a severity-ranked report. Posts to GitLab or Jira only when asked. |
| [confluence-review](skills/confluence-review) | Reviews a Confluence doc (PRD, design doc, runbook, ADR) for completeness, correctness, ambiguity and staleness; optional grounding against Jira and code. |
| [mr-comment-resolution](skills/mr-comment-resolution) | Works through review comments on your own MR: verifies each, fixes what belongs, tickets what does not, replies with a table the reviewer can check. |
| [scope-audit](skills/scope-audit) | A fresh agent that sees only the acceptance criteria, your explicit asks and the diff classifies every hunk as required, supporting, not required or dead. |
| [jira-story-estimation](skills/jira-story-estimation) | Estimates stories from their own acceptance criteria and the real code, with an adversarial second pass and an audit trail. |
| [monitor-dev-ci](skills/monitor-dev-ci) | Watches the default-branch pipeline after a merge until the app is on dev, then hands back the release tag, commit and a prefilled new-tag link. |
| [monitor-stage-ci](skills/monitor-stage-ci) | Follows a tag to stage, names the manual gate to click, proves what is live and scans for config deploys nobody played. |
| [rca-report](skills/rca-report) | Investigates an incident to its root cause (reproduce, isolate, trace, date) and writes the RCA, with a two-phase non-prod-then-prod access gate. |
| [prod-flag-ledger](skills/prod-flag-ledger) | Ledger of every feature flag a story adds; from release notes, works out which flags must go on in prod for that release. |
| [test-skill-branch](skills/test-skill-branch) | Points a local skills/plugin checkout at an unmerged skill branch (or back at main) while keeping it synced. |

## Install

### Any harness (recommended)

```bash
git clone https://github.com/mudittiwari2000/agent-skills.git ~/dev/repos/agent-skills
bash ~/dev/repos/agent-skills/install.sh            # every harness found on this machine
bash ~/dev/repos/agent-skills/doctor.sh             # verify
```

`install.sh` symlinks each skill into the harness's skills directory, so a
`git pull` updates every harness at once. Re-run it after pulling to pick up new
or renamed skills.

| Flag | Effect |
|---|---|
| `--harness claude,codex,agents` (or `all`) | Pick harnesses: `~/.claude/skills`, `$CODEX_HOME/skills` (+ Codex prompts), `~/.agents/skills` |
| `--target DIR` | Any other harness: link the skills into `DIR` (repeatable) |
| `--replace` | A real folder already sits where a skill goes: back it up under `~/.local/state/agent-skills/backup/` and link |
| `--overlay DIR` | Use a private overlay checkout (otherwise auto-detected, see below) |
| `--adopt` | Move unmanaged skills you wrote locally into the private overlay (lists them and asks first) |
| `--bootstrap-secrets` | Create or fill `~/.config/agent-secrets/.env` from the key template |
| `--no-deps` | Skip `npm ci` for skills that ship script dependencies |
| `--dry-run`, `--uninstall` | Preview; remove only the links this repo created |

Requires bash, git and python3 (macOS, Linux, WSL). Skills with Node scripts
(`rca-report`) also need npm.

### Claude Code plugin

```
/plugin install agent-skills --marketplace mudittiwari2000/agent-skills
```

(Older Claude Code: `/plugin marketplace add mudittiwari2000/agent-skills`, then
`/plugin install agent-skills@mudit-agent-skills`.)

This copies the public skills only. Use `install.sh` if you also use a private overlay.

## Private overlay

The public skills hold the method and its guardrails. Anything specific to one
organisation is left as a placeholder: repo profiles, CI job names, tracker
tools, environment access, house conventions. A **private overlay** fills it in.

```
agent-skills-private/            # a separate PRIVATE repo
  overlays/<skill>/profile.md    # org facts + extra steps for one public skill
  skills/<name>/                 # skills that are entirely org-specific
  secrets.conf                   # fallback secrets files + key aliases (no values)
  denylist.txt                   # org strings the pre-commit hook blocks here
```

Each skill opens with an "Organisation overlay" step. It reads
`${AGENT_SKILLS_OVERLAY:-~/.config/agent-skills/overlay}/overlays/<skill>/profile.md`
when it exists. Where the two disagree, the overlay wins on organisation facts
and the public skill wins on method and guardrails. Without an overlay, the
skill discovers what it needs from the repo and asks you.

`install.sh` finds the overlay from `--overlay`, `$AGENT_SKILLS_OVERLAY`, an
existing `~/.config/agent-skills/overlay` link, or an `agent-skills-private`
checkout next to this repo. It links the overlay at
`~/.config/agent-skills/overlay` and installs its `skills/` too.

## Secrets

Values never live in either repo. Scripts resolve keys through
[`lib/env_resolve.py`](lib/env_resolve.py), first hit wins:

1. `$AGENT_SECRETS_FILE`
2. `~/.config/agent-secrets/.env` (chmod 600)
3. the fallback files in the overlay's `secrets.conf`, then `$AGENT_SECRETS_FALLBACKS`
4. the shell environment

Skills use generic names (`JIRA_BASE_URL`, `JIRA_USER_EMAIL`, `JIRA_API_TOKEN`,
`CONFLUENCE_*`, `GITLAB_TOKEN`; see [secrets/.env.example](secrets/.env.example)).
An organisation that already uses other names maps them in `secrets.conf`:

```
alias JIRA_API_TOKEN = ORG_JIRA_API_TOKEN, JIRA_API_TOKEN   # first that resolves wins
```

`bash doctor.sh` reports which keys each skill's `manifest.yaml` needs and
whether they resolve. It never prints values.

## Keeping it public-safe

- `install.sh` turns on a pre-commit hook (`.githooks/pre-commit`) that runs
  [`scripts/check-public-safe.sh`](scripts/check-public-safe.sh). It checks for
  generic secret shapes plus your overlay's `denylist.txt`.
- CI runs the generic patterns and gitleaks over the full history, the syntax
  checks, the marketplace sync check and an install into every harness.
- Scan everything yourself with `scripts/check-public-safe.sh --all` and
  `--history`.

## Adding a skill

1. Create `skills/<name>/SKILL.md` with frontmatter `name` (equal to the folder)
   and `description` (what it does and when to use it). Add `scripts/` and
   `references/` as needed.
2. Put organisation specifics in `overlays/<name>/profile.md` in the private
   overlay, and add the "Organisation overlay" section from any existing skill.
3. Declare secrets in `skills/<name>/manifest.yaml`. Scripts that need them find
   `lib/env_resolve.py` by walking up from their own path (see
   `skills/confluence-review/scripts/confluence_api.py`) and must never print
   values.
4. Optional Codex slash command: `prompts/codex/<name>.md`.
5. `python3 scripts/sync-marketplace.py && bash install.sh && bash doctor.sh`.

## License

[MIT](LICENSE)
