# agent-skills

Version-controlled home for my agent skills (Codex CLI today, extensible to
Claude Code) and the **key names** — never values — of the secrets that
support them.

## Layout

```
codex/skills/<name>/        # one Codex skill per dir (SKILL.md, scripts/, references/)
codex/skills/<name>/manifest.yaml   # secrets the skill needs (required/any_of/optional)
codex/prompts/<name>.md     # slash-command wrapper for the skill
lib/env_resolve.py          # shared secrets resolution + bootstrap + doctor
secrets/.env.example        # every known key, documented, NO values (committed)
mcp/                        # MCP server config templates referencing key names
install.sh                  # symlink deploy into ~/.codex + secrets bootstrap
doctor.sh                   # end-to-end health check (never prints values)
```

## Secrets model

Real values live **outside this repo** in `~/.config/agent-secrets/.env`
(chmod 600). Scripts resolve keys through a chain, first hit wins:

1. `$AGENT_SECRETS_FILE` (explicit override)
2. `~/.config/agent-secrets/.env` (canonical)
3. `~/.hermes/profiles/pegasus/.env` then `~/.hermes/.env` (per-key fallback)

`install.sh --bootstrap-secrets` creates the canonical file from
`secrets/.env.example` and copies values for matching keys from the Pegasus
profile. Adding a new secret = add the key to `.env.example` (name only),
declare it in the skill's `manifest.yaml`, put the value in
`~/.config/agent-secrets/.env`, run `bash doctor.sh`.

## Install / update

```bash
bash install.sh                       # symlink skills + prompts into ~/.codex
bash install.sh --adopt               # also adopt unmanaged dirs from ~/.codex/skills
bash install.sh --bootstrap-secrets   # also create/fill the canonical secrets file
bash doctor.sh                        # verify everything (no secret values printed)
```

Symlinks mean edits here are live immediately — no re-install needed except
when adding a *new* skill or prompt.

## Adding a skill

1. `mkdir codex/skills/<name>` with `SKILL.md` (frontmatter: `name`,
   `description`), plus `scripts/`, `references/` as needed.
2. Declare its secrets in `codex/skills/<name>/manifest.yaml`.
3. Optional slash command: `codex/prompts/<name>.md` using `$ARGUMENTS`.
4. `bash install.sh && bash doctor.sh`.

Scripts should import `lib/env_resolve.py` (see
`codex/skills/confluence-review/scripts/confluence_api.py` for the pattern)
and must never print credential values.

## Skills

- **confluence-review** — review a Confluence document (PRD/design/runbook)
  against a severity rubric; optional Jira/code grounding; opt-in comment
  posting with page-version staleness gate.
- **mr-review** — grounded whole-codebase GitLab MR review (adopted from the
  original `~/.codex/skills` copy).
