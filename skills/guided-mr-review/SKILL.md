---
name: guided-mr-review
description: Guide the user through reviewing a GitLab merge request themselves, instead of reviewing it for them. Produces a one-screen Review Brief listing what has already been verified (so they can skip it) and the 2–5 places that need human judgement, ranked by risk. Each place gets the question to answer, where to look and what each answer means for approval. With --walk, goes through those places one at a time, records the user's verdicts and drafts their review comments in their voice. Use when the user says "guide me through this MR", "what should I look at in !123", "walk me through this review", "help me review this", "what do I need to check before approving", or invokes /guided-mr-review with an MR URL, IID or branch. Reuses mr-review's fetch and verification. Never approves, posts or comments unless the user explicitly asks.
argument-hint: <MR URL | IID | branch> [--walk]
metadata:
  tags: [code-review, GitLab, reviewer, guidance]
  related_skills: [mr-review, mr-comment-resolution, scope-audit]
---

# Guided MR review

`mr-review` reviews an MR **for** the user and hands back findings. This skill
helps the user review it **themselves**: it does the mechanical work, proves
what it can, and points their attention at the few places where a human
decision is needed. The user stays the reviewer. This skill is their
preparation and their notes.

Why it is shaped this way:

- **Order drives attention.** Reviewers comment most on the files they see
  first, and the default alphabetical order is rarely the useful one. So stops
  are ranked by risk, not by path.
- **Cross-file problems are where humans miss things.** Defects that only show
  when two places are read together depend on working memory. Every stop names
  its partner location explicitly.
- **Pre-judging breeds rubber-stamping.** Show a verdict up front and people
  tend to accept it. So a judgement stop is a *question with evidence*, not an
  answer. Only defects you have verified are stated as defects, and they sit in
  their own list.

## Organisation overlay (optional)

Before starting, look for `${AGENT_SKILLS_OVERLAY:-~/.config/agent-skills/overlay}/overlays/guided-mr-review/profile.md`.
If it exists, read it, and any file it points to, before doing anything else.
It supplies what this skill leaves as placeholders (repo profiles, tracker and
CI tool names, environment access, house conventions) and may add steps.
For facts about the organisation the overlay wins; for method and guardrails
this file wins. Without an overlay, discover the values from the repo and the
user, and record what you learn where the skill says to.

Also apply `mr-review`'s overlay profile (`overlays/mr-review/profile.md`) when
present. Its repo rows tell you how to run a repo's checks, and they are the
main thing this skill needs. Its own profile is only for reviewer-side
conventions, such as where to see a change running (which environment, which
test account) or the house wording for review comments.

## Inputs

- An MR URL, IID or branch, or nothing to use the current working tree (same
  forms `mr-review` accepts).
- `--walk` (or "walk me through it"): after the brief, go through the stops
  interactively. Without it, stop after the brief and offer the walk in one
  line.

## Depends on `mr-review`

This skill uses the sibling `mr-review` skill's scripts and method. Set
`MR_REVIEW_DIR` to the directory holding `mr-review/SKILL.md`, normally
`$SKILL_DIR/../mr-review`, where `$SKILL_DIR` is this skill's directory
(resolve symlinks). If it is missing, tell the user to install `mr-review` from
the same repo and stop.

## Workflow

### 1. Fetch

```bash
bash "$MR_REVIEW_DIR/scripts/fetch_mr.sh" "<MR-URL | IID | branch>"
```

Record every printed field exactly as `mr-review` step 1 describes (`WORKTREE`,
`DIFF_FILE`, `DESCRIPTION_FILE`, `BASE_SHA`, `HEAD_SHA`, `HEAD_LABEL`,
`WEB_URL`, `EXTERNAL_POSTING_ALLOWED`, …). Work only inside `$WORKTREE`.

### 2. Ground and verify, as mr-review does

Read `$MR_REVIEW_DIR/SKILL.md` steps 2–4, and from `references/rubric.md` the
grounding rule, the dimensions and "verify, don't assert". Skip its severity
scale and report format; this skill has its own output. Do the work in full:
- orient on the repo rules;
- ground every change in its callers and consumers;
- run the repo's checks, baselining any failure at `BASE_SHA`;
- prove the MR's new tests fail on base;
- check mergeability against the live target branch;
- check the description's claims against the real call sites.

The brief is only as trustworthy as this step. Do not shorten it because the
output is shorter. You also inherit mr-review's duty to add or correct a
repo-profile row when you learn something a future review would otherwise have
to rediscover. Rows for organisation repos go in the overlay.

Keep three lists as you go:

- **Verified:** each check you ran, the exact command and its result. Also each
  question you settled by reading code, as a fact with its `file:line` (for
  example "no global `h2` styles: searched `apps/*/**/*.css`").
- **Defects:** problems you have proven, with `file:line` and the trigger.
  These go in the brief as facts. A code comment or MR-description claim that
  the code contradicts is a proven defect too: cite both the claim and the code
  that disproves it.
- **Evidence gaps:** places where the author's stated evidence (tests,
  screenshots, browser runs) exercised a different path or shape from the one
  production uses. Each is a "Not verified" line, and also a stop when the
  path at stake is risky.
- **Open:** anything whose correctness depends on intent, product behaviour,
  design or environment that the code cannot settle, plus anything risky you
  could not verify. These are the candidates for judgement stops.

### 3. Choose the judgement stops

A stop is a place where **the user's judgement changes the review outcome**.
Pick from the Open list. Something qualifies when any of these holds:

- **Intent:** the code is correct either way; only the author or product owner
  knows which way is wanted. Example: a shared component's change reaches
  callers the MR description never mentions.
- **Cross-file effect:** the impact shows only when a changed line is read
  alongside a distant one, such as a definition and a caller, a config and its
  consumer, or a migration and the code that reads it.
- **Unverified risk:** behaviour that matters but that no check exercised.
  Examples: a visual change checked only in jsdom, a path only reachable in an
  environment you could not run, or a security-sensitive branch with no test.
- **Blast radius:** shared or app-wide code, auth, data or migrations, infra,
  anything hard to reverse.

Not stops: anything on the Verified list; style and naming nits; findings the
user could not act on. Proven defects go in their own section, not as stops.
Two stops may share a line when they ask different questions (say, one about
intent and one about unverified behaviour); merge only stops that ask the same
question.

Keep **2–5 stops**, and at most 4 when there are proven defects. If more qualify, merge stops that ask the same question and
drop the lowest-risk ones (mention how many you dropped). If none qualify, say
so plainly. "Nothing here needs your judgement beyond a skim" is a valid
result.

Rank by risk: blast radius × how hard it is to reverse × how unverified it is.
Most risky first.

For each stop write:

- **Where:** the primary `file:line`, plus the partner location(s) that make it
  matter.
- **Why you:** one line on why a human must decide this, and why the code
  cannot settle it.
- **Question:** one question the user can answer yes or no, or with a short
  choice. It must not hint at the answer you would give.
- **Look at:** at most two things to open or run to answer it. Name any
  prerequisite, such as an environment, a test account or a viewport. The
  overlay may say where a change can be seen running.
- **If yes / if no**, or **If A / If B** for a short-choice question: what each
  answer means for the review, taken from the outcome list in the brief format.
  You may add one qualifier (for example "leave a comment, or ask the author
  first if it should match desktop").

### 4. Emit the Review Brief

Use the exact format in [references/brief-format.md](references/brief-format.md).
Aim for about 40 lines, defects list included; its budget rules say what to
compress. Brief-only mode shows anchors, not code. Code is shown in the walk,
or when the user asks for it.
Print it, and save the exact text to `$WORKTREE.brief.md`.

End with the **Approve if** line: the condition for approval stated in terms
of the stops, for example "approve if 1 is intended and 3 is fixed". For a stop
that is a visual or on-device check, the condition is that it "passes your
look". Then, when
`--walk` was not given, offer the walk in one line.

### 5. Walk (only with --walk, or when the user asks)

Take the stops in brief order. For each one:

1. Show the primary hunk with enough context to read it (about 40 lines at
   most) and the partner lines, both with `file:line`. Then ask the stop's
   question.
2. Ask for the user's verdict. Use your structured question tool when the
   harness has one, otherwise ask in plain text. Offer these options:
   - **OK:** fine as it is.
   - **Concern:** something should change.
   - **Question for author:** the user can't decide without the author.
   - **Skip:** not my call, or not now.
3. For Concern or Question, take the user's own words. Ask one follow-up only if
   the comment would otherwise be unclear to the author.
4. If the user asks what you think, tell them, with your evidence. Never give
   your view before they answer, unless they ask.

After the last stop, print:

- a table with one row per stop: number, location, verdict and a one-line note;
- **draft comments** for every Concern and Question. Write them in the user's
  voice:
  - short, specific and anchored to `file:line`;
  - labelled `question:` or `suggestion:`, or `blocking:` only when the user
    called it blocking;
  - polite and non-accusatory;
  - plain text with no blockquote markers, so they copy cleanly.
- the proven defects, each as a ready-to-post comment the user can choose to
  include;
- the **verdict the answers imply**: approve, approve with comments, or request
  changes. State that the call is the user's.

Save the walk record to `$WORKTREE.walk.md`.

### 6. Acting on GitLab — only when explicitly asked

Nothing in this skill posts, approves or resolves anything unless the user asks
in so many words. Require `EXTERNAL_POSTING_ALLOWED=true` for every action
below.

- **Post the comments as one MR note:** write them to a file and post it with
  `python3 "$MR_REVIEW_DIR/scripts/gitlab_review.py" post --mr-url "$WEB_URL"
  --report <file> --head-sha "$HEAD_SHA"`. That helper checks the live head
  first. On `STALE_REVIEW`, stop and offer to re-run against the new head.
- **Post inline comments:** ask once to confirm the list. Then, for each
  comment, take `base_sha`, `start_sha` and `head_sha` from the MR's
  `diff_refs` (`glab api projects/:id/merge_requests/<iid>`) and create a
  discussion with a text `position` (`new_path`, `new_line`, or
  `old_path`/`old_line` for removed lines). Report each created discussion ID.
  If a position is rejected, fall back to the single note for that comment.
- **Approve:** run `glab mr approve <iid> -R <project>` only when the user says
  to approve. Never infer approval from an OK walk.

### 7. Clean up

```bash
bash "$MR_REVIEW_DIR/scripts/fetch_mr.sh" --cleanup "$WORKTREE"
```

This keeps `$WORKTREE.brief.md` and `$WORKTREE.walk.md`.

## Rules

- Every stop and every verified fact is anchored to `file:line` in `$WORKTREE`.
- A check you did not run is "not verified", never assumed green.
- Questions never lead the answer. Your view comes only when asked, or after
  the user's verdict.
- Stay inside the MR's scope. A finding about shared code the MR didn't
  change is a note for a follow-up ticket, not a stop.
- Do not inflate. Fewer, sharper stops beat a long checklist, and "nothing
  needs you here" is a fine outcome.
- The worktree is read-only. Never push, amend or approve on the user's behalf
  without an explicit request.
