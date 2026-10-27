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
| Stage announcement names | `<tag>` (the tag already names the app) | `<service> <tag>` (a bare `v<version>` names nothing) |

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

**Check what else the tag will carry.** List the merges on `$BRANCH` between the
previous release tag and this merge commit that touched the app
(`git log --merges --oneline <prev tag>..$MERGE_SHA -- apps/<app>`). A merge that
changed the app without bumping its version ships under *this* tag, so its
user-facing change belongs in the tag message too. Name it in the report.

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
# GitLab job JSON can carry raw control characters (e.g. in commit messages),
# which jq rejects; parse leniently, and give up after repeated empty reads
# instead of looping for ever on a parse or auth error.
field() { python3 -c 'import sys,json
d=json.loads(sys.stdin.read(),strict=False); j=sys.argv[1]
if j: print(next((x.get("status","") for x in d if isinstance(x,dict) and x.get("name")==j),"") if isinstance(d,list) else "")
else: print(d.get("status","") if isinstance(d,dict) else "")' "$1" 2>/dev/null; }
miss=0
while true; do
  st=$(glab api "projects/$P/pipelines/$ID/jobs?per_page=100" 2>/dev/null | field "$DEPLOY_JOB")
  ps=$(glab api "projects/$P/pipelines/$ID" 2>/dev/null | field "")
  if [ -z "$st" ] || [ -z "$ps" ]; then miss=$((miss+1)); [ $miss -ge 5 ] && { st=unreadable; break; }; else miss=0; fi
  case "$st" in success|failed|canceled|skipped|manual) break;; esac
  case "$ps" in failed|canceled) break;; esac
  sleep 30
done
echo "deploy: $st / pipeline: $ps"
```

`unreadable` means the watcher could not read the job list five times in a row
(API, auth or parse error). Report it and check by hand; never treat it as
"still running".

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
git show "${MERGE_SHA}:apps/<app>/package.json" | jq -r .version
git show "${MERGE_SHA}:package-lock.json" | jq -r '.packages["apps/<app>"].version'   # must match
# single-app repo
git show "${MERGE_SHA}:package.json" | jq -r .version
git show "${MERGE_SHA}:package-lock.json" | jq -r .version                           # must match

git ls-remote --tags origin "$TAG"                              # must print nothing — never reuse a tag
git ls-remote --tags --sort=-v:refname origin "$TAG_PREFIX*" | head -3
```

Write `"${MERGE_SHA}:<path>"` with braces and quotes. In zsh, `$MERGE_SHA:apps/…`
reads `:a` as a path modifier (make absolute) and git gets a nonsense revision.

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

## 6. Notify (when a notify webhook is configured)

The watch can take a while, so the user may not be looking at the terminal when
it ends. When the overlay names a notification webhook (for example a Slack
incoming webhook that can post to one private channel only), post the report
there as the run's last step, on **every** terminal outcome: deployed, failed,
waiting on a manual job, canceled, or tag already exists. Without a configured
webhook, skip this step and say so in one line.

- Read the URL into a variable from the config/secret helper the overlay names.
  Check its shape (`https://hooks.slack.com/services/...` for Slack), and never
  echo it, log it, or put it in a file, a commit or the transcript.
- Post with `../agent-alerts/scripts/notify.py` (the shared alert script; see
  the `agent-alerts` skill), passing the URL only as
  `NOTIFY_WEBHOOK_URL` in its environment. It builds the Slack Block Kit JSON
  with a serializer, so quotes and newlines in the tag message cannot break it,
  and prints `posted` or `failed: <status> <body>`. `--dry-run` prints the
  payload without posting. On failure, report it in the terminal; the terminal
  report still stands, and the run is not failed because of it.
- **The tag message goes in its own message.** On the Slack mobile app a
  long-press copies a whole message, and selecting part of one is fiddly. So
  pass it with `--copy "Tag message" "<text>"`: it is posted as a separate
  message holding only that text, right after the alert. Keep it free of
  labels and code fences, so a long-press copies exactly what gets pasted into
  the new-tag form.
- **The stage-deployment announcement is a draft, not text to copy.** When the
  overlay defines one (a channel and a template), create it as an unsent draft
  in that channel through the `agent-alerts` skill (`../agent-alerts/SKILL.md`,
  "draft, don't send"), with the real channel-wide mention and the commit
  linked. Copied text loses both on mobile: the mention arrives as plain text
  and the commit link drops. The alert says the draft is ready and carries an
  "Open <channel>, draft ready" button (`--announce-channel-name`,
  `--announce-channel-url` from the draft's channel link, `--announce-button`).
  The user sends it when they start the stage deployment. No watch is needed:
  nothing follows the send. If the channel already holds an unsent draft, or
  the draft can't be created, post the announcement as a `--copy` message
  instead and say why. The skill never posts the announcement itself.
- **The announcement names what is being deployed.** Fill it from the repo
  profile's "Stage announcement names" row, not from the tag alone. In a
  monorepo the tag (`<app>-v<version>`) already names the app; in a single-app
  repo the tag is a bare `v<version>`, so the line must also carry the
  service name the team uses in that channel (read it off real announcements
  there). An overlay template written from one repo's posts must not be
  applied unchanged to another repo: a bare `Initiating stage deployment for
  v1.2.3` reads as some other repo's release.

Message shape (Slack `mrkdwn`; links are `<url|text>`). The first line names
the skill that published it, so a reader of the channel can tell which run a
message came from:

```text
*monitor-dev-ci* · <repo short name>
<:white_check_mark: | :x: | :hourglass:> <app> <deployed to dev | dev deploy failed | waiting on a manual job>
Tag: `<tag>`  Merge commit: <commit url|<short sha>>
<New tag page — prefilled|<new-tag link>>   <Pipeline|<pipeline url>>
<one line on anything that didn't go cleanly, or nothing>
Ready to copy (one message each, below): 1. Tag message
Announcement for <channel>: draft ready
[Open <channel>, draft ready]
```
then one message with only the tag message.

`notify.py` writes the "Ready to copy" line itself for every `--copy` message,
so don't also pass it as a `--line`; the alert would show it twice.

On failure, the first line names the failed job and links its log, and the
new-tag link carries "don't create it until the deploy is fixed".

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
- Never print or store a notify webhook URL; it is a secret even though it can
  only post to one channel.

## Revision notes

- **16 October 2026** — quoted and braced `"${MERGE_SHA}:<path>"` in the version
  reads (zsh's `:a` modifier broke the unbraced form), and added the check for
  merges that land under this tag without their own version bump. One such
  merge had to be found by hand and added to the tag message.
- **16 October 2026 (night, later)** — reverted the stage-announcement proposal
  (step 6b) added earlier the same night. It came from a misread request: the
  ask was a review request when an MR opens, which belongs in its own skill, not
  in a skill that runs at merge.
- **16 October 2026 (night, last)** — the alert script moved to the shared
  `agent-alerts` skill (`../agent-alerts/scripts/notify.py`).
- **16 October 2026 (evening)** — the tag message and the stage announcement
  are now posted as separate copy-only messages after the alert (`notify.py
  --copy`), because on Slack mobile a long-press copies a whole message and
  picking part of one was hard.
- **16 October 2026 (evening, last)** — the stage announcement is now an unsent
  Slack draft in the deployment channel (through agent-alerts) instead of copy
  text: copying on mobile lost the channel-wide mention and the commit link.
  The tag message stays a separate copy message.
- **27 October 2026** — a single-app service run drafted the stage
  announcement as `Initiating stage deployment for v<version>`. The template came from monorepo
  posts, where the tag names the app; for a single-app repo it named nothing
  and read as a monorepo release. Added the "Stage announcement names" profile
  row and the rule that the announcement names the service. Also: don't pass
  the "Ready to copy" line yourself, `notify.py` adds it.
