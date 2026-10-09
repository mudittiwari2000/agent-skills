# Review Brief format

Emit exactly this shape, in about 40 lines. Plain Markdown with no
blockquotes, so any part can be copied.

Budget rules when it runs long, in this order:
1. Merge trivial verified items onto one line.
2. Shorten commands to their essential part (`jest toaster confirm-modal`).
3. Put a stop's partner locations on its "Look at" line instead of the header.
4. Drop the lowest-risk stop and count it in the "dropped" line.

```
# Review Brief — <title> (!<iid> @ <HEAD_LABEL>)
<one sentence: what the MR does, in the user's terms>

## Already verified — skip these
- <check or fact> → <result>   (`<command>` or `file:line`)
- ...
- Not verified: <check> — <why> (only if any)

## Proven defects  (omit the section when there are none)
- `file:line` — <defect and its trigger>  → <smallest fix>

## Your stops (most risky first)
1. `file:line` (+ `partner:line`) — <short label>
   Why you: <why the code can't settle this>
   Question: <neutral yes/no or short-choice question>
   Look at: <one or two things to open or run>
   If yes → <outcome> · If no → <outcome>
2. ...
(<n> lower-risk candidates dropped: <one line on what kind>)   (only if any)

## Approve if
<condition stated in terms of the stops and defects>

Walk through the stops one by one? Re-run with --walk or say "walk me".
```

## Rules for the content

- **Already verified** lists results, not activities: "jest 133/133 pass" or
  "the new specs fail on base (5 tests)", never "ran the tests". Group trivial
  checks on one line.
- **Proven defects** need a reproducible trigger or a concrete conflict, such
  as a merge-tree conflict, a failing command, or a caller that breaks. A code
  comment or description claim contradicted by the code also counts; cite both.
  Anything less is a stop, not a defect.
- **Question** must be answerable without reading this skill. It must not
  smuggle in a verdict. For example, ask "Is moving every mobile toast to the
  bottom intended, including export and newsletter?". Don't ask "This
  wrongly moves every toast, right?".
- **If yes / If no** (or **If A / If B** for a short-choice question) use these
  outcomes: approve as is · leave a comment · ask the author first · request
  changes. At most one qualifier per outcome.
- **Approve if** is one line a reader could check off, for example "approve
  if stop 1 is intended and the version conflict is fixed".

## Walk record (`$WORKTREE.walk.md`)

```
# Walk — !<iid> @ <HEAD_LABEL>

| # | Where | Verdict | Note |
|---|---|---|---|
| 1 | `file:line` | OK / Concern / Question / Skip | <user's words, short> |

## Draft comments
- `file:line` — question: <text>
- `file:line` — suggestion: <text>

## Proven defects (include if you want)
- `file:line` — <ready-to-post comment>

## Implied verdict
<approve | approve with comments | request changes> — your call.
```
