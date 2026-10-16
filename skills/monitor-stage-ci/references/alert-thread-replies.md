# Acting on replies to a CI alert

Shared by `monitor-dev-ci` (the stage-deployment announcement) and
`monitor-stage-ci` (the testing request). Each skill decides **what** it
proposes: the message, the suggested channels, the suggested people and why.
This file decides **how** the user approves, edits or declines that proposal,
either in the terminal or by replying to the alert, and how the run sends it.

## 1. Post a proposal, not just a draft

The alert that offers the message shows the proposal in full:

```text
Proposed: <what the message is for>
To: #channel-a (<id>), #channel-b (<id>)
cc: @person-a (<why: e.g. reviewed the MR>), @person-b (<why>)
<exact message text>
Reply in this thread: `send` · `+@x` / `-@y` / `+#ch` / `-#ch` to edit · plain `#ch @x` to send to exactly those · `skip`
```

Write mentions in the alert as plain text (`@here`, `@name`), never as live
mentions, so the alerts channel pings nobody. The sent message uses real
mentions.

## 2. The reply grammar

Only replies **written by the user** (the user id the overlay names) count.
Read each reply as a list of tokens; every other word is ignored and quoted
back in the report, so a note the user meant to include is not lost silently.

| Reply | Effect |
| --- | --- |
| `send` (or `yes`, `ok`, `go`) | Send the current proposal. |
| `skip` (or `no`, `don't send`) | Send nothing; stop watching. |
| `+#ch`, `-#ch` | Add or remove a channel. Edits only, so no send. |
| `+@x`, `-@x` | Add or remove a person from the cc. Edits only, so no send. |
| plain `#ch …` and/or `@x …` (no `+`/`-`) | Replace the channels and/or the cc with exactly those, then send. Plain channels with no people keep the current cc; plain people with no channel keep the current channels. |
| edits plus `send` in one reply | Apply the edits, then send. |
| `resend #ch` | Send again to a channel already sent to. |

After an edits-only reply, post the revised proposal as a follow-up alert (the
same shape as section 1) and keep waiting for `send`. Edits accumulate across
replies, in order.

## 3. Resolve every name before any send

- Each channel link or `#name` must resolve to exactly one channel id; each
  user mention or name to exactly one user id. Removing someone who is not on
  the list is a no-op, reported as such.
- If any name is unknown or ambiguous, send nothing. Say which name was
  unclear (terminal and follow-up alert) and wait for a clearer reply. A
  partial send from a half-understood reply is worse than none.
- More channels than the overlay's cap (five by default) means confirm in the
  terminal first.
- A proposal left with no channel cannot be sent; say so.

## 4. Grants and sending

- The reply that triggers a send (or the user's terminal answer) is the
  grant: one one-time grant **per channel** for one message, recorded wherever
  the messaging tool's allowlist lives, each quoting the user's words. A reply
  from anyone else grants nothing.
- Send one message per channel, with the same text and cc line. A failed send
  to one channel does not stop the others; for each failure give the user the
  text to paste instead.
- Keep a list of the channels already sent to in this run. A later `send`
  goes only to channels not on it; the others are reported as "already sent".
  Only `resend #ch` sends to a channel again.
- A skill can hold a `send` until a precondition holds (for example, the
  release tag exists). Say that it is held and why, keep checking on each watch
  tick, and send when it clears. `send now` overrides the hold.

## 5. Confirm where the user is looking

Report every message link, and every failure, in the terminal. When the
answer came from the thread, also post a short follow-up alert listing them,
plus whether the watch is still running.

## 6. Watching the thread

The alert goes out through a webhook, which returns no message id. So:

1. Right after posting the alert, read the alerts channel with the messaging
   tool and take the newest message whose first line names the skill and the
   release unit. Its timestamp is the thread. If you can't find it, say so and
   fall back to the terminal question.
2. Schedule a recurring in-session check, every few minutes, for the overlay's
   watch window (two hours by default). Each check reads the replies newer than
   the last one handled.
3. Stop watching (cancel the check) after a send that covered every proposed
   channel, after `skip`, or when the terminal answer has already covered it.
   Keep watching after edits-only or unclear replies, and while a `send` is
   held.
4. When the window ends, cancel the check and say so, in the terminal and in a
   last follow-up alert. The proposal in the alert is still there to copy.

The check lives only as long as the agent session. Say so when the watch
starts, and say in each confirmation whether the watch has stopped.

## Guardrails

- Never send to a channel the user did not choose in this run, in the
  terminal or in their own reply.
- Never act on a reply from anyone but the user.
- Never send part of a proposal whose names did not all resolve.
- Never resend without an explicit `resend #ch`.
- Never put live mentions in the alert itself.
