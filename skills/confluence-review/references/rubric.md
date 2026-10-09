# Confluence Review Rubric

## Severity levels

- **Blocker** — acting on the document as written would build the wrong thing,
  break something, or is impossible (contradictory requirements, missing a
  section the work cannot start without, instructions that would cause damage).
- **Major** — a reader will very likely misunderstand or stall: ambiguous
  requirement with two reasonable readings, missing acceptance criteria,
  stale core claim, broken link on the critical path.
- **Minor** — friction, not failure: unclear ordering, duplicated content,
  minor inconsistencies, missing context a reader can recover elsewhere.
- **Nit** — style, tone, formatting. Never let these dominate the report.

## Dimension weighting by document type

| Dimension            | PRD / requirements | Design / ADR | Runbook / how-to | Reference |
|----------------------|--------------------|--------------|------------------|-----------|
| Completeness         | high               | high         | **critical**     | medium    |
| Internal consistency | high               | **critical** | high             | medium    |
| Ambiguity            | **critical**       | high         | **critical**     | medium    |
| Staleness            | medium             | medium       | **critical**     | high      |
| Broken references    | medium             | medium       | high             | high      |
| Structure            | medium             | medium       | high             | medium    |
| Unresolved comments  | high               | high         | medium           | low       |

Expected sections per type (missing ones are Completeness findings):

- **PRD**: problem/goal, in-scope & out-of-scope, actors/users, requirements
  with acceptance criteria, success metrics, open questions.
- **Design / ADR**: context, decision & alternatives considered, consequences
  / tradeoffs, affected systems, migration or rollout notes.
- **Runbook**: preconditions, exact ordered steps, expected output per step,
  failure handling, rollback, owner/escalation.

## Verify, don't assert

- A staleness finding needs evidence: the page's `LAST_MODIFIED`, a dated
  contradiction, or (when grounding) a Jira/code check you actually ran.
- A broken-link finding means you saw the reference fail or the target absent
  in the fetched data — not "this might not exist".
- Anything you could not check, phrase as "not verified", with what it would
  take to verify it.

## Report format

```markdown
# Confluence Review: <TITLE> (v<VERSION>, <LAST_MODIFIED>)

<one-paragraph verdict: what the doc is, who it serves, overall readiness>

## Blockers
- **<short title>** — <finding>. *(section: "<heading>", near "<quoted phrase>")*

## Major
- ...

## Minor
- ...

## Nits
- ...

## What's solid
- <genuine strengths — always included, keeps the review credible>

## Open questions for the author
- <numbered, answerable questions; each one unblocks a finding above>
```

Omit empty sections except **What's solid**, which is mandatory. If there are
no Blockers or Majors, open the verdict by saying the document is ready.
