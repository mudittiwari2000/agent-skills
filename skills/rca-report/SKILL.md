---
name: rca-report
description: Investigate a production incident or user-reported bug to its root cause and write it up as an RCA (root cause analysis) document. Use when the user asks for an "RCA", "root cause", "post-mortem", "why is X broken / empty / 404ing", shares screenshots of a broken page and wants it explained, or asks to check an issue across dev / stage / prod. Covers a two-phase access gate (non-prod first, then prod; prod access is required before an RCA is written), a reproduce-isolate-trace-date protocol, evidence standards, the traps that waste time or produce a wrong cause, and the RCA document shape. The output goes to a Claude Docs artifact by default; a Confluence page (location and title proposed and confirmed with the user first) or a Markdown file on request. Organisation specifics (environment gates, data sources, config helper, Confluence conventions) come from an optional overlay.
---

# Root cause analysis

The job is a cause that is **proven, dated and actionable**, not a plausible
story. An RCA fails in one of three ways: it names the wrong cause because a
hypothesis was announced before it was tested; it names a real mechanism but
not *what changed*; or it is right but no one can check it. Every step below
exists to prevent one of those.

Keep a running log in the scratchpad (`rca-log.md`) as you go: each step, what
it showed, and any mistake you made. The log feeds the Evidence section, and
the mistakes feed improvements to this skill.

`<skill-dir>` below means the directory that holds this SKILL.md, wherever
your harness installed it. The scripts in `<skill-dir>/scripts/` need their
Node dependencies installed once: `cd <skill-dir>/scripts && npm ci`
(`node_modules` is not committed). `md2cf.py` needs Python 3 and the
`markdown` package (`markdown_py` on the PATH).

## Organisation overlay (optional)

Before starting, look for `${AGENT_SKILLS_OVERLAY:-~/.config/agent-skills/overlay}/overlays/rca-report/profile.md`.
If it exists, read it, and any file it points to, before doing anything else.
It supplies what this skill leaves as placeholders (repo profiles, tracker and
CI tool names, environment access, house conventions) and may add steps.
For facts about the organisation the overlay wins; for method and guardrails
this file wins. Without an overlay, discover the values from the repo and the
user, and record what you learn where the skill says to.

## 0. Inputs and the access gate

### Inputs

| Input | Default | Ask? |
| --- | --- | --- |
| The prod symptom (URL, screenshots, who reported it) | none | Yes, if missing |
| Output target | `artifact` (Claude Docs artifact) | Only if the user mentions Confluence or a file. Other values: `confluence`, `markdown` |
| Environments | prod (required) + develop/stage | No |

### Access: two phases, prod is the bare minimum

An RCA explains a **prod** bug, so the cause must be confirmed in prod's own
data and config. Public-site checks (curl, public search keys) can back up a
prod claim, but can't stand in for prod account access when the cause lives
in prod data, config or a store. Non-prod access is needed for the deep dive
and for proving the fix.

1. **Check everything at the start, in one pass.** Load your config/secret
   helper if you have one (the overlay names it and says how it maps account
   names to AWS profiles), then:
   ```bash
   # AWS_PROFILE_NONPROD / AWS_PROFILE_PROD: the SSO profile names for each account.
   for acct in nonprod prod; do
     P=$([ $acct = prod ] && echo "${AWS_PROFILE_PROD:-}" || echo "${AWS_PROFILE_NONPROD:-}")
     [ -n "$P" ] || { echo "$acct: profile unknown"; continue; }
     aws sts get-caller-identity --profile "$P" --query Account --output text >/dev/null 2>&1 \
       && echo "$acct: connected" || echo "$acct: not connected ($P)"
   done
   ```
   Also check: log search and its retention, Jira, `git fetch` of the repos, and
   your config helper's health or list command, if it has one (a stale config
   copy is a common trap).
2. **Ask once, in one message, for everything that's missing.** Say what each
   account is for: prod to confirm the cause in prod data, non-prod to trace
   the cause and verify the fix. Give the exact
   `! aws sso login --profile <p>` command. If the prod profile is unknown,
   ask for the profile name and account id, and record them where your config
   helper keeps account settings (the overlay says where).
3. **Phase 1, non-prod:** start once non-prod is connected. Run steps 1–4
   against develop and stage, plus read-only public checks of prod.
4. **Phase 2, prod:** before starting, re-check prod access. Re-check it too
   before any AWS step after a gap: SSO sessions expire (daily, in practice),
   and a follow-up on another day will find both profiles logged out. If it's still not
   connected, **stop and wait**. Tell the user what phase 1 found and exactly
   which claims are waiting on prod access. Don't write the RCA yet.
5. **The gate:** the RCA is written only after the prod evidence is in. The one
   exception: the user explicitly says to go ahead without prod access. Then
   title the document "Preliminary investigation (prod unverified)", not
   "RCA", and mark every prod-dependent claim unverified.

Secrets: fetch single values with your config/secret helper (`$(<helper> get …)`)
into variables. Never read a whole config file into the transcript. If the user
gives a new config path, register it with the helper rather than reading it
directly.

## 1. Reproduce exactly what the user saw

- Read the screenshots closely: the exact URL, the empty-state wording, which
  neighbouring widgets *do* work (a working sibling rules out a total outage).
- Request the **exact URL** the way the user's client does. `curl -sL` follows
  redirects and can hide the real first hop. Use `curl -s -D - -o /dev/null`
  to see each hop, then follow it yourself. A browser's client-side navigation
  (RSC) can take a different path from a hard load.
- Reproduce on **every environment** (dev, stage, prod). An issue on all
  three points to shared data or config; one on prod only points to a prod
  deploy, prod data or a prod flag.
- Always run a **control**: a sibling that works (another tag, category or
  brand). The difference between the two is where the cause is.

## 2. Trace the path from the UI to the data

Follow the empty-state string, then the component, service, query and data
source. Read the real code on `origin/main`; don't guess from names.

- Find what the component fetches, and call that layer directly (API route,
  GraphQL, index), separately from the UI. Confirm the route prefix from the
  code (basePath, assetPrefix, trailing slash) before calling it.
- Tell "the query errored" apart from "the query succeeded and returned
  nothing". `200` with `posts: 0, error: false` is a *data* question, not an
  outage.
- Query the data source **without the app** (the database, CMS or a search
  mirror). If you use a mirror or proxy, label it one; it can be stale.
- Before claiming something **does not exist**, enumerate the whole set, not a
  top-N facet. A distinct-value count lets you prove the list is complete.

## 3. Find the last known good, then what changed

A mechanism is not a root cause. "The code queries tag X and tag X is empty"
describes the failure; the cause is **what made X empty, and when**.

1. **Did it ever work?** Look for evidence it worked: the original ticket's QA
   comments, Wayback Machine captures (`web.archive.org/cdx/search/cdx?url=…`),
   old logs, screenshots. If you skip this, "it was always broken" and "it
   regressed" look identical.
2. **Last known good / first known bad.** Pin both with dated evidence.
3. **Diff the code across that window** (`git log --since … -- <paths>`). If
   the code didn't change, the cause is data or config, so look there.
4. **Search the change record for the data itself, not just git.** Jira
   tickets that touch the entity (the term, table, index, redirect or flag), CMS
   migrations, KVS or redirect stores, feature-flag history. Search by
   *entity* ("the tag", "taxonomy", "redirect") and by label
   (the CMS's name, `migration`), not only by the symptom.

Time-box each tool: if about 3 queries against one source (e.g. logs) haven't
produced the signal, write down why, and switch sources.

## 4. Confirm, and separate the failures

- One incident often holds **several independent faults** (e.g. data removed
  + redirect to a page that doesn't exist + a stale nav link). List each one
  with its own evidence; don't fold them into one story.
- Check every claim in the tickets and Slack against the code or data. A
  ticket's explanation ("it'll clear once the queue drains") is a hypothesis
  until the code or data backs it up, and it is often wrong.
- **Don't say "this is the root cause" until the last-known-good check is
  done.** Say "leading hypothesis" until then. If the user's view differs
  from yours, check it against the evidence; don't just adopt it.
- When the user brings in someone else's finding, cross-check it against your
  own evidence and say what it confirms, adds or contradicts.

## 4b. Settle the fix, and measure it before recording it

The fix is the team's decision, not the investigator's. Propose one, but
write into the RCA (and any ticket) the fix the user confirms, with the date
it was decided.

- **Run the chosen fix's query against prod data before you record it**, using
  exactly what the code will send. A fix can be right in principle and still
  wrong in practice. In one incident, the decided query matched a single prod
  record, because a data migration had added the new value without updating
  the field the query filtered on. The RCA and the ticket then recorded that
  effect as accepted, rather than it surprising someone after deploy.
- **Confirm a surprising number with a second, independent source** before
  reporting it: e.g. the CMS's own API plus a search-index mirror that the CMS
  feeds separately.
- **Put the evidence in your message, then ask.** A question that carries its
  numbers only inside the question gets rejected so the user can ask for
  clarification. That happened twice. Give the table first, then a short
  plain-text question.
- **Record scope boundaries explicitly.** When the user accepts a known
  remaining break (e.g. "the page 404s until another team ships it"), write
  down that it's out of scope, who owns it, and the date it was accepted.

## 5. Write the RCA

Only after the phase-2 gate in step 0. The content shape is the same for every
output target:

| Section | Contents |
| --- | --- |
| Lead (no heading) | 3–4 sentences: what broke, the cause, whether content/data is safe, what the fix is |
| Impact | Table: surface · what the user sees · per-env status + since when |
| Timeline | Table, newest first: date · event. Mark **when each env broke** and the moments it could have been caught |
| Root cause | Numbered faults + a mermaid flowchart of the failure path + a table of the code/config locations involved |
| Contributing factors | Why it shipped and why no one noticed: process, detection, design debt. One bullet each |
| Evidence | Table: claim · how verified (the command or query) · env · result. Label proxy evidence |
| Fix | Numbered changes with file paths, what *not* to do (e.g. don't roll back the migration), a prerequisite check, and a `- [ ]` verification checklist per env |
| Prevention | `- [ ]` actions, each one tied to a contributing factor |
| Open questions | Anything unverified, with why and what would settle it |
| Sources | Tickets, captures, threads actually opened |

Style: short sentences, specifics (counts, dates, file:line), no names
blamed; refer to roles and tickets. Don't file Jira tickets or post to Slack
unless asked.

An RCA is a long-lived record, so write it for a reader who never saw the
investigation and may read it a year later:
- Give every date its year, including in tables ("24 Sep 2026", never "24 Sep").
- Don't use relative time ("this week", "today", "recently", "still",
  "currently"). Anchor state to an as-of date ("open as of 25 September 2026").
- Don't refer to the conversation or the drafting ("as you suggested",
  "written for this", "my local setup"). Define internal names on first use.
- Before publishing, search the draft for relative-time words and for dates
  missing a year, and fix every hit.

Draft the whole RCA as Markdown in the scratchpad first (`rca.md`). Every
target publishes from that one draft.

### Target `artifact` (default)

`Artifact quickstart` (intent `document`), publish with the Docs `type_url`,
then fill through the Claude Docs connector, one section per call. Give the
link, say it's private until they share it, and summarise the cause in two or
three lines.

### Target `markdown`

Write `rca.md` where the user says (ask for the path if they didn't give one).

### Target `confluence`

A Confluence page is public to the org at once and **can't be deleted without
admin rights**. So the location and title are proposed, shown in full and
approved before anything is created.

1. **Propose the location.** Read the saved defaults (space key, parent page
   id, parent path, title pattern) from the overlay or your config helper; with
   none saved, ask the user for a parent page.
   Check the parent still exists, and read its five newest children to confirm
   the title convention is still followed:
   ```bash
   # CONFLUENCE_BASE_URL: the wiki base, e.g. https://<site>.atlassian.net/wiki
   B=$CONFLUENCE_BASE_URL; A="$JIRA_USER_EMAIL:$JIRA_API_TOKEN"
   curl -s -u "$A" -G "$B/rest/api/content/search" \
     --data-urlencode "cql=type=page AND parent=<parent_id> ORDER BY created DESC" \
     --data-urlencode limit=5 --data-urlencode expand=history \
     | jq -r '.results[] | "\(.history.createdDate[:10]) | \(.title)"'
   ```
   Build the title from the pattern: the date the incident **started in
   prod**, then the ticket that **tracks the incident or its fix** (the log's
   convention; the ticket that caused it goes in the header table), then a
   short symptom. For example `2026-01-15 - PROJ-123 - Category news list
   empty`. No customer names or email addresses in titles.
2. **Look for a clash.** Search for the same title under the parent. If it
   exists, the choice is to update that page or pick a new title, never to
   silently create a duplicate.
3. **Confirm with the user** (`AskUserQuestion`). Show the full path,
   `<SPACE> > … > <parent> > <title>`, and the account that will author the
   page. If the configured token authenticates as a shared integration account
   rather than the user (the overlay names it), say so. Options: the proposal (Recommended), a different parent,
   a different title. They can also type their own. **Create nothing until
   they approve.**
4. **Convert, validate and publish.** Make these changes to the draft first:
   - **Credit the author.** When the API token belongs to a shared integration
     account, the page must name and @-mention the real author. Put the
     author's storage-format mention
     (`<ac:link><ri:user ri:account-id="…" /></ac:link>`, which `md2cf.py`
     builds from `CONFLUENCE_AUTHOR_ACCOUNT_ID`) in an info panel at the top
     ("Author: … Published through the <integration-account> account on behalf
     of the author").
   - **Add the log's labels.** If the space keeps an incidents log whose parent
     page lists children with a label macro (e.g. `label = "incidents"`), a
     page without that label doesn't appear in the log. Pass `metadata.labels`
     = the required labels, as a space-separated `RCA_LABELS` (e.g.
     `incidents rca`; the overlay names the real ones). Without an overlay,
     read the labels off the log's newest pages.
   - **Match the log's template.** Add the log's header table first, with the
     rows the overlay lists (without one, copy them from the log's newest
     page). A typical set: incident date, incident ticket, caused by,
     reported, incident status, RCA status, RCA author. Write the ticket rows as `@@JIRA:<KEY>@@`, which becomes the
     same live Jira macro the log's own pages use, so the page always shows
     each ticket's current lane. In the incident-status row, say how to update
     it ("update this row when <KEY> reaches Done"), and anchor the current
     state to a date.
   - **Render the diagram to an image.** Many Confluence sites have no Mermaid
     macro (the overlay records whether yours does), so a Mermaid block shows
     as raw source. After creating the page:
     1. Render: `node <skill-dir>/scripts/render_mermaid.mjs diagram.mmd diagram.png`.
        The first time, run `npm ci` in `<skill-dir>/scripts/` and install a
        headless Chromium (`npx playwright-core install --only-shell chromium`
        from that folder). The script finds it in `PLAYWRIGHT_BROWSERS_PATH`
        (default `~/.cache/ms-playwright`), or takes `CHROMIUM_EXECUTABLE`. If
        Chromium fails on a missing shared library (e.g. `libasound.so.2`),
        point `LD_LIBRARY_PATH` at a userspace copy. The overlay may have a
        "Rendering in a browser" section for your machine.
     2. **Look at the PNG** before using it. Check that every box is readable,
        URLs aren't broken mid-word and it isn't tiny.
     3. Attach it: `POST /rest/api/content/<id>/child/attachment` with header
        `X-Atlassian-Token: no-check` and multipart `file=@diagram.png`.
     4. Re-run `md2cf.py` with the PNG name as its 4th argument, then `PUT` the
        page. The converter swaps each Mermaid code block for the image,
        followed by a collapsed "Diagram source (Mermaid)" expand holding the
        source, so the diagram stays editable.

     Put a sentence before the image that says what it shows, including what
     each colour means if you use `classDef`.
   - **Replace charts with tables.** A Claude Docs chart does not survive the
     Markdown export (it becomes "[embedded content]"), so give its numbers as
     a table.

   Then convert, validate without creating anything, and POST:
   ```bash
   # @@AUTHOR_PANEL@@ and @@MENTION@@ tokens in the draft become the info panel and the mention;
   # "- [ ]" lists become <ac:task-list>, fenced code becomes the code macro.
   # Optional 4th argument: PNG attachment names (from render_mermaid.mjs) that replace the mermaid blocks in order.
   # Env: CONFLUENCE_AUTHOR_ACCOUNT_ID (for @@MENTION@@ / @@AUTHOR_PANEL@@),
   # CONFLUENCE_JIRA_SERVER and CONFLUENCE_JIRA_SERVER_ID (for @@JIRA:KEY@@; copy them
   # from an existing page's Jira macro). The overlay gives the commands that set them.
   python3 <skill-dir>/scripts/md2cf.py rca.md rca.html \
     'Author: @@MENTION@@ (<name>). Published through the <integration-account> account on behalf of the author.' \
     diagram.png
   jq -n --rawfile v rca.html '{value:$v,representation:"storage"}' \
     | curl -s -u "$A" -H 'Content-Type: application/json' --data-binary @- \
       "$B/rest/api/contentbody/convert/view" | jq -r 'if .value then "valid" else .message end'
   jq -n --arg t "<title>" --arg s "<space>" --arg p "<parent_id>" --arg l "${RCA_LABELS:-}" --rawfile v rca.html \
     '{type:"page",title:$t,space:{key:$s},ancestors:[{id:$p}],
       body:{storage:{value:$v,representation:"storage"}},
       metadata:{labels:[$l|split(" ")[]|select(.!="")|{prefix:"global",name:.}]}}' \
     | curl -s -u "$A" -H 'Content-Type: application/json' --data-binary @- "$B/rest/api/content" \
     | jq -r '.id // .message, ._links.webui // empty'
   ```
5. **Read it back** (`GET /rest/api/content/<id>?expand=body.storage,ancestors,metadata.labels`).
   Check the parent, the labels, every `<h2>`, the table count, and that the
   mention's `ri:account-id` is present. Then give the user the page URL.
   Update the saved default location only if the user says the new location
   should become the default.
6. **From now on, Confluence is the canonical copy.** Say so, and stop editing
   the artifact. For a later edit, change the on-disk Markdown, re-convert it,
   and `PUT /rest/api/content/<id>` with `version.number` set to the current
   version + 1. Check first that nobody else has edited the page since
   (`version.by`); if someone has, merge their changes rather than overwrite
   them.

### Linking the RCA to the ticket

"Attach the RCA to the story" means **link the Confluence page**. Don't
upload a PDF unless the user asks for a file. A PDF is a frozen copy that goes
stale as the page is edited, and the Claude Docs PDF export prints Mermaid
diagrams as raw source.

- **Link both ways.** The link matters beyond navigation: whoever moves the
  ticket between lanes can open the RCA from it and update the RCA's incident
  status. The page, for its part, shows the ticket's live lane through the
  Jira macro in its header.
  - Ticket to page: a remote link,
    `POST $JIRA/rest/api/2/issue/<KEY>/remotelink` with
    `{globalId, relationship:"RCA", object:{url, title}}`. In the ticket's own
    text, point at "the linked RCA", not "the attached RCA".
  - Page to ticket: `@@JIRA:<KEY>@@` in the header table. Do the same for
    every prevention-action ticket once it exists.
- **Only if a file is requested:** export from Claude Docs (`export`,
  format `pdf`). The PDF is too large to return in the tool result, so it's
  saved under `tool-results/`; decode that file's `bytes_b64` field. Upload it
  with your tracker's attachment-upload tool (the overlay names it), or
  `POST $JIRA/rest/api/2/issue/<KEY>/attachments` with header
  `X-Atlassian-Token: no-check` and multipart `file=@rca.pdf`.
- **Re-read the ticket immediately before any update.** Another session or an
  automated delivery workflow may have added evidence declarations,
  workflow-owned sections, labels or attachments since you last looked. A
  structured story-update tool that re-renders the whole description from a
  schema silently deletes any section its schema has no field for. If the ticket
  carries content the schema can't express, don't re-render it. Ask the user,
  or limit yourself to remote links and comments.
- **A targeted text fix, with the user's approval:**
  1. `GET $JIRA/rest/api/2/issue/<KEY>?fields=description` immediately
     beforehand.
  2. Assert each phrase to replace occurs exactly once, and replace only those
     phrases.
  3. `PUT {"fields":{"description": …}}`.
  4. Re-fetch and diff line by line. The only changed lines must be the ones
     you meant, and workflow-owned sections must still be present.

  This keeps everything else byte for byte, which matters most when an
  automated workflow is writing to the same ticket.
- **A structured story-update tool may refuse raw descriptions.** If yours
  builds the description from structured fields (background, user story,
  scope, supporting info, acceptance criteria; the overlay lists them), the
  rendered layout differs from a hand-written panel description. Tell the
  user so when you show them the draft.

## 6. Improve this skill

At the end, read the shortcomings in `rca-log.md`. If one is new and would
recur, add it to "Traps" below, or to the overlay (its profile or toolkit)
if it is organisation-specific. Don't record one-off typos.

## Traps (each one has happened)

- **Announcing the cause too early.** "Looks like the root cause" came before
  checking whether it had ever worked, and the ticket's QA then disproved it.
  Run the step-3 checks first.
- **Searching change records by symptom only.** The ticket that caused the
  break (a CMS taxonomy migration) was findable by searching the entity, but a
  generic symptom JQL capped at 10 results missed it.
- **Reading a whole secrets file into the transcript.** Read keys, then pull
  the values you need.
- **`curl -L` hiding the first hop**, then puzzling over why the screenshot
  URL renders at all. Inspect each hop.
- **zsh quirks in one-liners** (each hit this run, some twice):
  - An unquoted `$var` never word-splits, so `set -- $var` or
    `cmd $ids` passes the whole list as **one** argument. Pass lists through a
    file, or use `${=var}`.
  - `echo "$json"` expands backslash escapes and corrupts JSON. Use
    `printf '%s'`, write to a file, or parse in Python.
  - A word starting `=`, like `====`, triggers `=cmd` expansion.
  - Unmatched globs such as `--include=*.ts` abort the command.

  Quote separators (`echo '----'`), use arrays, or run under `bash -c`.
- **Stopping a paginated API at the wrong signal.** Confluence search returns
  at most 50 results per page even when you ask for 100, so "fewer than I
  asked for" ends the loop early. Paginate on `_links.next`. A suspiciously
  round count (exactly 50) is the tell.
- **Chasing logs that can't answer.** JSON-in-`message` logs with ~3-day
  retention can't date a break from a week ago. Check retention and field shape
  with one sample before writing aggregate queries.
- **Discovering missing access mid-investigation.** SSO expired halfway
  through, and the prod account was never requested, so the first RCA shipped
  with the prod CMS and the prod redirect store unverified. Run the step-0
  check first, ask for every account at once, and hold the RCA until prod
  evidence is in.
- **Claiming absence from truncated output.** `grep … | head -10` cut off the
  list before the match. Before saying "X is not in Y", rerun the search for
  the exact key, with no `head` or `limit`.
- **Not keeping the Markdown draft on disk.** The RCA was written straight
  into a Claude Docs artifact. The Docs export returns the file as base64 in
  the tool result, not as a local file, so publishing to Confluence meant
  rebuilding the Markdown by hand. Keep `rca.md` in the scratchpad as the
  source of truth, and publish every target from it.
- **Attaching a PDF when a link was meant.** "Attach the RCA to the story"
  was read as "upload a file". The PDF duplicated the Confluence page, went
  stale, and showed the diagram as raw source. Link the page instead.
- **Placeholders that vanish in conversion.** The incident-status row said
  `"Resolved on <date>, fix released in <version>"`. The Markdown converter
  treated `<date>` as an HTML tag, and the page read "Resolved on , fix
  released in ". An independent audit spotted it, not the read-back. Write
  placeholders as `[date]` or `TBD`. `md2cf.py` now refuses `<word>` text
  outside code.
- **Publishing a diagram Confluence can't draw.** The RCA page went out with
  its flowchart as a Mermaid code block, and the user saw raw source. Render
  it to PNG and attach it (step 4). Then look at the image: the first render
  came out 300 px wide with URLs broken mid-word, because Mermaid scales to
  fit its container unless `useMaxWidth` is off.
- **Leaving the investigator's recommendation in place after the team
  decided.** The Fix section still recommended the investigator's option
  after the team had chosen a different query.
  When a decision lands, rewrite the Fix section to match it, and add the
  measured effect (step 4b).
- **Writing for the conversation, not for the record.** The first drafts said
  "this week", "Broken since 24 Sep" (no year), and "the RCA written for this
  proposal", and read as a reply to the user's premise. The user caught it in
  review. Run the durability search in step 5 before handing anything over.
- **Treating a ticket's explanation as fact.** "404 until the queue drains"
  turned out to be a missing route in code.
