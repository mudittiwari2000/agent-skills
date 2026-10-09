---
name: mr-review
description: Ground and review a GitLab merge request across the whole codebase, not just the diff. Use when the user shares a gitlab.com merge-request URL or IID (e.g. "review this MR", "review !123", pastes a /-/merge_requests/ link), names a branch to review, or asks to review the current working-tree changes, for any repo under ~/dev/repos, including agent tooling repositories (skills, scripts, MCP servers, and plugins). Fetches the MR into an isolated worktree, traces every changed symbol through its real callers/tests/config, checks correctness, regressions, security, error handling, tests, and repo conventions, verifies claims by running the repo's own checks when feasible, and emits a severity-ranked report. Local report by default; optionally posts it to GitLab or to the JIRA ticket identified from the source branch or MR title, but only when explicitly asked and only after verifying that the reviewed commit is still current. When the user wants to review the MR themselves and asks where to look, use guided-mr-review instead.
---

# MR Review (grounded, whole-codebase)

Review a merge request against the **real repository state**, not the diff in
isolation. The diff tells you *what* changed; the job is to judge whether it is
correct *given the rest of the code that uses it*.

When the user wants to review the MR themselves and needs to know where to
look, use the sibling `guided-mr-review` skill instead; it reuses this skill's
fetch and verification.

Repos live under `~/dev/repos` (override with `REPOS_ROOT`). `glab` must be
authenticated to the GitLab host. JIRA REST credentials are loaded by
`scripts/jira_review.py` through the agent-skills secrets resolution;
credential values must never be printed. Do not disturb the user's working copy
— all checkout happens in a throwaway worktree.

Repository scope comes from the MR and local clone, not a Jira project prefix.
A review does not require a Jira ticket or credentials; resolve Jira only for
explicitly requested Jira posting.

## Organisation overlay (optional)

Before starting, look for `${AGENT_SKILLS_OVERLAY:-~/.config/agent-skills/overlay}/overlays/mr-review/profile.md`.
If it exists, read it, and any file it points to, before doing anything else.
It supplies what this skill leaves as placeholders (repo profiles, tracker and
CI tool names, environment access, house conventions) and may add steps.
For facts about the organisation the overlay wins; for method and guardrails
this file wins. Without an overlay, discover the values from the repo and the
user, and record what you learn where the skill says to.

`$SKILL_DIR` below means the directory that holds this `SKILL.md` (the harness
shows it as the skill's base directory; resolve symlinks if needed).

## Workflow

### 1. Fetch the MR into an isolated worktree

Run the helper with whatever the user gave you (MR URL, IID, branch, or nothing
for the current working tree):

```bash
bash $SKILL_DIR/scripts/fetch_mr.sh "<MR-URL | IID | branch>"
# working-tree changes in a repo you're already in:
bash $SKILL_DIR/scripts/fetch_mr.sh --working-tree
```

It prints `MODE`, `REPO_DIR`, `SOURCE_BRANCH`, `TARGET_BRANCH`, `BASE_SHA`,
`HEAD_SHA`, `HEAD_LABEL`, `TITLE`, `WEB_URL`, `EXTERNAL_POSTING_ALLOWED`,
`WORKTREE`, `DIFF_FILE`, `DESCRIPTION_FILE`, and the changed-file list. If it
can't find the local clone for an MR URL, re-run with
`REPO_DIR=~/dev/repos/<name>`.
For a branch, it also resolves an associated open MR when `glab` can find one.
The target branch comes from MR metadata, then `TARGET_BRANCH_OVERRIDE`, then
the remote's actual default branch; do not substitute `main` by assumption.

**`$WORKTREE` is your review root** — it is the full codebase checked out at the
MR HEAD. `cd` into it. `$DIFF_FILE` holds the unified diff (base..head). In
working-tree mode the helper snapshots both tracked and untracked changes into
an isolated worktree; do not review in or mutate the user's original checkout.

Record all printed metadata. `HEAD_LABEL` is the report label; `HEAD_SHA` is the
commit used for external freshness checks. `EXTERNAL_POSTING_ALLOWED=false`
means no concrete MR was resolved, so neither external posting flow may run.

### 2. Orient

- Read `$WORKTREE/AGENTS.md` and `$WORKTREE/CLAUDE.md` if present — apply those
  rules as review criteria.
- Inspect the repository layout and applicable nested `AGENTS.md` / `CLAUDE.md`
  files. Classify the change: product code, agent tooling, or both. An MR that
  touches skills, prompts, agent definitions, hooks, MCP servers or their
  wrappers, or a plugin/runtime manifest counts as agent tooling even when the
  repo also holds product code. For agent tooling, read
  [references/agent-tooling.md](references/agent-tooling.md) now and use its
  checklist alongside the rubric.
- Check [references/repo-profiles.md](references/repo-profiles.md), plus the
  overlay profile's rows when one exists, for the
  repo's known review surfaces and verification quirks. Treat every row as a
  hint to re-verify, not as a fact. Add or correct a row when you discover
  something a future review would otherwise rediscover the hard way.
- Read `$DIFF_FILE` end to end to understand the intent of the change. When the
  diff is too big to hold (rule of thumb: over ~3k changed lines, typically
  long instruction files), keep the executable code and manifests yourself.
  Fan the prose out to subagents, each with a scoped file list, the MR's stated
  claims and the findings you already hold. Spot-verify every High or Blocker
  a subagent returns against the tree before reporting it.
- Read `DESCRIPTION_FILE` when non-empty and record each concrete claim it makes
  (for example "read-only", "never prod", "creates X"). Every claim is checked
  against the code and config in step 4, not just the diff's intent.

### 3. Ground every change (the core step)

For each changed file/symbol, work inside `$WORKTREE`:

- Read the entire enclosing function/class or declarative workflow, not just the
  hunk. For instruction/config changes, trace referenced paths, commands, tool
  names, loaders, and consumers as the equivalent of symbol call sites.
- `git grep -n "<symbol>"` to find its definition and **every call site**, then
  read those call sites — a changed signature or return shape can break code the
  diff never touched.
- Locate and read the tests that exercise the changed code.
- Follow the data: config, env vars, types/interfaces, DB migrations, generated
  clients. Confirm any claimed bug has a real reachable trigger.

### 4. Review across all dimensions and verify

Follow `references/rubric.md` (read it now) for the dimensions, the
verify-don't-assert rule, severity levels, and the exact report format. Where
cheap, run the repo's own type-check / lint / targeted tests inside `$WORKTREE`
to confirm findings, and report exactly what you ran.

- **Environment:** a fresh worktree usually has no virtualenv or
  `node_modules`. Reuse the main clone's environment (`$REPO_DIR/.venv`,
  `$REPO_DIR/venv`, or whatever the repo's test runner probes) read-only, and
  never install into the user's environments to make a check run. For a Node
  workspace, symlink `$REPO_DIR/node_modules` and every nested `node_modules`
  the primary clone has under `apps/*` and `packages/*` into the matching
  worktree paths. Remove the symlinks before cleanup. The
  borrowed deps can lag the MR's lockfile, so a "Cannot find module" failure
  is the environment until a base run shows otherwise. If a check cannot run,
  record "not verified" and why.
- **Baseline any failure:** before you attribute a failing check to the MR,
  run the same command at `BASE_SHA` in a second throwaway worktree
  (`git worktree add --detach <scratch>/base "$BASE_SHA"`, where `<scratch>`
  is the session's scratch or state directory). Remove that worktree
  afterwards with `git worktree remove --force`. `--force` is expected,
  because copying the MR's specs into it makes it dirty. Report failures that already exist on base as
  pre-existing, not as findings. Only failures introduced at `HEAD_SHA`
  count against the MR.
- **Run the relevant suites, not only the MR's own tests:** that includes
  registries, catalogs, manifest and skill-parity tests that enumerate what
  the change adds to.
- **Prove the new tests bite:** copy the MR's new or changed spec files into
  the base worktree and run them against the base code. A regression test that
  passes there does not guard the fix.
- **Check mergeability against the live target:** `git fetch origin
  "$TARGET_BRANCH"` (worktrees share refs, so this also updates the primary
  clone's `origin/$TARGET_BRANCH` tracking ref; that is harmless and expected),
  then `git merge-tree --write-tree --name-only HEAD
  origin/"$TARGET_BRANCH"`. In repos that bump a version on every MR, a stale
  bump conflicts in the manifest and lockfile. That is a real finding even
  when the diff itself is clean.
- **Check the description's claims about callers against the callers:** for
  example "callers omit X" or "covers the Y flow". Read the real arguments at
  each call site. Any evidence collected on a shape no caller produces does
  not cover production.

### 5. Emit the report

Produce the severity-ranked report defined in `references/rubric.md`, every
finding anchored to `file:line` in the current tree. Identify the reviewed
commit with `HEAD_LABEL`. Print it and save the exact emitted Markdown beside
the worktree as `$WORKTREE.review.md`; this persistent file is the sole input
to either posting helper. Do not post anywhere unless explicitly requested.

### 6. Post to GitLab — only when explicitly asked

If (and only if) the user asks to post the review to the MR, first require
`EXTERNAL_POSTING_ALLOWED=true`. If the current request already explicitly asks
to post to the same `WEB_URL`, that is sufficient confirmation; otherwise show
the resolved MR URL and ask for confirmation. Then run:

```bash
python3 $SKILL_DIR/scripts/gitlab_review.py post \
  --mr-url "$WEB_URL" --report "$REPORT_FILE" --head-sha "$HEAD_SHA"
```

The helper passes the report over stdin without shell interpolation, verifies
the live MR head first, and uses GitLab's duplicate protection. If it reports
`STALE_REVIEW`, stop: fetch and review the new head before posting. Use
`--allow-stale` only when the user explicitly asks to post the older review
despite that warning; use `--repost` only when they explicitly request a
duplicate. For inline discussions on specific lines, ask first — bulk inline
comments are noisy.

### 7. Post to JIRA — only when explicitly asked

If (and only if) the user asks to post the review to JIRA, first require
`EXTERNAL_POSTING_ALLOWED=true`:

1. Extract JIRA-looking keys with the case-insensitive pattern
   `\b[A-Z][A-Z0-9]+-\d+\b`. Prefer a key from `SOURCE_BRANCH`; fall back to
   the MR `TITLE`. Normalize it to uppercase.
2. If the branch and title contain different keys, or either contains multiple
   distinct keys, stop and ask which issue is correct. Never guess.
3. Use the already-saved exact report, then verify the derived issue before
   posting:

   ```bash
   python3 $SKILL_DIR/scripts/jira_review.py issue <KEY>
   ```

   The helper uses Jira Cloud REST API v3 and the agent-skills credential
   resolution (`lib/env_resolve.py`): `$JIRA_ENV_FILE` when explicitly set,
   then `~/.config/agent-secrets/.env` (canonical), then the fallback files
   and key aliases named in the overlay's `secrets.conf`, then the shell
   environment. It reads `JIRA_USER_EMAIL` + `JIRA_API_TOKEN` (or
   `JIRA_BEARER_TOKEN`) and `JIRA_BASE_URL` (required — no default); an
   organisation that uses other key names maps them with `alias` lines.
   Credential values are never printed.
4. Confirm that the issue exists and show its key and summary to the user before
   posting, unless the user's current request already explicitly names that same
   key and asks to post.
5. Post the report:

   ```bash
   python3 $SKILL_DIR/scripts/jira_review.py post <KEY> \
     --report <report-file> --mr-title "$TITLE" --mr-url "$WEB_URL" \
     --head-sha "$HEAD_SHA"
   ```

   The helper verifies that `HEAD_SHA` is still the live MR head before it
   connects to JIRA, converts headings and bullets to Atlassian Document Format,
   and includes the MR URL and short head SHA without duplicating the report's
   title. It checks existing comments and skips a duplicate for the same MR URL
   and SHA. If it reports `STALE_REVIEW`, fetch and review the new head before
   posting. Pass `--allow-stale` only when the user explicitly asks to post the
   older review despite that warning. Pass `--repost` only when the user
   explicitly requests a duplicate comment.
6. Report the issue key and whether the helper printed `POSTED_COMMENT_ID` or
   `SKIPPED_DUPLICATE`. On missing credentials, authentication failure, or a
   permission error, do not claim success or fall back to browser automation;
   return the derived key and the helper's sanitized error.

Posting to JIRA does not imply posting to GitLab, or vice versa. Each destination
requires an explicit user request.

### 8. Clean up

When done, remove the worktree, transient diff, and fetched description:

```bash
bash $SKILL_DIR/scripts/fetch_mr.sh --cleanup "$WORKTREE"
```

Cleanup deliberately preserves `$WORKTREE.review.md` as the durable review
artifact. Remove it only if the user asks.

## Rules

- Never report a finding you can't anchor to a line in `$WORKTREE`. No hunk-only
  reasoning.
- Never claim a check passed unless you actually ran it; otherwise write "not
  verified".
- Don't inflate nits into blockers. If the MR is clean, say so.
- Treat the worktree as read-only for review; never push or amend the branch.
- Never post externally unless the user explicitly requested that destination.
