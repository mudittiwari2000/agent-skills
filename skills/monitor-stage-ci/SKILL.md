---
name: monitor-stage-ci
description: After a release tag is cut (or a merge whose stage deploy is a manual gate), follow the change to STAGE — find the pipeline that deploys it, hand the user the exact manual job to click when stage is gated, watch the stage deploy jobs to a terminal state, confirm what is actually live (running version, or the deployed config read back from the live store), and scan the change's config dependencies for stage deploys nobody played. Runs post-deploy stage QA by default through a QA runner, moves the story to testing once stage is verified (QA never blocks the move), and offers a testing request for the QA testers, sent to the channel the user picks in the terminal or by replying to the stage alert. Use when the user says a tag is created / "monitor the stage pipeline" / "tell me when it's on stage" / "test it on stage", or invokes /monitor-stage-ci with a tag, MR IID or merge commit. Never plays, retries or cancels jobs without an explicit ask, and never touches prod.
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
- **QA is on by default.** Once stage is verified, post-deploy QA runs on stage
  through your QA-dispatch workflow (step 6). `--no-qa` skips it.
  `--qa=manual` runs your manual-QA workflow instead (see step 6 for when that
  is right). The overlay names both.
- **`--no-move`** (optional): with a Jira key, the story moves to the board's
  QA stage once stage is verified (step 7). This flag keeps it where it is.
- **`--no-request`** (optional): skip the testing-request offer (step 7b).

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
# GitLab job JSON can carry raw control characters, and a single read can come
# back empty or truncated. Parse leniently, skip a bad read, and give up only
# after five in a row, so one hiccup can't end the watch or pose as a failure.
read_jobs() { glab api "projects/$P/pipelines/$ID/jobs?per_page=100" 2>/dev/null | python3 -c 'import sys,json
try: d=json.loads(sys.stdin.read(),strict=False)
except Exception: sys.exit(3)
last=next((x.get("status","") for x in d if x.get("name")==sys.argv[1]),"")
bad=next((x["name"] for x in d if "stage" in x.get("name","") and x.get("status") in ("failed","canceled")),"")
print(f"{last}|{bad}")' "$LAST_STAGE_JOB"; }
miss=0; last=""; bad=""
for i in $(seq 1 720); do
  out=$(read_jobs)
  if [ -z "$out" ]; then miss=$((miss+1)); [ $miss -ge 5 ] && { last=unreadable; break; }; sleep 30; continue; fi
  miss=0; last=${out%%|*}; bad=${out#*|}
  [ -n "$bad" ] && break
  case "$last" in success|skipped|manual) break;; esac
  sleep 30
done
echo "last=$last failed=$bad"
```

`unreadable` means five reads in a row failed (API, auth or parse error).
Report it and check by hand; it is neither "still running" nor a failed
deploy. Re-list the jobs once the watcher exits rather than reusing its last
read.

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

## 5b. Re-read the story before testing or announcing

Requirements can change after the merge. Before running stage QA, moving the
story or asking anyone to test it, read the story's current acceptance criteria
and its comments since the merge (struck-through rules, a BA or PO asking for a
change). If a rule the release implements was withdrawn or changed, stage
tests the old behaviour: stop, report the change with the comment link, and
let the user decide (usually a follow-up ticket first). Never post a testing
request for behaviour the requirements no longer ask for.

## 6. Post-deploy stage QA (default on)

Unless `--no-qa` was given, call your
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

**Moving the story to the QA stage once stage is verified.** This writes to
a shared system, so the default comes from the overlay. Without an overlay,
ask the user before moving. Use your tracker's forward-only, idempotent
transition tool (the overlay names it and the target status), so a story
already at or past QA is left alone.

The move depends on the **release being testable**, not on the automated QA
verdict. Move when all of these hold:

- the stage deploy is verified (steps 3 and 4);
- step 5 found no pending dependency gap that affects the ACs;
- step 5b found no withdrawn or changed requirement.

Do the move as soon as these hold, and run QA after it (in the background when
it will take a while), so human QA can start without waiting for it. QA's
verdict never blocks or undoes the move. Report it instead, and make a bad
result impossible to miss:

- **PASS**: post the evidence; nothing else to do.
- **PASS_WITH_FOLLOWUP, INCONCLUSIVE, TOOL_UNAVAILABLE or a blocked run**:
  post what there is and name what is unverified in the Jira comment, the
  alert and the testing request.
- **FAIL**: lead the Jira comment and the alert with the failing AC and its
  evidence, and put it at the top of the testing request, so the QA testers
  check it first. The story stays in the QA stage. Moving it back is the
  user's call.

If any of the three conditions above fails, leave the story where it is, say
which one failed, and let the user decide. `--no-move` skips the move. After
the move, give the user the Jira key and the link
(`https://<your-tracker>/browse/<key>`) with the new status.

## 7b. Offer the testing request

Once the story is in the QA stage (or would have been, with `--no-move`), the
QA testers need to hear that it is ready. Unless `--no-request` was given:

1. **Draft the request** from the overlay's template. Without a template, use:
   a channel-wide mention, "<key> is on stage (<release unit>) and ready for
   testing", one or two one-line bullets on what to check (taken from the ACs),
   any unverified or failing AC from step 6 as its own line, and a `cc:` line
   for the story's QA owner when the overlay or the tracker names one.
2. **Let the user say where it goes, in either of two ways.** The run accepts
   whichever answer comes first.
   - **In the terminal:** offer the overlay's channel list for this story's
     team, plus "don't send", and let them pick another channel. Show the exact
     text with the destination name and id.
   - **As a reply to the step 8 alert:** the user replies in the alert's thread
     naming the channel and the person to cc, e.g. `#qa-channel @tester`. This
     is the route for when they are away from the terminal (see "Watching the
     alert thread" below).
3. **Treat the user's own choice as the grant, and only that.** A channel the
   user picked in the terminal, or named in their own reply, is a one-time
   grant for this one message. Record it wherever your messaging tool's
   allowlist lives, quoting the user's words. A reply from anyone else, or one
   that names no channel, grants nothing.
4. **Send only to that channel**, with the named person in the `cc:` line (the
   overlay's QA owner when the reply names nobody), through the messaging tool
   the overlay names. Read the posted message's link back and report it. On a
   denied or failed send, give the user the text to paste instead.

### Watching the alert thread

The alert goes out through a webhook, which returns no message id. So:

1. Right after the step 8 post, read the alerts channel with the messaging
   tool and take the newest message whose first line names this skill and this
   release unit. That message's timestamp is the thread to watch. If you can't
   find it, say so and fall back to the terminal question.
2. Schedule a recurring in-session check (every few minutes, for at most the
   overlay's watch window, two hours by default). Each check reads the thread's
   replies newer than the alert and keeps only those **written by the user**
   (the user id the overlay names).
3. On the first such reply, resolve what it names: a channel link or `#name`
   to a channel id, a user mention or name to a user id. When exactly one
   channel resolves, send (step 4 above), report the link in the terminal, and
   cancel the scheduled check. When the reply is ambiguous (no channel, two
   channels, an unknown name), send nothing. Report what was unclear in the
   terminal, and in a short follow-up alert when the webhook is configured,
   then keep watching for a clearer reply.
4. When the watch window ends with no reply, cancel the check and say so. The
   draft in the alert is still there to copy.

The scheduled check lives only as long as this agent session. Tell the user
that when the watch starts, so they don't reply to the thread after the session
has closed and expect a send.

The same draft goes into the step 8 alert, so the user can send it from there
when they are not at the terminal.

## 8. Notify (when a notify webhook is configured)

The stage watch and QA can take a long time. When the overlay names a
notification webhook (for example a Slack incoming webhook that can post to one
private channel only), post the step 7 report there as the run's last step, on
**every** terminal outcome: on stage and verified, stage deploy failed, waiting
on a manual job, a dependency gap found (step 5), QA finished (pass, follow-up
or fail), or stopped because the requirements changed (step 5b). Without a
configured webhook, skip this step and say so in one line.

Handle the URL and the post exactly as `monitor-dev-ci` step 6 does: read it
into a variable from the overlay's config/secret helper, check its shape, never
print or store it, build the JSON with a serializer, and check for `200` / `ok`.
A failed post is reported in the terminal and never fails the run.

When step 7b drafted a testing request, add it to the alert as the
announcement call to action (`notify.py --announce-text` with the draft,
`--announce-channel-name` and `--announce-channel-url` for the channel the
overlay suggests first): plain `mrkdwn` plus an "Open <channel>" button, as
`monitor-dev-ci` does for its stage announcement. The webhook only reaches the
alerts channel, so the user copies the text from there. Mentions in the draft
must stay plain text (`@here`, not `<!here>`) so the alerts channel is not
pinged.

When QA runs after the move, send a second alert when it finishes, with its
verdict and evidence link.

Message shape (Slack `mrkdwn`). The first line names the skill that published
it, so it can't be mistaken for a `monitor-dev-ci` message:

```text
*monitor-stage-ci* · <repo short name>
<:white_check_mark: | :x: | :hourglass: | :warning:> <release unit> <on stage | stage deploy failed | waiting on <job> | blocked: <reason>>
Stage jobs: <job> <result>, … · <Pipeline|<pipeline url>> · finished <HH:MM UTC>
Live check: <version match | KVS entries N, diffs M | job result only>
<Dependency gaps: <job link> … | none>
<Story: <key> → <QA stage> | not moved: <reason>>
<QA: <verdict> — <one line> · <QA evidence|<tracker comment url>> | QA running | QA skipped (--no-qa)>
<Testing request: draft below, suggested channel <name>; reply here with `#channel @person` to send it | sent to <name> | not sent>
<Next: <the one thing the user should do now>>
```

## Guardrails

- Never announce a release for testing without re-reading the story's current ACs and post-merge comments (step 5b).

- Never play, retry, cancel or re-run a job without an explicit ask, and then
  only the named job.
- Never send the testing request to a channel the user did not pick in this
  run, in the terminal or in their own reply on the alert thread, and never
  without recording the grant your messaging tool requires. A reply from anyone
  else grants nothing.
- Never let a failing QA result go unmentioned because the story moved anyway:
  it leads the Jira comment, the alert and the testing request.
- Never touch prod jobs, even when they sit in the same pipeline.
- Never print or store a notify webhook URL (step 8).
- Never report "on stage" from an overall-green pipeline. Key off the last
  stage job in the chain, and prove the live state where you can (step 4).
- Never print secrets from your config/secret store or put them in artifacts.
- Never mark an AC as passed when the stage environment it ran on was missing
  one of the change's dependencies (step 5).

## Revision notes

- **16 October 2026** — the step 3 watcher now parses leniently and tolerates
  up to five bad reads before giving up with `unreadable`. One empty API read
  had set the "failed job" variable to an error marker, ending the watch while
  the deploy was still running fine.
- **16 October 2026 (later)** — QA is now on by default (`--no-qa` to skip) and
  no longer gates the move to the QA stage. The move depends on the release
  being testable (deploy verified, no dependency gap, requirements unchanged),
  and a bad QA result is reported prominently instead. Added step 7b: draft a
  testing request, let the user pick the channel, send only there, and carry
  the draft in the alert as a copyable call to action. The user can also pick
  the channel and the person to cc by replying in the alert's thread: the run
  finds the alert, watches its thread with a scheduled in-session check, and
  sends on the user's own reply.
