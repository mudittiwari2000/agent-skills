---
name: monitor-stage-ci
description: After a release tag is cut (or a merge whose stage deploy is a manual gate), follow the change to STAGE — find the pipeline that deploys it, hand the user the exact manual job to click when stage is gated, watch the stage deploy jobs to a terminal state, confirm what is actually live (running version, or the deployed config read back from the live store), and scan the change's config dependencies for stage deploys nobody played. Optionally hands off to a QA runner for post-deploy stage QA and to the issue tracker for evidence and the testing transition. Use when the user says a tag is created / "monitor the stage pipeline" / "tell me when it's on stage" / "test it on stage", or invokes /monitor-stage-ci with a tag, MR IID or merge commit. Never plays, retries or cancels jobs without an explicit ask, and never touches prod.
version: 0.1.0
argument-hint: <tag | MR IID | merge SHA> [--jira <ISSUE-KEY>] [--qa[=manual]] [--no-move]
metadata:
  tags: [CI, GitLab, Stage, Deployment, Release]
  related_skills: [monitor-dev-ci]
---

# Monitor a change through to stage

`monitor-dev-ci` follows a merge to **dev** and hands back the release tag.
This skill picks up from there. It follows that tag, or a merge whose stage
deploy is gated, to **stage**, then proves what is live. The two share the
repo-profile layout, so they can later merge into one skill that takes the
environment as a parameter. A release workflow's "deploy or prepare deployment
evidence" step can call this skill for the CI part (the overlay names it).

It watches and reports. The user clicks manual gates unless they explicitly ask
you to. A stage deploy is shared: other engineers see it, and the user may want
to warn the team first.

## Organisation overlay (optional)

Before starting, look for `${AGENT_SKILLS_OVERLAY:-~/.config/agent-skills/overlay}/overlays/monitor-stage-ci/profile.md`.
If it exists, read it, and any file it points to, before doing anything else.
It supplies what this skill leaves as placeholders (repo profiles, tracker and
CI tool names, environment access, house conventions) and may add steps.
For facts about the organisation the overlay wins; for method and guardrails
this file wins. Without an overlay, discover the values from the repo and the
user, and record what you learn where the skill says to.

## Inputs

- **Release unit** — one of:
  - a release **tag** (e.g. `v1.2.3`, `<app>-v1.2.3`), the usual case;
  - an **MR IID** or **merge SHA**, for things that deploy from the default
    branch with a manual stage gate (config stores such as the CloudFront KV
    store).
- **Repo**: taken from the MR or tag link, or from the checkout's `origin`. `$P`
  is the URL-encoded project path. Use `glab api`, which is authenticated as the
  user.
- **Jira key** (optional): the story to update once stage is verified.
- **`--qa`** (optional): run post-deploy QA on stage through your QA-dispatch
  workflow. `--qa=manual` runs your manual-QA workflow instead (see step 6 for
  when that is right). The overlay names both.
- **`--no-move`** (optional): with a Jira key and a fully passing QA, the story
  may move to the board's QA stage (step 7). This flag keeps it where it is.

## Repo profiles

Everything that varies by repo lives here. For a repo not listed, read the
values off its latest tag pipeline (step 1), use them, and add a row
afterwards (to the overlay's table when an overlay is installed). Re-read the
live job list on every run anyway, because job names drift.

| | `<service>` | `<monorepo>` app | `<monorepo>` config store (CloudFront KVS) |
|---|---|---|---|
| Project path | `<group>/<project>` | `<group>/<project>` | same |
| Stage runs from | the **tag** pipeline | the **tag** pipeline | the default-branch merge pipeline → bridge job → child pipeline |
| Stage gate | **manual** first stage job | automatic after tag validation | **manual** per-brand KVS stage job (dev runs automatically) |
| Stage job chain | `<push>` → `<deploy>` → `<post-deploy>` | `<build>` → `<deploy>` → `<cdn invalidation>` | `<kvs stage job>` |
| "On stage" means | last job in the chain success | deploy success, then CDN invalidation | job success **and** the live key reads back equal to the repo file |
| Live check | version/health endpoint, or the job result as the evidence | the app's running version where exposed; otherwise the job result | `aws cloudfront-keyvaluestore get-key` (step 4) |
| Prod jobs in the same pipeline | `<prod jobs>` (never touch) | `<prod jobs>` (never touch) | `<prod kvs job>` (never touch) |

`<app>` in job names is usually the app name with dashes replaced by
underscores. `<brand>` is the config store's brand or tenant folder.

## 1. Find the pipeline that deploys to stage

```bash
# tag-driven
glab api "projects/$P/pipelines?ref=$TAG&per_page=5" | jq -r '.[] | "\(.id) \(.status) \(.source)"'
# default-branch-driven (config stores): the merge pipeline, then its bridge's child
glab api "projects/$P/pipelines?sha=$MERGE_SHA&ref=$BRANCH&per_page=5" | jq -r '.[] | "\(.id) \(.status)"'
glab api "projects/$P/pipelines/$ID/bridges?per_page=100" | jq -r '.[] | "\(.status)\t\(.name)\t\(.downstream_pipeline.id)"'
# then list jobs
glab api "projects/$P/pipelines/$ID/jobs?per_page=100" | jq -r '.[] | "\(.status)\t\(.stage)\t\(.name)\t\(.id)"'
```

A pipeline whose overall status is `manual` (or a parent still `running` weeks
later) is waiting on a click. That is normal, not stuck.

## 2. Gate: hand over the exact job, don't click it

If the first stage job is `manual`:

- Give the user the **pipeline URL** and the **job name** to play (plus the job
  URL `https://gitlab.com/<path>/-/jobs/<id>`). Say what it changes and what it
  does not ("stage only; the prod jobs behind it stay untouched").
- Play it yourself **only** when the user explicitly says so, and play only
  that job. When the user says they'll click it, start the watcher (step 3)
  straight away, so the moment they click is picked up without another prompt.

## 3. Watch to a terminal state

Run one background watcher that exits on **every** terminal state, so a
failure can't look like "still waiting":

```bash
for i in $(seq 1 720); do
  J=$(glab api "projects/$P/pipelines/$ID/jobs?per_page=100")
  last=$(echo "$J" | jq -r --arg j "$LAST_STAGE_JOB" '.[]|select(.name==$j)|.status')
  bad=$(echo "$J" | jq -r '.[]|select((.name|test("stage")) and (.status=="failed" or .status=="canceled"))|.name' | head -1)
  [ -n "$bad" ] && break
  case "$last" in success|skipped) break;; esac
  sleep 30
done
echo "last=$last failed=$bad"; echo "$J" | jq -r '.[]|select(.name|test("stage"))|"\(.status)\t\(.name)\t\(.finished_at)"'
```

Key off the **last job in the profile's stage chain**, not "deploy looks
green". For example, a parameter-update job can run after the deploy job. On
failure, fetch the trace tail
(`glab api "projects/$P/jobs/$JOB/trace" | tail -60`) and report it. Never
retry.

## 4. Prove what is live

A green job only says the pipeline ran. Confirm that the running stage matches
the release:

- **Service with a version/health endpoint**: request it and compare the
  version with the tag.
- **Config store (CloudFront KVS)**: read the key back and compare it with the
  repo file at the deployed commit. Use the AWS profile the overlay names (or
  ask the user). The KVS data-plane API is global and is called in
  `us-east-1`, whatever the app's region.

  ```bash
  aws cloudfront list-key-value-stores --query 'KeyValueStoreList.Items[].[Name,ARN]' --output text | grep "<store name for this brand and stage>"
  aws cloudfront-keyvaluestore get-key --kvs-arn "$KVS_ARN" --key "$KEY" --region us-east-1 --query Value --output text
  ```

  Parse both sides and compare them as data (sets or maps), not as strings.
  Report the entry count and any key whose value differs.

- **Neither available**: say plainly that the job result is the only evidence.

If AWS SSO has expired, give the login command (`aws sso login --sso-session
<session>`, with the session the overlay names) and carry on with the checks
that don't need it.

## 5. Scan the change's dependencies for unplayed stage deploys

This is the step that catches real problems. A change on stage often depends on
config shipped by **another** MR, and that MR's manual stage job may never have
been played. Its dev deploy ran automatically, so dev looks fine and hides the
gap. (Seen in practice: a value had been in the repo's edge config file for
days, but its manual stage KVS job was never played, so stage routed a class of
users with the wrong entitlement while the API, already on stage, treated them
correctly.)

For each config the feature reads (edge KV keys, parameter-store values,
feature-flag definitions):

1. Read the **live** stage value (step 4) and compare it with the repo.
2. On a mismatch, find the commit that introduced the missing value
   (`git log -S'<value>' -- <file>`), its merge pipeline, and the child
   pipeline's stage job. It will usually be `manual`.
3. Hand that job to the user exactly as in step 2. Don't play it without an
   explicit ask. The user may want to tell the team first.

## 6. Optional: post-deploy stage QA

With `--qa`, or when the user asks to "test it on stage", call your
QA-dispatch workflow with the stage URL as the target. Its runner is a
**fresh** QA-runner subagent, never this context.

**Which QA skill.** The QA-dispatch workflow is the default, and it is chosen
on purpose, not as a fallback for a missing manual-QA workflow. This skill's
job is "did the AC hold on the deployed release, with proof I can post", and an
unattended dispatcher fits that: it returns a structured per-AC QA result that
your tracker's evidence tool can post, and works for any repo profile. A
manual-QA workflow is a different job, a QA-manager sign-off of a whole
ticket, usually with interactive gates and its own tracker writes. So do
**not** pick it just because it is installed. Use it only when the user asks
for it by name (`--qa=manual`, "run manual QA"), the repo supports it, and the
user is present for its gates. In that case hand it the stage URL and Jira
key, skip the evidence-posting tool (its report is the evidence), and still do
steps 4 and 5 here. The overlay describes the concrete trade-offs.

**Environment access.** Give the runner the environment access your overlay
describes: where the stage base URL and test users come from, how to get past
any auth or bot-protection gate on stage, and how to load config without
printing secrets. Without an overlay, ask the user. In any case provide the
runner:

- the stage base URL and the brand or tenant;
- how to get entitled test users (never print credentials);
- how to pass any stage-only bypass, scoped to the stage host only (a request
  route for that host, never a global extra header);
- one test user per tier or state the ACs name. A story about signed-out
  visitors needs no user, only a cookie-less context plus any bypass.

Test each layer separately (edge routing, rendered UI, API data), because one
can pass while another is broken.

When the runner returns, check its written claims against its own artifacts
before posting. A runner's summary has claimed a section was empty while its
own DOM capture and page HTML showed it populated. Fix the written claim to
match the data, keep the runner's original result beside the corrected one,
and say so in the report.

If the evidence-posting tool reports the result as stale, the story's AC text
changed while the run was in progress. Read the current ACs. When the changes
don't alter what was tested, rebuild the AC snapshot provenance from the
current description using the tracker integration's own client (the overlay
names it) with a new run id, repost, and say in the Jira comment that the ACs
were edited after the run. When they do alter it, run QA again. Anything step 5
found still pending is either fixed first or reported as blocked for the users
it affects, never as a pass.

## 7. Report, and Jira if asked

Give the user, in plain text (no blockquotes):

- stage status: each stage job with its result, the pipeline URL, and the time
  the last job finished;
- the live check result (version match, or KVS entry count and any
  differences);
- any dependency gaps from step 5, each with its pipeline and job links;
- the QA verdict and anything that failed, when step 6 ran.

With a Jira key, post the evidence through your tracker's tools (a comment,
plus the structured QA-evidence post for the QA result).

**Moving the story to the QA stage once QA has passed fully.** This writes to
a shared system, so the default comes from the overlay. Without an overlay,
ask the user before moving. Use your tracker's forward-only, idempotent
transition tool (the overlay names it and the target status), so a story
already at or past QA is left alone. "Passed fully" means all of these hold:

- step 6 ran and its QA result is a full, completed pass (not a pass with
  follow-ups, not inconclusive, not tool-unavailable), and any QA gate check
  your tooling provides passes;
- every AC is in the checked set, and none is not-verified, deferred or
  downgraded;
- the evidence post succeeded and was not stale;
- the runner's written claims were checked against its artifacts (step 6);
- step 5 found no pending dependency gap that affects the ACs;
- the stage deploy is verified (step 3 and step 4).

If any of these fails, leave the story where it is, say which one failed, and
let the user decide. `--no-move` skips the move even when QA passed fully.
Without `--qa` there is no QA result, so there is nothing to move on: report
and stop. After the move, give the user the Jira key and the link
(`https://<your-tracker>/browse/<key>`) with the new status.

## Guardrails

- Never play, retry, cancel or re-run a job without an explicit ask, and then
  only the named job.
- Never touch prod jobs, even when they sit in the same pipeline.
- Never report "on stage" from an overall-green pipeline. Key off the last
  stage job in the chain, and prove the live state where you can (step 4).
- Never print secrets from your config/secret store or put them in artifacts.
- Never mark an AC as passed when the stage environment it ran on was missing
  one of the change's dependencies (step 5).
