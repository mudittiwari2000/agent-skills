# Review Brief format

Emit exactly this shape, in about 40 lines. Plain Markdown with no
blockquotes, so any part can be copied.

Budget rules when it runs long, in this order:
1. Merge trivial verified items onto one line.
2. Shorten commands to their essential part (`pytest tests/billing`).
3. Keep only the partner locations a reader needs to answer the question.
4. Drop the lowest-risk stop and count it in the "dropped" line.

```
# Review Brief — <title> (!<iid> @ <HEAD_LABEL>)
<one sentence: what the MR does, in the user's terms>

## Already verified — skip these
- <check or fact> → <result>   (`<command>` or `file:line`)
- ...

## Not verified — look yourself if it matters   (omit when empty)
- <check or path> — <why it could not be verified>

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
(this last line only when --walk was not given)
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
  smuggle in a verdict. For example, ask "Should the new retry also apply to
  the nightly batch job, not only the API path?". Don't ask "This wrongly
  retries the batch job too, right?".
- **If yes / If no** (or **If A / If B** for a short-choice question) use these
  outcomes: approve as is · leave a comment · ask the author first · request
  changes. At most one qualifier per outcome.
- **Approve if** is one line a reader could check off, for example "approve
  if stop 1 is intended and the version conflict is fixed".

## Walk record (`$WORKTREE.walk.md`)

```
# Walk — !<iid> @ <HEAD_LABEL>
MR: <WEB_URL> · head: <full HEAD_SHA> · posting allowed: <EXTERNAL_POSTING_ALLOWED>

| # | Where | Verdict | Note |
|---|---|---|---|
| 1 | `file:line` | OK / Concern / Question / Skip | <user's words, short> |

## Follow-ups and views given on request
- Stop <n>: asked "<follow-up>" → "<answer>"
- Stop <n>: user asked my view → <view, one line, with evidence>

## Draft comments
- `file:line` — question: <text>
- `file:line` — suggestion: <text>

## Proven defects (include if you want)
- `file:line` — <ready-to-post comment>

## Implied verdict
<request changes | wait for the author | approve with comments | approve>, by
the rule in SKILL.md step 5 — your call.
```
