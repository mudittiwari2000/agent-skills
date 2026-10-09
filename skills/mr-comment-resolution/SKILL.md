---
name: mr-comment-resolution
description: Resolve review comments left on the user's OWN GitLab merge request — analyse each finding against the real code, fix what belongs in this MR, raise Jira tickets for what genuinely does not, and post a structured reply that a reviewer can check. Use when the user says a comment/review has landed on their MR, asks to "address the review", "fix the comments", "resolve the comments", "reply to <reviewer>", or shares an MR whose notes need answering. The sibling `mr-review` skill is the opposite job (reviewing someone else's MR) — do not confuse them.
---

# Resolving review comments on your own MR

A reviewer has commented on an MR **you raised**. The job is to give every
finding an honest verdict, act on it, and reply so the reviewer can verify the
outcome without re-reading the diff.

The failure modes this exists to prevent: accepting a finding that is wrong,
rejecting one that is right, silently ignoring one, manufacturing tickets to
look thorough, answering a question with an assertion, and replying in a way
that cannot be checked.

**This skill is not audited.** Treat it as a checklist that has been right so far,
not as an authority. Where a step does not fit the MR in front of you, do the
sensible thing, say so in your report, and fix the skill afterwards (see the
revision notes at the end).

## Organisation overlay (optional)

Before starting, look for `${AGENT_SKILLS_OVERLAY:-~/.config/agent-skills/overlay}/overlays/mr-comment-resolution/profile.md`.
If it exists, read it, and any file it points to, before doing anything else.
It supplies what this skill leaves as placeholders (repo profiles, tracker and
CI tool names, environment access, house conventions) and may add steps.
For facts about the organisation the overlay wins; for method and guardrails
this file wins. Without an overlay, discover the values from the repo and the
user, and record what you learn where the skill says to.

## 1. Gather

Fetch the MR's discussions with your GitLab discussions tool (the overlay names
it) or `glab api`: once filtered to unresolved threads (the work list), and once
in full for context.

```
glab api "projects/:id/merge_requests/<iid>/discussions?per_page=100"   # all threads; filter resolvable && !resolved for the work list
```

Practicalities that cost time the first time:

- The payload can be long, and it includes dozens of system notes ("added N
  commits", "changed the description"); some tools also return every thread
  twice. Skim for `system:false` notes; do not re-read the whole payload each time.
  The reply and resolve tools echo the full note bodies back too — expect long
  output and do not paste it into your own report.
- Note for each thread whether it is `resolvable` and `resolved`. Plain notes can
  only be replied to.
- **Line numbers belong to the version the reviewer saw.** Read
  `position.head_sha` and compare it with the current head. After a rebase or a
  force-push the cited line no longer points at the same code: re-anchor by
  searching for the quoted symbol, never by line number.

## 2. Split every note into findings

A note is rarely one finding. Split it into one item per **point**, whether or not
the reviewer numbered them, and tag each item by kind:

| Kind | Looks like | What it needs |
| --- | --- | --- |
| Defect claim | "X can happen when Y" | verify, then Fix / Ticket / Disagree |
| Suggestion | "could we use a helper…" | adopt, or say why not |
| **Question** | "can you confirm Z?" | an answer **backed by evidence**, never an assertion |
| **Remark** | "minor: just noting…" | acknowledge; say whether anything follows |
| Offer | "fine as a follow-up ticket" | take it only if the scope argument holds |

## 3. Verify each finding against the code — before agreeing or disagreeing

**Open the file and the lines cited.** A reviewer (human or automated) can be
right about the smell and wrong about the mechanism, or right about a line a later
commit already changed.

For each finding establish, in order:

1. **Is the claim true of the current HEAD?** Quote the code.
2. **Is it reachable, and how?** Say so honestly either way — "not reachable on
   today's data" is useful context, never on its own a reason to decline a cheap fix.
3. **Does the ticket require the behaviour the reviewer is questioning?** Check the
   acceptance criteria and business rules verbatim before calling anything a
   regression or a mistake.
4. **Look at what the reviewer did not name.** The same defect usually has siblings
   (a reviewer named two call sites; a third was the original), and the obvious fix
   usually has a cost they did not mention (a dropped async response must also
   release its "loading" flag, or the next request is blocked for ever).

For a **Question** about how the system behaves ("is this flag always on?"):

- Find what **controls** the thing (the flag, the config key, the default) and say
  what it is. "Always" is almost never the answer.
- Back it with a **measurement** when one is cheap (a request log, a timestamp),
  and with the code that explains it.
- **Label the grade of your evidence.** "Read from the code and consistent with the
  measurements, not instrumented in a browser" is honest; "the cause is X" without
  that label is a claim you have not earned.

For a **race or concurrency** claim: reproduce it with a failing test before you
trust either the reviewer or yourself.

Never accept a finding purely because a reviewer raised it, and never reject one
purely because you wrote the code.

## 4. Classify — every finding (or sub-finding) lands in exactly one bucket

| Bucket | Meaning | Action |
| --- | --- | --- |
| **Fix** | Real, and inside this MR's scope | Fix + test in this MR |
| **Intended** | The behaviour the ticket explicitly asks for | No change; quote the AC/rule verbatim in the reply |
| **Answered** | A question or remark; nothing to change | Reply with the evidence; no code, no ticket |
| **Ticket** | Real, but genuinely outside this ticket's scope | Create a Jira ticket, link it |
| **Disagree** | Not correct | Say so plainly, with the evidence that settles it |

One finding may need **two** buckets: a defect that is true and pre-existing is
**Ticket**, while the question attached to it is **Answered**. Split it; do not force
one verdict onto a mixed point.

**Do not invent tickets.** If every finding is Fix, Intended or Answered, the honest
answer is "no follow-up tickets". Equally, do not fold a genuinely out-of-scope fix
into the MR just to close the comment. Good tests:

- **Ticket:** the same defect exists in code this ticket deliberately does not own,
  or fixing it changes behaviour the ticket never mentioned (e.g. editing a shared
  store call changes every caller on every brand).
- **Intended:** you can quote a business rule or AC that requires exactly what the
  reviewer is questioning.

## 5. Fix, test, gate, commit

Fix the **Fix** bucket and fix the *class*, not just the named instances (one shared
helper beats three copies of an inline check).

**Prove each test bites, including against the wrong fix.** Temporarily remove the
fix and confirm the test fails; then try the plausible *incorrect* variant (an early
return that skips the cleanup) and confirm a test fails for that too. A test that
cannot fail is decoration. Restore the file byte-for-byte afterwards and re-run.

**Run the gates, and know which ones actually cover your files.** Run the repo's own
commands, from where the repo runs them:

- A linter may *ignore* the package you changed ("File ignored because of a matching
  ignore pattern"). That is "lint does not apply", not "lint clean" — say so.
- Never pipe a gate into `tail`/`grep` and read the pipeline's exit code; capture
  the real one (redirect to a file, then check `$?`).
- When a type check shows errors, `git blame` them: are they on lines you wrote?
- Run the secret scan and any pre-push rule the repo documents.

**Do not rewrite history during an active review.** Comments anchor to a head SHA.
Add a normal commit and push it. A rebase (and the force-push it needs) belongs
*before* the review starts; once a review is active, rebase only with the
reviewer's explicit agreement, and then cite the post-rebase SHA. Check the
remote's own rules before pushing — commit-message patterns, branch-name patterns —
instead of discovering them from a rejection.

Commit message: name the review and separate verdicts, and say what was deliberately
not changed. Push **before** replying, so the SHA you cite exists.

**Workflow state.** If a QA artifact was recorded against a tree hash, a code change
makes it stale. Do not re-record it. Say which verification you did re-run and which
you did not, and let the user decide whether an expensive full re-run is warranted —
a targeted regression test plus an honest note is the default.

## 6. Raise tickets for the Ticket bucket

Story creation is often gated — route through your team's story-creation workflow
(the overlay names it; such workflows typically handle gating, duplicate detection
and evidence declarations) rather than calling the tracker's create tool cold. Then:

- **Check the issue types the board can create.** If the type you want is not
  creatable (e.g. "Tech Debt"), file the closest type, add the label the existing
  tickets of that kind carry, and tell the user the type can be changed in the UI.
- Put the ticket where the user directs (team, backlog, epic). If a team or board has
  mandatory fields the tool cannot set (the overlay lists known ones), apply them by
  REST and **verify with a board query** before claiming the ticket is visible.
- Write the background so it **stands alone**: who found it and where, what is
  true today with dates and numbers, why it is out of scope here, how reachable it
  really is, the risk, and a suggested direction. Include the evidence grade
  (measured vs read from the code). Link related tickets as *related, not duplicates*.

## 7. Reply so the reviewer can check it

Reply **inside each thread**. Only when a thread genuinely cannot be replied to (it is
not a resolvable discussion, or the API refuses) fall back to a new MR note — and
**@-mention the reviewer who left the finding**, because a standalone comment that
does not name them is easy to miss. Structure, in this order:

1. **A summary table first** — one row per finding, one-word outcome (Fixed /
   Intended / Answered / Ticket / Disagree). Verdicts in five seconds.
2. **Then per-finding detail**, in the reviewer's own order and numbering.
3. **Cite the commit SHA** that carries the fixes, and **link any tickets**.
4. **Close with what was re-verified — and what was not.** The "not re-run" line is
   as important as the "passed" line.

Tone: credit a good catch plainly, and where a finding was right say what made it
right — often the reachability is narrower, or the cost bigger, than the reviewer
realised. Where you disagree, lead with the evidence, not the disagreement. Answer a
**Question** with the answer first, then the evidence, then its grade.

## 8. Resolve threads

Resolve only `resolvable` threads you actually addressed.

- **Fixed** → resolve after the fix is pushed and verified.
- **Answered / Ticket** → resolve only when the reviewer allowed that route (e.g.
  "fine as a follow-up ticket") **or the user asked you to resolve**. Otherwise
  leave it open with a clear closing question, and say why.
- **Disagree** → leave open for the reviewer to concede or reply.

Never resolve a thread to tidy away feedback you did not act on. Say in your report
that the reviewer can reopen any thread.

## 9. Leave the MR consistent

A review round changes facts other people read. After the push:

- Re-read the **MR description** and fix anything now wrong (what the guard covers,
  test counts, version, "QA verified"); add a short "Review round" note.
- Check the **new head's pipeline**, `has_conflicts`, and that blocking discussions
  now read as resolved.
- If the **Jira state or QA record** no longer matches the code, say so; add a
  one-line Jira comment only if the trail would otherwise mislead.
- Link any new ticket from the MR, and report its key and URL to the user.

## Guardrails

- Verify every claim against the code before agreeing or disagreeing.
- Quote acceptance criteria and business rules verbatim when calling something
  intended — a paraphrase is not checkable.
- One bucket per finding (split a mixed point), and no finding left unaddressed —
  questions and "just noting" remarks included.
- Never manufacture tickets, and never absorb out-of-scope work silently.
- Push before citing a SHA, and never force-push during an active review unless
  the reviewer has explicitly agreed to a rebase.
- Label evidence by grade; never present a code reading as a measurement.
- Do not claim a gate passed that did not cover your files.

## Revision notes

- **11 September 2026** — first version.
- **6 October 2026** — revised after resolving two threads on a product MR:
  added thread-splitting by kind (questions and
  remarks are findings), the *Answered* bucket and sub-finding splits, head-SHA
  anchoring and tool-output warnings, "fix the class", proving tests against the
  wrong fix, gate coverage honesty (ignored linters, piped exit codes, blame on
  type errors), no history rewrite during review, evidence grading for answers,
  resolve rules per bucket, and the post-resolution consistency step. Board-specific
  ticket rules were made conditional so the skill can generalise.
- **9 October 2026** — organisation specifics moved to the overlay; the rebase rule
  now matches the no-force-push guardrail (rebase before the review starts, or only
  with the reviewer's explicit agreement).
