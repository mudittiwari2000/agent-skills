---
name: pick-next-ticket
description: Pull the next ticket from a priority-ordered Kanban board's ready lane (To Do), the way a careful teammate would. Checks first that nothing you already own needs finishing, then walks the lane in pull order (expedite, fixed-date risk, priority, board rank), compares the ticket already assigned to you with anything of higher priority that is still unclaimed, scores your confidence (0-10) in each candidate against its acceptance criteria and the real code, and pulls the first one that clears the threshold (default above 8), falling back to your assigned ticket. Skipped tickets are reported with the question that would unblock them, so they don't starve. Then claims it, gives you a TL;DR, and drafts the "I'm picking this up" message in the team channel in the shape the channel already uses, for you to send. Use when the user says "pick up my next story", "what should I work on next", "take the highest-priority ticket in To Do", "once this is in review, pick the next one", or invokes /pick-next-ticket. Never sends the team message itself.
---

# Pick the next ticket

Made for **Kanban boards run as a pull system on priority**: nobody hands out
work; when a developer frees up, they pull the top-priority item from the ready
lane (To Do) and say in the team channel what they took. Kanban practice adds
two rules around that pull: finish what you already own before starting
something new ("stop starting, start finishing"), and take items in the order
the board's policy sets, so urgent work isn't left waiting.

An agent following the rule naively makes two mistakes. It grabs the top
ticket whether or not it can deliver it, or it keeps to its own assigned ticket
while something more urgent sits unclaimed. This skill weighs priority against
confidence. It moves to a higher-priority ticket only when it can honestly
deliver it, shows its reasoning so the user can overrule it, and says what
would unblock every ticket it passed over.

It works on Scrum boards too (pull from the sprint's To Do), but the priority
and rank rules assume the lane's order is the team's real priority.

## Organisation overlay (optional)

Before starting, look for `${AGENT_SKILLS_OVERLAY:-~/.config/agent-skills/overlay}/overlays/pick-next-ticket/profile.md`.
If it exists, read it, and any file it points to, before doing anything else.
It supplies what this skill leaves as placeholders: the board and its ready-lane
query, the tracker tools, the priority scale and any team rule about it, the
team channel, who to cc, the delivery workflow to hand the ticket to, and the
confidence threshold if the team uses a different one. For facts about the
organisation the overlay wins; for method and guardrails this file wins.
Without an overlay, ask the user for the board, lane and channel once, and offer
to record them in a new overlay profile.

## When to run

- The user's current ticket has just reached review, and they want the next one.
- The user asks what to work on next, or asks you to pick it.
- A delivery workflow finishes its hand-off and the user asked beforehand for
  the next pick ("once this is in review, pick up the next one").

If the user names a ticket, this skill isn't needed; start that ticket.

## 0. Finish before you start

Walk the user's own work from right to left (closest to done first) before
pulling anything:

- an MR or PR with unanswered review comments or a red pipeline;
- a ticket in testing or sign-off with an open question addressed to the user;
- a blocked ticket the user could unblock;
- a WIP limit on the user's lane or column that pulling would break.

If any of these exists, report it and ask whether to deal with it first. Pull
anyway only when the user says so, or when the work is waiting on someone else
(a reviewer, QA, a product answer) and nothing is the user's to do.

## 1. Read the ready lane

Fetch every item in the board's first actionable lane (often "To Do"). Use the
board's own filter, not a guess at it. Page through all results. For each item,
collect the key, summary, type, assignee, priority, board rank, story points,
parent, labels and last-updated time.

Drop items that are not real pickups:

- sub-tasks, including review or QA gate sub-tasks of in-flight stories;
- items **assigned to someone else**, which are claimed even when they sit in
  the lane;
- items blocked by an open dependency (an inbound "is blocked by" link to an
  unfinished item), or labelled blocked;
- items someone has already claimed in the team channel in the last few days
  but not yet assigned. Search the channel for the key.

What remains splits into **mine** (assigned to the user) and **available**
(unassigned).

## 2. Order the lane by pull policy

Sort in the board's **pull order**:

1. **Expedite**: an item flagged as an emergency (an expedite swimlane or flag,
   or a "Highest"/blocker priority on a live incident). It goes first and may
   break a WIP limit; say so.
2. **Fixed date at risk**: an item with a due date that will be missed if it
   isn't started now (due date minus a rough lead time is today or past).
3. **Everything else by priority**, highest first, ties broken by **board rank**
   (the lane's top-to-bottom order). Respect a rank marker the team uses, such
   as a "prioritised above this line" ticket: nothing below it outranks
   anything above it.
4. **Intangible** work (tech debt, tooling, "when you have time"), only when
   nothing above it is pullable.

Use the tracker's priority scale, not memory. Get the scale from the tracker, not from memory. Some tickets carry a
value outside the usual names (for example a custom "Not prioritised"). Place
those with comparison queries (`priority < Low`, `priority > High` in JQL)
rather than guessing. Say where you placed them and how.

- **Reference ticket:** the user's assigned item in the lane. If several are
  assigned, use the highest-priority one; if none, there is no reference.
- **Candidates:** available items with a strictly higher priority than the
  reference, in order. With no reference, every available item is a candidate.

A team rule in the overlay (for example "bugs strictly Highest, then High, then
Medium") overrides this order. Quote it in the summary.

## 3. Score confidence, grounded, one candidate at a time

Work down the candidates in order. For each one, read the full ticket
(description, acceptance criteria, recent comments, links). Then **look at the
code** it would change before you score it. A score from the ticket text alone
is a guess, and the guess is usually too high.

Start each candidate at 10 and subtract:

| Deduct | When |
| --- | --- |
| 3-5 | An open product or design decision changes what "done" means (the ticket says "decision needed", or refinement questions are unanswered). |
| 2-3 | The code you found contradicts the ticket's stated fix (for example a comment explaining why the current behaviour is deliberate), or the real fix is in a different place from where the ticket points. |
| 2 | The change depends on runtime state you can't confirm: a feature flag, config, or data that differs between environments. |
| 1-2 | Acceptance criteria are vague, missing, or have no testable outcome. |
| 1-2 | The change touches shared code with a wide blast radius, or a repo or stack you can't build and test locally. |
| 1-2 | The fix can't be verified before merge (no stage reproduction, prod-only data). |
| 1 | Unestimated, or the estimate disagrees badly with what you found. |

Write one line per candidate: the score and the two or three reasons that
moved it. Cite what you read (`file:line`, comment id, flag name).

**Pick the first candidate whose score is above the threshold** (default 8,
meaning 9 or 10). Stop scoring at the first pick; you don't need to score the
rest. If no candidate clears it, fall back to the reference ticket and say so.
If there is no reference either, recommend the best-scoring candidate and ask
the user before claiming it.

Don't round a score up to clear the threshold. A candidate at 8 with one
question open is the user's call: name the question so they can answer it and
re-run.

**Don't let a skipped ticket starve.** In a pull system the top item stays at
the top until someone takes it, so a low score must not quietly pass it over
forever. For each skipped candidate, name the one question or fact that would
lift its score (a product decision, a flag state, a reproduction), and who can
answer it. Report these in the summary. Offer to ask them, but post nothing
without the user's say-so.

## 4. Claim it

Do this only when the user asked you to pick up the work. If they only asked
what to work on, stop at the summary and ask.

- Assign the ticket to the user.
- Add it to the active sprint if the board uses sprints.
- Don't change its status yourself. The delivery workflow moves it when work
  starts.
- Leave every other ticket alone. Never unassign anyone.

## 5. Tell the user (TL;DR)

In the terminal, short and in this order:

1. **Picking:** key, title, link, priority, points.
2. **Why this one:** the rule that chose it (higher priority and confidence N,
   or a fallback to the assigned ticket because candidates scored N, M).
3. **TL;DR:** what is broken or wanted, in two or three plain sentences, and
   the likely fix with the file it lives in.
4. **Open points:** questions to settle before or while starting.
5. **Passed over:** each higher-priority candidate, with its score and the one
   reason that kept it below the threshold, so the user can overrule.

## 6. Draft the pickup message

Read the team channel's last few weeks of messages (about 50-100). Find the
messages where someone announced they were taking a ticket, and copy their
shape: greeting or `@here`, how the ticket is linked, whether they give a
reason or a due date, who they cc, and how long the message is. Keep to what
the team already writes; don't add sections nobody uses.

Write it in the user's voice, first person, as their own announcement. State
the reason the rule gave ("it's the highest-priority ticket in To Do" only when
that is true; if it was a fallback, say it's the user's assigned ticket). Add
one line on what the user will do first.

Then hand it to the team's draft path (the `agent-alerts` skill, or the
overlay's equivalent). It lands as an **unsent draft** in the channel, and the
user edits and sends it. Never send it yourself. Some messaging tools keep
one draft per channel; if the channel's draft slot is already taken (often by
the review request for the ticket just handed off), don't overwrite it. Send
the pickup text to the user's private alert channel as a copy-ready message
instead, and say so. Show the draft text in the
terminal as plain text, not a blockquote, so it copies cleanly.

## 7. Hand off

If the user asked for the work to start, start the overlay's delivery workflow
on the picked ticket. Otherwise end with the command that starts it.

## Guardrails

- Never claim a ticket assigned to someone else, or one claimed in the channel.
- Never send the team message; draft it.
- Ground every confidence score in the code and the ticket, and cite it.
- Report the scores even when the fallback wins, so the choice can be checked.
- Don't open the ticket's open questions on the user's behalf in Jira or Slack
  unless they ask. List them in the summary instead.

## Background

- Pull order follows Kanban's classes of service (expedite, fixed date,
  standard, intangible), as in the Kanban University glossary and David
  Anderson's work, with the standard class ordered by the board's priority and
  rank instead of age because this skill targets priority-ordered boards.
- Step 0 is the Kanban habit of walking the board right to left and finishing
  work in flight before pulling more.
