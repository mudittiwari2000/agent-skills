---
name: test-skill-branch
description: Point the local checkout of a skills/plugin repo (the one your agent launcher loads skills from) at an unmerged skill branch (or back at main) while keeping it synced to main. Use when the user says /test-skill-branch, "switch the plugin to <skill or branch>", "point the plugin at main", "which skill branch is the plugin on", or asks to add a skill branch to the list, or to sync/refresh one or all skill branches against main. Takes a skill key from branches.tsv, a raw branch name, `main`, `status`, `sync`, `sync-all`, or `add <key> <branch>`.
---

# test-skill-branch

Many setups launch the agent with a plugin or skills directory taken from a local checkout of a
skills repo, often after a plain `git pull` (the "launcher" below).
Whatever branch that checkout is on is the set of skills the user gets. This skill moves the checkout
between unmerged skill branches and `main`, and keeps each skill branch rebased on `origin/main`
so the rest of the repo stays current.

## Organisation overlay (optional)

Before starting, look for `${AGENT_SKILLS_OVERLAY:-~/.config/agent-skills/overlay}/overlays/test-skill-branch/profile.md`.
If it exists, read it, and any file it points to, before doing anything else.
It supplies what this skill leaves as placeholders (repo profiles, tracker and
CI tool names, environment access, house conventions) and may add steps.
For facts about the organisation the overlay wins; for method and guardrails
this file wins. Without an overlay, discover the values from the repo and the
user, and record what you learn where the skill says to.

## Repo profile

Each value comes from its environment variable when set, else from the overlay profile, else ask
the user once (and suggest they export the variable or add it to the overlay).

| Setting | Source | Example |
|---|---|---|
| Repo | `SKILL_REPO_DIR`: path of the skills/plugin checkout the launcher loads | `$HOME/dev/repos/<plugin-repo>` |
| Launcher | `SKILL_REPO_LAUNCHER`: the command that pulls the checkout and starts the agent with it | `<launcher>` |
| Default branch | `SKILL_REPO_MAIN` (default `main`; remote `origin`) | `main` |
| Regenerated tracked files | `SKILL_REPO_REGENERATED`: space-separated tracked files that tooling rewrites on every run (safe to stash/restore); empty if none | `path/to/generated.json` |
| Mapping | see below: `<skill key><TAB><branch>`, one per line | |

This file writes `main` for the default branch. If `SKILL_REPO_MAIN` is something else, use that
value wherever `main` appears in a command below.

**Mapping file.** Read the first that exists:

1. `${AGENT_SKILLS_OVERLAY:-~/.config/agent-skills/overlay}/overlays/test-skill-branch/branches.tsv`
2. `branches.tsv` next to this file (local and untracked; the repo ignores it).

If neither exists, the mapping is empty; `branches.example.tsv` next to this file shows the format.
`add` writes to the overlay's `branches.tsv` when the overlay directory
`overlays/test-skill-branch/` exists (creating the file if needed), else to the local untracked
`branches.tsv` next to this file. Never write the mapping into `branches.example.tsv`.

The tracking model this skill relies on: git has `pull.rebase=true` globally, `rebase.autostash=true`
and `push.default=current` in the repo. So a skill branch whose `branch.<b>.merge` is
`refs/heads/main` gets rebased onto `origin/main` by every launcher pull, and `git push` still
targets the same-named remote branch. Never "correct" those three settings. If the repo lacks
them, say so in the report and ask before setting them.

## Arguments

- `<key>` → look it up in the mapping file.
- `<branch>` → a raw branch name (any value that is not a key, not `main`, not a command).
- `main` → back to plain main.
- `sync` → refresh the **current** branch against `origin/main` (see Sync). No switching.
- `sync-all` → refresh **every** mapped branch plus local `main`, staying on the current branch
  (see Sync-all). `sync <key>` is not an alias: to refresh a specific other branch, use `<key>`
  (switches to it) or `sync-all`.
- `status` (or no argument) → report only, change nothing.
- `add <key> <branch>` → append to the mapping file (see Repo profile for which one; reject a
  duplicate key or branch; confirm the branch exists on `origin` first). No git changes.

An unknown key that does not look like a branch: print the mapping and stop. Do not guess.

## status

Report: current branch; whether it is a mapped skill branch (and its key); ahead/behind vs
`origin/main` after a `git fetch origin`; dirty files; the full mapping with each branch's
ahead/behind vs `origin/main` and whether it is checked out in another worktree.

## Switch procedure

Run from the repo dir. Stop and report at the first failing step; never force anything.

1. `git fetch origin --prune`. A failed fetch stops the run (a stale view is the main risk here).
2. **Already on it?** If the current branch is the target, skip to step 6.
3. **Worktree guard.** `git worktree list --porcelain`: if the target is checked out in a *different*
   worktree, git will refuse the checkout. Stop and tell the user which path holds it. Do not remove
   or detach that worktree without their say-so. Offer: remove the worktree (only if clean and
   pushed), or test from that worktree path instead.
4. **Dirty-tree guard.** `git status --porcelain`. Only the regenerated file(s) in the profile may
   be dirty; untracked files are ignored. Anything else dirty: stop and list it.
   If a regenerated file is dirty, `git stash push -m test-skill-branch -- <file>` and remember to pop.
5. **Checkout.**
   - `main`: `git checkout main && git merge --ff-only origin/main`. Local `main` may be far behind;
     an ff-only failure means local `main` has commits of its own: stop and report.
   - Skill branch with a local ref: `git checkout <branch>`.
   - Skill branch with only `origin/<branch>`: `git checkout -b <branch> --track origin/<branch>`.
   - Neither exists: stop. The branch name is probably wrong; show near matches from
     `git branch -a --list '*<ticket-key>*'`.
   Then `git stash pop` if step 4 stashed. A pop conflict: stop and report, leave the stash.
6. **Keep it synced to main** (skill branches only, not `main`):
   - `git config branch.<b>.remote origin` and `git config branch.<b>.merge refs/heads/main`.
     This is what makes the next launcher pull rebase onto main instead of the stale remote branch.
   - If behind `origin/main` by N > 0: back up first with a timestamped ref, so earlier backups
     are never overwritten:
     `git branch "pre-rebase-backup/<b>-$(date +%Y%m%d-%H%M%S)" <b>`
     (for example `pre-rebase-backup/PROJ-123/my-skill-20260101-120000`), then `git rebase origin/main`
     (autostash handles the regenerated file). On conflict: `git rebase --abort`, report the
     conflicting files, leave the branch exactly as it was.
   - Report `ahead/behind origin/main` afterwards.
7. **Report** (short, no blockquotes): previous branch → new branch, key, ahead/behind vs
   `origin/main`, whether a rebase ran (and the backup ref name), and this reminder:
   *skills load when the launcher starts, so restart the agent for the switch to take effect.*

## Sync

Refresh the current branch without switching. Run Switch steps 1 and 4, then:

- On `main`: `git merge --ff-only origin/main`.
- On a mapped skill branch: Switch step 6 (set `remote`/`merge`, back up, rebase, report).
- On any other branch: stop and say so. Do not rebase unmapped branches.

Report: branch, behind-count before, ahead/behind after, and whether a rebase ran (with backup ref).

## Sync-all

Refresh every mapped branch and local `main` without leaving the current branch.

1. `git fetch origin --prune` (a failure stops the run).
2. **Local `main`:** if `main` is not checked out in any worktree,
   `git fetch origin main:main` (fast-forward only; a refusal means local `main` has commits of
   its own: report, don't force). If `main` is checked out somewhere, skip it and say where.
3. For each mapped branch, in file order, and when behind `origin/main` by N > 0:
   - **Current branch:** run the Sync steps in place.
   - **Checked out in another worktree:** skip, report `skipped: checked out at <path>, behind N`.
     Never touch another worktree.
   - **Any other branch:** rebase it in a temporary worktree so the main checkout never moves:
     `tmp=$(mktemp -d)`; if no local ref, `git worktree add -b <b> --track "$tmp" origin/<b>`,
     otherwise `git worktree add "$tmp" <b>`; set `branch.<b>.remote origin` and
     `branch.<b>.merge refs/heads/main`; `git branch "pre-rebase-backup/<b>-$(date +%Y%m%d-%H%M%S)" <b>`
     (only if it already existed locally); `git -C "$tmp" rebase origin/main`. On conflict:
     `git -C "$tmp" rebase --abort`, report the conflicting files, leave the branch as it was.
     Always `git worktree remove --force "$tmp"` afterwards, success or not.
   - Already up to date (N = 0): still ensure the `remote`/`merge` config, no rebase.
4. **Report one table:** key, branch, before (ahead/behind), after (ahead/behind), action
   (`rebased` / `up to date` / `created + rebased` / `skipped: <reason>` / `conflict: <files>`),
   backup ref where one was made. End with the restart reminder only if the current branch rebased.

## Rules

- Never push, never force-push. A rebased skill branch now differs from its stale remote branch;
  publishing that is the branch owner's call. Say so when a rebase ran.
- Never `git reset --hard`, never delete branches or worktrees, never touch other worktrees.
  The one exception: the temporary worktree that `sync-all` itself creates, which it removes.
- Never overwrite a backup ref: each backup gets its own timestamp suffix.
- Do not discard the regenerated tracked file: stash and restore, or let autostash carry it.
- `add` only edits the mapping file. Keep it sorted by nothing in particular; order is insertion order.
