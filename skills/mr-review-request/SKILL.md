---
name: mr-review-request
description: After a GitLab MR is opened (by hand, or at the end of a delivery workflow such as ship-it, interactive-ship or quick-ship), prepare its review request without sending anything. Picks reviewers from related work (who authored or reviewed MRs on the same ticket and files) with a reason each, drafts the request in the team's review channel as an unsent Slack draft, and posts an alert to the user's agent desk with an "Open channel, draft ready" button. The user edits the reviewers or the channel in Slack and sends it themselves. When the sent message is detected, it sets the MR's GitLab reviewers to exactly the people tagged, adds a reviewer-reasons note to the MR and marks the MR ready. Use when an MR has just been created, or when the user says "request a review", "send the review request", "post this MR for review", or invokes /mr-review-request with an MR IID or URL. Never posts the request itself.
---

# MR review request

The last step of delivering a change is asking the right people to review it, in
the right channel, with enough context to start. Doing that by hand is easy to
get slightly wrong: a reviewer left off, the wrong channel, a reviewer set in
Slack but not on the MR. This skill prepares everything and leaves the one
judgement, and the send, to the user.

It runs through the `agent-alerts` skill (`../agent-alerts/SKILL.md`): draft,
don't send; alert on the agent desk; notice the send; hand back who was tagged.

## Organisation overlay (optional)

Before starting, look for `${AGENT_SKILLS_OVERLAY:-~/.config/agent-skills/overlay}/overlays/mr-review-request/profile.md`.
If it exists, read it, and any file it points to, before doing anything else.
It supplies the review channel per team, the message template, standing
reviewer conventions, how to read the ticket's team, and how GitLab users map to
messaging-tool users. For facts about the organisation the overlay wins; for
method and guardrails this file wins. Without an overlay, ask the user for the
channel and use the default template below.

## Inputs

- **MR**: an IID or URL; otherwise the MR for the current branch
  (`glab mr view --output json`). `$P` is the URL-encoded project path.
- **Ticket key**: from the MR title or source branch (`KEY-123`); ask only if
  neither has one.
- **`--watch`**: poll Slack for the send and thread commands (section 4).
  Off by default.
- **`--keep-draft`**: don't mark the MR ready on send (the same as the user
  replying `draft` in the alert's thread). Section 6 lists every thread
  command.
- **Starting automatically:** a hook may start this skill right after an MR is
  created. That is safe, because the skill only drafts and alerts. Don't ask
  questions in that case; put anything uncertain in the alert.

## 1. Check it hasn't been done

Before drafting, look for an existing request: a message from the user in the
review channel, or anywhere (search the user's messages), containing the MR URL
or `!<iid>`. If one exists, report it with its link and stop. Never draft a
second request for the same MR. Also stop, and say so, when the MR is merged or
closed.

## 2. Pick the reviewers, with a reason each

Base the choice on related work, never on load or at random:

1. MRs for the same ticket (`glab mr list --search <KEY> --all`), and for
   linked or parent tickets: their authors, reviewers and approvers
   (`glab api projects/$P/merge_requests/<iid>/approvals`).
2. Recent history of the files this MR changes (`git log --format=%an -- <files>`
   over the last few months), and the MRs that introduced the code it builds on.
3. Standing conventions from the overlay (e.g. "this person reviews every MR on
   this board").

Never pick the MR's author. Rank by how directly each person's work touches
this change, and keep the list short (three to five). Give each a one-line
reason that names the evidence: "reviewed !8865, which changed the same mapper",
"built this grid (KEY-123)". People already set as reviewers on the MR stay in,
with their reason, or "already a reviewer on the MR".

Map each person to the messaging tool: by email first, then full name, and
confirm a partial name match against the email. Anyone who doesn't map to
exactly one person goes in the alert as "not found in Slack, left out".

## 3. Write the request

Use the overlay's template. Without one:

```text
Hi @here,
Could I please get a review on [!<iid>](<MR URL>)?
[<KEY>](<ticket URL>) <MR title without "Draft:">
- <what changed, one line>
- <what changed, one line>

<@reviewer>: <reason>
<@reviewer> <@reviewer>: <shared reason>
```

- Two or three one-line bullets about the change itself, taken from the MR
  description: what it does and why, not how it was verified.
- No test counts, commit counts, QA status or open-thread status. Those belong
  in the MR.
- One line per reviewer (or per group sharing a reason), with real mentions in
  the draft, after a blank line so the last bullet doesn't swallow it.

## 4. Hand it to agent-alerts

Give `agent-alerts`:

- **Channel:** the overlay's review channel for the ticket's team (read the
  team from the ticket the way the overlay says). If the team has no mapped
  channel, create no draft: post the alert with the text to paste and ask in it
  where the request should go (`#channel` reply).
- **People:** the reviewers from step 2, with their reasons.
- **Text:** step 3.
- **Identifier:** the MR URL and `!<iid>`.
- **Watch:** opt-in. Start one only on `--watch` or when the user asks;
  then it checks at most every 15 minutes, for the overlay's window (four
  hours by default), and stops on the send. Without a watch, tell the user to
  say `sent` in the terminal once they have sent the request; then check once
  and do section 5.
- **Commands:** the table in section 6. They are read from the thread on each
  check: on a watch tick, or when the user says `sent` or asks you to look at
  the thread.

The alert's headline is "<KEY> review request ready: !<iid>". It also lists
the MR's state (draft or ready) and what will happen on send (step 5).

## 5. When the user has sent it

`agent-alerts` hands back the channel, the message link and the people the user
actually tagged. Then:

1. **Set the MR's reviewers to exactly those people.** Map each back to their
   GitLab user (the overlay's mapping, or a member search by name). Use the
   API with a JSON body, because form-style array parameters can silently set
   nothing:
   ```bash
   jq -n --argjson ids '[<id>,<id>]' '{reviewer_ids:$ids}' > body.json
   glab api -X PUT "projects/$P/merge_requests/$IID" -H "Content-Type: application/json" --input body.json
   ```
   Read the MR back and confirm the reviewer list matches. Anyone without a
   GitLab account is reported, not guessed.
2. **Add a reviewer-reasons note to the MR** (`glab mr note`): each reviewer
   with the reason from step 2, or "tagged by <user> in the review request"
   for people the user added.
3. **Mark the MR ready** (`glab mr update <iid> --ready`), unless `--keep-draft`
   or a `draft` reply. If it is already ready, say so.
4. **Confirm** through `agent-alerts`: where the request went, who was tagged,
   the reviewers now on the MR, the note link, and the MR's state.

If the sent message tags nobody, change no reviewers, add no note and don't
mark it ready. Say so, and let the user decide.

## 6. Commands from the alert's thread

The user can steer the review request from Slack without opening the terminal.
These are added to the agent-alerts built-ins (`skip`, `#ch`, `sent`, `status`,
`stop`, `help`) and follow its rules: only the user's own replies count, each
handled reply gets a follow-up alert, and a **confirmed** command waits for
`yes` in the thread.

| Reply | Effect | Kind |
| --- | --- | --- |
| `go` | Use the suggested reviewers without a Slack message: set them on the MR, add the reasons note, mark the MR ready. The Slack draft stays for the user to send or delete. | direct |
| `reviewers @a @b` | Set exactly these people as the MR's reviewers, plus the reasons note. Slack mentions or names, each resolved to one GitLab user; anyone who doesn't resolve is reported and left out. | direct |
| `+@a` / `-@a` | Add or remove one reviewer. | direct |
| `undraft` (or `ready`) | Mark the MR ready now. | direct |
| `draft` (or `keep draft`) | On send, keep the MR a draft; if it is already ready, set it back to draft. | direct |
| `bump` | Bump the version the repo's convention asks for (the repo's agent instructions, or the overlay's rule for the repo), commit with the repo's commit format, and push. Post the planned files and versions first. If the change touches nothing the convention versions, say so and change nothing. | confirmed |
| `rebase` | Rebase or merge the default branch into the MR branch, run the repo's checks for what changed, and push. Post the plan and any conflicts first. | confirmed |
| free text | Anything else, e.g. "fix the nit in the spec", "also ask Priya". Work it out as section 3 of agent-alerts says; code changes are confirmed, and messages to other people become a new draft, never a send. | per action |

- Reviewer commands change the MR's GitLab reviewers and the reasons note
  only. They never edit or send the Slack message: if the user wants the
  request itself changed, offer a new draft.
- After a `bump` or `rebase` push, say in the follow-up whether any review or
  QA evidence was invalidated (the tree changed) and what would re-validate it.
- Merging is never a thread command. Point to the terminal.

## Guardrails

- Never post the review request yourself; draft it and let the user send it.
- Never pick the MR's author, and never guess a person who doesn't resolve to
  exactly one account.
- Never draft a second request for an MR that already has one.
- Never set reviewers from the proposal: only from the message the user sent.
- Never put test or commit counts in the request.
- Never commit or push from a thread command without the user's `yes` to
  the posted plan.

## Revision notes

- **30 October 2026** — the watch is opt-in (`--watch`). By default the user
  says `sent` in the terminal and one check runs, because a 4-minute poll ran
  for hours on one MR and the user would rather not pay for that
  convenience. An opt-in watch checks at most every 15 minutes and stops on
  the send.

- **23 October 2026** — added section 6, thread commands (`go`, `reviewers`,
  `+@`/`-@`, `undraft`, `draft`, `bump`, `rebase`, free text), at the user's
  request to control undrafting, reviewers and version bumps from Slack. The
  watch now continues after the send so post-send commands work.

- **16 October 2026** — first version, at the user's request: prepare the
  review request after an MR opens, so they can edit the channel and reviewers
  and send it themselves ("This makes sure no wrong people in wrong channels
  are tagged"). On send it sets the MR's reviewers, adds the reasons note and
  marks the MR ready, as the user chose.
