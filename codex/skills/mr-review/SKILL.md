---
name: mr-review
description: Ground and review a GitLab merge request across the whole codebase, not just the diff. Use when the user shares a gitlab.com merge-request URL or IID (e.g. "review this MR", "review !123", pastes a /-/merge_requests/ link), names a branch to review, or asks to review the current working-tree changes, for any repo under ~/dev/repos. Fetches the MR into an isolated worktree, traces every changed symbol through its real callers/tests/config, checks correctness, regressions, security, error handling, tests, and repo conventions, verifies claims by running the repo's own checks when feasible, and emits a severity-ranked report. Local report by default; optionally posts it to GitLab or to the JIRA ticket identified from the source branch or MR title, but only when explicitly asked and only after verifying that the reviewed commit is still current.
---

# MR Review (grounded, whole-codebase)

Review a merge request against the **real repository state**, not the diff in
isolation. The diff tells you *what* changed; the job is to judge whether it is
correct *given the rest of the code that uses it*.

Repos live under `~/dev/repos` (override with `REPOS_ROOT`). `glab` must be
authenticated to the GitLab host. JIRA REST credentials are loaded by
`scripts/jira_review.py` through the agent-skills secrets resolution;
credential values must never be printed. Do not disturb the user's working copy
— all checkout happens in a throwaway worktree.

## Workflow

### 1. Fetch the MR into an isolated worktree

Run the helper with whatever the user gave you (MR URL, IID, branch, or nothing
for the current working tree):

```bash
bash ~/.codex/skills/mr-review/scripts/fetch_mr.sh "<MR-URL | IID | branch>"
# working-tree changes in a repo you're already in:
bash ~/.codex/skills/mr-review/scripts/fetch_mr.sh --working-tree
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
- Read `$DIFF_FILE` end to end to understand the intent of the change.
- Read `DESCRIPTION_FILE` when non-empty and note the stated intent so you can
  check the diff actually delivers it.

### 3. Ground every change (the core step)

For each changed file/symbol, work inside `$WORKTREE`:

- Read the entire enclosing function/class, not just the hunk.
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
python3 ~/.codex/skills/mr-review/scripts/gitlab_review.py post \
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
   python3 ~/.codex/skills/mr-review/scripts/jira_review.py issue <KEY>
   ```

   The helper uses Jira Cloud REST API v3 and the agent-skills credential
   resolution. It loads `$JIRA_ENV_FILE` when explicitly set; otherwise
   `~/.config/agent-secrets/.env` (canonical), then `$HERMES_HOME/.env`,
   `~/.hermes/profiles/pegasus/.env`, `~/.hermes/.env`. The user-level file
   overrides stale shell values and a nearest repo `.env` only fills missing
   values. Credential precedence is `PEI_JIRA_USER_EMAIL` +
   `PEI_JIRA_API_TOKEN`, then legacy `JIRA_USER_EMAIL` +
   `JIRA_DIRECT_API_TOKEN`/`JIRA_API_TOKEN`. Base URL precedence is
   `PEI_JIRA_BASE_URL`, then `JIRA_BASE_URL` (required — no default).
   Credential values are never printed.
4. Confirm that the issue exists and show its key and summary to the user before
   posting, unless the user's current request already explicitly names that same
   key and asks to post.
5. Post the report:

   ```bash
   python3 ~/.codex/skills/mr-review/scripts/jira_review.py post <KEY> \
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
bash ~/.codex/skills/mr-review/scripts/fetch_mr.sh --cleanup "$WORKTREE"
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
