---
name: agent-alerts
description: Shared plumbing for skills that report to the user through one private "agent desk" channel. Posts an alert there through an incoming webhook (scripts/notify.py). For any message that tags other people (an MR review request, a testing request), it never sends: it creates a ready Slack draft in the target channel, with the suggested people and the reasons, so the user edits and sends it themselves. It watches the alert's thread for the user's replies, notices when the user has sent the draft, and hands the final channel and people back to the calling skill. Load it from monitor-dev-ci, monitor-stage-ci, mr-review-request, or any skill that tells the user something and lets them decide what goes to a team channel.
---

# Agent alerts

Long-running skills (CI watches, QA runs, MR hand-offs) finish while the user is
away from the terminal. They report to one private channel, the **agent desk**,
which only the user reads. Some of them also need a message to reach other
people: reviewers, QA testers. Tagging the wrong person in the wrong channel is
the failure to avoid, so this skill never posts those messages. It puts a
finished **draft** in the right channel and lets the user send it.

The calling skill decides **what** to say and to whom. This skill decides
**how**: the alert, the draft, the thread replies, noticing the send, and the
hand-back.

## Organisation overlay (optional)

Before starting, look for `${AGENT_SKILLS_OVERLAY:-~/.config/agent-skills/overlay}/overlays/agent-alerts/profile.md`.
If it exists, read it, and any file it points to, before doing anything else.
It supplies the desk channel (name and id), the webhook and how to read it, the
user's messaging-tool user id, the messaging tools, and any send guard and its
allowlist. For facts about the organisation the overlay wins; for method and
guardrails this file wins. Without an overlay, ask the user where alerts should
go, and skip the parts that need a webhook or a messaging tool.

## 1. Post an alert

Post with `scripts/notify.py` (next to this file). Read the webhook URL into a
variable from the overlay's config/secret helper, check its shape
(`https://hooks.slack.com/services/...` for Slack), and pass it only as
`NOTIFY_WEBHOOK_URL` in the script's environment. Never echo it, log it, or put
it in a file, a commit or the transcript.

```bash
NOTIFY_WEBHOOK_URL="$U" python3 scripts/notify.py \
  --skill <calling skill> --repo <repo short name> \
  --status ok|failed|waiting|blocked --headline "<one line>" \
  --line "<mrkdwn line>" … --link "Label=https://…" … \
  [--code "<title>" "<preformatted body>"] \
  [--announce-text "<copyable mrkdwn>" --announce-channel-name "#ch" --announce-channel-url "https://…"]
```

It builds the payload with a serializer, so quotes and newlines can't break it,
and prints `posted` or `failed: <status> <body>`. `--dry-run` prints the payload
without posting. A failed post is reported in the terminal and never fails the
calling skill.

- The first line always names the calling skill, so the desk reads as a log of
  which run said what.
- **No live mentions in an alert.** Write people and `@here` as plain text
  (`@Name`), never `<@U…>` or `<!here>`, so the desk pings nobody.
  Plain text alone isn't enough: unparsed by default, Slack turns a literal
  `@here` into a real mention. `notify.py` marks every text block `verbatim`,
  which stops that (and stops `#channel` auto-linking); explicit `<url|label>`
  links still work. Use `--announce-note` and `--announce-button` to word the
  copy block's intro and its button (e.g. "Open #ch, draft ready").

## 2. Messages that tag other people: draft, don't send

When the calling skill needs a message to reach other people:

1. **The calling skill builds the proposal:** the channel or channels, the
   people with a one-line reason each, and the exact text with real mentions.
   Every person and channel must resolve to exactly one id. Leave out anyone who
   doesn't, and list them as "not found" rather than guessing.
2. **Create one draft per channel** with the messaging tool's draft call. A
   draft sits unsent in the user's composer for that channel, so nobody is
   pinged until the user sends it. Keep the draft's link and the time it was
   created.
   - If the channel already has an unsent draft (Slack allows one per
     channel), don't overwrite it. Say so in the alert and include the text to
     paste instead.
   - If the user isn't a member of the channel, the draft fails. Say so; offer
     the text to paste.
   - **Formatting in drafts:** leave a blank line after a bullet list. Without
     it the next line (a `cc:` or reviewer line) is joined onto the last bullet.
   - **Link previews:** a link to a page behind single sign-on unfurls as the
     login page (e.g. "SAML single sign-on"). The draft call can't turn previews
     off, so say in the alert that the preview should be dismissed before
     sending.
3. **Post the alert** (section 1) with:
   - what the draft is for, and the channel(s);
   - the people, each with their reason, as plain text;
   - a link button per channel, "Open #ch, draft ready", pointing at the draft's
     channel link;
   - the full text as a fallback to copy;
   - a one-line note on replies: `skip`, `#other-channel`, `sent` (section 3).
4. **Tell the user in the terminal** the same thing in two lines, and that the
   watch is running (section 5) and for how long.

The user edits the draft in Slack (adds or removes people, rewrites lines,
deletes it) and sends it themselves. Never call the messaging tool's send for
these messages. A send guard, if the overlay names one, should allow drafts to
the channels the user has listed and still block sends.

## 3. Replies in the alert's thread

Only replies **written by the user** count; ignore anyone else's. The words
other than these commands are ignored and quoted back, so nothing the user
meant is lost silently.

| Reply | Effect |
| --- | --- |
| `skip` (or `no`) | Stop watching; the draft stays in Slack for the user to delete. |
| `#ch` | Also create the draft in that channel (one more draft). |
| `move #ch` | Same, and stop expecting a send in the original channel. |
| `sent` (or `done`) | Check for the sent message now instead of at the next tick. |
| `draft` (where the calling skill supports it) | The skill-specific variant, e.g. send the review request but keep the MR a draft. |

After each reply, post a short follow-up alert saying what changed.

## 4. Notice the send and hand back

The calling skill gives an **identifier** that its message must contain: the MR
URL or `!<iid>`, the ticket key, the release tag. On each check:

1. Read each proposed channel's messages newer than the draft time and find
   ones **written by the user** that contain the identifier.
2. If none, also search the user's own messages since the draft time for the
   identifier (the user may have sent it somewhere else). A match in an
   unexpected channel is reported as such.
3. On a match, read that message's mentions and resolve each to a person. That
   list, not the proposal, is the final list. Hand back the channel, the
   message link and the people to the calling skill, which does its follow-up
   (e.g. set the MR's reviewers).
4. Report in the terminal and in a follow-up alert: where it went, who was
   tagged, what the calling skill did with it, and that the watch has stopped.

A message the user sent that tags nobody is still a match: hand back an empty
list and let the calling skill decide (usually: do nothing it would do per
person, and say so).

## 5. Watching

- Find the alert's thread: the webhook returns no message id, so read the desk
  channel right after posting and take the newest message whose first line
  names the calling skill and its identifier. If it can't be found, say so; the
  terminal and the send detection still work.
- Schedule a recurring in-session check every few minutes for the calling
  skill's watch window (the overlay's default when the skill gives none). Each
  check handles new thread replies (section 3), then looks for the send
  (section 4).
- Stop on a detected send, on `skip`, or when the window ends. On window end,
  post a last alert: the draft is still in Slack, and sending it now won't
  trigger the follow-up, so the user should ask in the terminal.
- The check lives only as long as the agent session. Say so when it starts.

## Guardrails

- Never send a message that tags other people; create a draft and let the user
  send it.
- Never act on a thread reply from anyone but the user.
- Never guess a person or channel; leave out what doesn't resolve to exactly
  one id, and say so.
- Never put live mentions in an alert.
- Never print or store the webhook URL.
- Never treat the proposal as the final list once the user has sent: the sent
  message is the truth.

## Revision notes

- **16 October 2026 (evening)** — a dev alert's literal "@here" rendered as a
  live mention in the desk, and "Tag message::" doubled its colon. notify.py
  now sets `verbatim` on every text block and strips a trailing colon from
  `--code` titles; added `--announce-note` and `--announce-button`.

- **16 October 2026 (later)** — a test draft showed two rendering issues: a
  line after a bullet list joins the last bullet unless a blank line separates
  them, and an SSO-protected link unfurls as the login page. Added both to
  section 2.

- **16 October 2026** — first version, taken from the thread-reply rules that
  monitor-stage-ci grew the same day. The user asked for messages that tag
  people to be prepared, not sent ("so I can click a button there and edit
  channel or reviewers and then I can manually send … This makes sure no wrong
  people in wrong channels are tagged"), so the agent now drafts and the user
  sends, and the sent message decides the final list.
