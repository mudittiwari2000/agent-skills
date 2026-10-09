---
name: monitor-dev-ci
description: After a GitLab MR merges (or is set to auto-merge), watch the default-branch pipeline for its merge commit (a monorepo, a single-app service, or any repo with a dev deploy job) until the app is deployed to dev, then hand back the release tag name (from the bumped app version), the merge commit id, the annotation text, and a prefilled GitLab new-tag link (tag name + merge commit filled in) for creating the tag manually. Use when the user says an MR is merged / on auto-merge and asks to "monitor the dev pipeline", "tell me when it's on dev", "give me the tag", or invokes /monitor-dev-ci with an MR IID or commit. Read-only: never creates the tag, never retries or re-runs jobs without asking.
---

# Monitor an MR through to dev, then prepare its release tag

The user merges an MR (often via auto-merge), then wants to know when it is
live on dev, and needs three things to cut the release tag by hand in GitLab:

1. the **tag name**, built from the version the MR bumped
2. the **merge commit id** on the default branch to tag
3. the **annotation text** for the tag

This skill watches and reports. It does **not** create the tag, and it does not
retry, re-run or cancel jobs unless the user asks — a failed deploy is reported
with its log, not papered over.

## Organisation overlay (optional)

Before starting, look for `${AGENT_SKILLS_OVERLAY:-~/.config/agent-skills/overlay}/overlays/monitor-dev-ci/profile.md`.
If it exists, read it, and any file it points to, before doing anything else.
It supplies what this skill leaves as placeholders (repo profiles, tracker and
CI tool names, environment access, house conventions) and may add steps.
For facts about the organisation the overlay wins; for method and guardrails
this file wins. Without an overlay, discover the values from the repo and the
user, and record what you learn where the skill says to.

## Inputs

- **MR IID** (e.g. `123`) — preferred. Or a merge commit SHA on the default branch.
- **Repo** — the overlay may name a default project path. Take
  it from the MR link when one is given, or from the current checkout's
  `origin` remote. `$P` below is the URL-encoded project path. Use `glab api`,
  which is authenticated as the user.
- **App** — derive it; don't ask. In a monorepo it is the `apps/<app>` whose
  `package.json` version the MR changed (e.g. `<app>`). If the MR bumped
  more than one app, handle each; if it bumped none, say so — there is no new
  tag to cut. A single-app repo has no `<app>`: the root `package.json` is the
  version.

## Repo profiles

Everything that differs per repo lives here. `$BRANCH` below is the profile's
default branch. For a repo not listed, read the real values off its most recent
default-branch pipeline and its latest tags (commands in steps 2 and 4), use
them, and add a row here afterwards (or to the overlay's profile table, when
an overlay is installed — the overlay holds the real rows).

| | `<monorepo>` | `<single-app service>` |
|---|---|---|
| Project path | `<group>/<project>` | `<group>/<project>` |
| `$P` | `<group>%2F<project>` | `<group>%2F<project>` |
| Default branch | `main` | `main` / `master` |
| Version source | `apps/<app>/package.json` + `package-lock.json` `.packages["apps/<app>"].version` | root `package.json` `.version` + `package-lock.json` `.version` |
| Dev deploy job | `deploy_dev_<app_underscored>` | `deploy_dev`, then any post-deploy job |
| CDN invalidation | `cdn_invalidation_dev_<app_underscored>` | none |
| Tag name (`$TAG`) | `<app>-v<version>` | `v<version>` |
| `$TAG_PREFIX` | `<app>-v` | `v` |
| Tag message style | from real tags (step 4) | from real tags (step 4) |

## 1. Wait for the merge

```bash
glab api "projects/$P/merge_requests/$IID" | jq '{state, merged_at, merge_when_pipeline_succeeds, merge_commit_sha, squash_commit_sha, sha, detailed_merge_status}'
```

- `state=merged` → take `merge_commit_sha` (the commit on `$BRANCH` that the
  default-branch pipeline runs for). Fall back to `squash_commit_sha` only when there is no
  merge commit (fast-forward/squash-only projects).
- `state=opened` with `merge_when_pipeline_succeeds=true` → auto-merge is armed;
  wait for `state=merged`. Watch for it going stale instead: `detailed_merge_status`
  of `conflict` / `need_rebase`, or a failed MR pipeline, means auto-merge will
  never fire — stop and tell the user rather than waiting forever.
- `state=opened` without auto-merge, or `closed` → report and stop.

**Check the version didn't go stale on the way in.** A long auto-merge wait lets
other MRs land version bumps. Compare the MR's version (from the profile's
version source) with `origin/$BRANCH`'s at merge time and the existing tags. If
the number is already taken, say so before the merge lands — the user will want
to re-bump (both `package.json` and `package-lock.json`, from `origin/$BRANCH`'s
version + 1, skipping any number another open MR already claims).

## 2. Find the default-branch pipeline for that commit

```bash
glab api "projects/$P/pipelines?sha=$MERGE_SHA&ref=$BRANCH&per_page=5" | jq '.[] | {id, status, source, created_at}'
glab api "projects/$P/pipelines/$ID/jobs?per_page=100" | jq -r '.[] | "\(.status)\t\(.stage)\t\(.name)"'
```

It can take a few seconds to appear after the merge — poll, don't give up on
the first empty result.

Read the dev path off the job list: the ordered chain of build, deploy and any
post-deploy jobs (CDN invalidation, parameter update, tag push) for this app.
The overlay lists the known chains per repo. A typical monorepo chain, with the
app name's dashes turned into underscores in job names:

| Stage | Job |
|---|---|
| `build_image_dev` | `build_image_and_push_dev_<app_underscored>` |
| `deploy_to_dev` | `deploy_dev_<app_underscored>` |
| `cdn_invalidation_dev` | `cdn_invalidation_dev_<app_underscored>` |
| `push_tag_to_dev` | `push_tag_to_dev_<app_underscored>` |

When a job runs after the deploy (a parameter or config update, a CDN
invalidation), "on dev" is the deploy job = success, but wait for that last
job before reporting — it is the last step of the dev path.

Other jobs (tests, lint, scanning, e2e, cleanup) are not the deploy. Report
their outcome, but "on dev" means the app's dev deploy job succeeded. Re-read
the job list rather than trusting a table blindly — if the names differ for
another repo or app, use the job in the dev deploy stage for that app.

## 3. Watch until dev is deployed

Run one background watcher (Bash with `run_in_background: true`) that exits on
**every** terminal state, not only success, so a failure cannot look like
"still running":

```bash
while true; do
  st=$(glab api "projects/$P/pipelines/$ID/jobs?per_page=100" | jq -r --arg j "$DEPLOY_JOB" '.[] | select(.name==$j) | .status')
  ps=$(glab api "projects/$P/pipelines/$ID" | jq -r .status)
  case "$st" in success|failed|canceled|skipped|manual) break;; esac
  case "$ps" in failed|canceled) break;; esac
  sleep 30
done
echo "deploy: $st / pipeline: $ps"
```

Don't chain foreground `sleep`s. Keep the user posted in one line when it starts.

- **`success`** → also wait for the CDN invalidation job when the profile has
  one (until it finishes, a cached page can still serve the old build), then
  continue.
- **`failed`** → fetch the trace tail and report it; do not retry:
  `glab api "projects/$P/jobs/$JOB_ID/trace" | tail -60`
- **`manual`** → the deploy is gated on a human click; tell the user which job.
- **`canceled` / `skipped`** → report; ask before anything else.

## 4. Build the three outputs

**Tag name** — the profile's tag pattern (`<app>-v<version>` in a monorepo,
`v<version>` in a single-app repo), where version is read from the merge commit
itself, not the branch:

```bash
git fetch -q origin $BRANCH
# monorepo
git show $MERGE_SHA:apps/<app>/package.json | jq -r .version
git show $MERGE_SHA:package-lock.json | jq -r '.packages["apps/<app>"].version'   # must match
# single-app repo
git show $MERGE_SHA:package.json | jq -r .version
git show $MERGE_SHA:package-lock.json | jq -r .version                           # must match

git ls-remote --tags origin "$TAG"                              # must print nothing — never reuse a tag
git ls-remote --tags --sort=-v:refname origin "$TAG_PREFIX*" | head -3
```

Check tags on the **remote** with `git ls-remote`, not `git tag -l`. A local
`git fetch --tags` in a large monorepo can exit non-zero on unrelated tags that "would
clobber existing tag", which silently breaks any `&&` chain after it, and local
tags can be stale anyway.

If the tag already exists, stop and say so — the MR's bump collided and the
user needs a new number, not a duplicate tag.

**Merge commit id** — the full 40-char `merge_commit_sha`, plus the short form.
Confirm it is on the default branch (`git branch -r --contains $MERGE_SHA`
includes `origin/$BRANCH`).

**Tag annotation text** — follow the house style, read from real tags. Fetch
the few latest tags explicitly first; local tags may be missing or stale:

```bash
git fetch -q origin "refs/tags/$TAG_PREFIX*:refs/tags/$TAG_PREFIX*" 2>/dev/null
git for-each-ref "refs/tags/$TAG_PREFIX*" --sort=-v:refname --count=6 --format='%(refname:short)%0a%(contents)%0a---'
```

The style differs by repo; the overlay records each repo's style. Common
shapes:

- **Plain-language** — one or two lines saying what
  changed for users (a `- ` bullet list when the release has several changes).
  No tracker keys, no commit hashes, no "Merge branch …". Write it from the MR's
  title and description, in the product's terms: what now works, not how the
  code changed. If one merge carries several user-facing changes, one bullet
  each.
- **Key + title** — a single line: the tracker key and the MR title, e.g.
  `PROJ-123 <MR title>`.
  Drop a leading "Draft:" and never use "Merge branch …".

## 5. Report

Give the user, in plain text (no blockquotes — they copy it):

- dev status: deploy job id + result, CDN invalidation result, pipeline URL
- **Tag name**
- **Merge commit** (full SHA, short SHA) and its URL:
  `https://gitlab.com/<project path>/-/commit/<full sha>`
- **Tag message**, in a fenced code block, ready to paste
- **Prefilled new-tag page — always, every run, never optional.** A link that
  opens GitLab's "New tag" form with the tag name and the merge commit already
  filled in, so the user only pastes the message and clicks Create:
  `https://gitlab.com/<project path>/-/tags/new?tag_name=<tag>&ref=<full sha>`
  Use the **full** 40-char SHA for `ref`, not the short one or a branch name, so
  the tag lands on the merge commit even if the branch has moved on. It also
  goes in the report when the deploy failed or is waiting on a manual step (say
  "don't create it until the deploy is fixed"). The only time to leave it out
  is when the tag already exists, and then say so instead.

The user asked for this link explicitly and wants it returned on every run.

Mention anything that didn't go cleanly (e2e failures, a manual gate, a
version that was bumped by another MR in the meantime) — briefly, after the
three outputs.

## Next: stage

Once the user has cut the tag, `/monitor-stage-ci <tag>` follows the release to
stage. It uses the same repo-profile layout, so the two skills can later merge
into one skill that takes the environment as a parameter.

## Guardrails

- Never create, move or delete tags; the user cuts the tag.
- Never retry, re-run, cancel or play jobs without an explicit ask.
- Never report "on dev" off the pipeline being green overall — key off the
  deploy job for this app.
- Never guess the version from the branch; read it from the merge commit.
- Never finish a report without the prefilled new-tag link (step 5), unless
  the tag already exists.
