---
name: confluence-review
description: Review a Confluence document (PRD, design doc, runbook, ADR, spec) for completeness, correctness, ambiguity, staleness, and structure, and emit a severity-ranked report. Use when the user shares an atlassian.net/wiki URL or Confluence page ID, names a page to review ("review the X design doc"), or asks to check a Confluence spec before refinement or implementation. Doc-only by default; optionally grounds claims against Jira issues and local repos under ~/dev/repos when explicitly asked. Local report by default; posts a comment back to the Confluence page only when explicitly requested and only after verifying the page version is still current.
---

# Confluence Document Review

Review a Confluence document as a demanding, constructive reader: someone who
must implement, operate, or approve what the document describes. The goal is a
severity-ranked report the author can act on — not a rewrite.

Credentials are resolved by `scripts/confluence_api.py` through the
agent-skills secrets chain (`~/.config/agent-secrets/.env`, falling back to
`~/.hermes/profiles/pegasus/.env`); credential values must never be printed.

## Workflow

### 1. Resolve the document

- Given a URL or numeric page ID, go straight to step 2.
- Given a title or topic, search first and confirm before reviewing:

```bash
python3 ~/.codex/skills/confluence-review/scripts/confluence_api.py search "<title or CQL>"
```

If more than one plausible match comes back, list the candidates (id, title,
space, last modified) and ask the user which one. Never guess between
similarly-named pages.

### 2. Fetch the document

```bash
python3 ~/.codex/skills/confluence-review/scripts/confluence_api.py get "<URL or page-id>"
```

This writes `page.md` (Markdown), `page.storage.xml` (raw source), and
`meta.json` into `~/.codex/tmp/confluence-review/<id>/` and prints `PAGE_ID`,
`TITLE`, `VERSION`, `LAST_MODIFIED`, `URL`, the file paths, `REPORT_FILE`, and
the child-page and attachment lists. Record `VERSION` — it gates any later
posting. Then fetch the discussion:

```bash
python3 ~/.codex/skills/confluence-review/scripts/confluence_api.py comments "<page-id>"
```

### 3. Read and classify

Read `page.md` **end to end** before judging anything. If the Markdown looks
mangled anywhere (complex macros, layouts), consult `page.storage.xml` for
that section rather than reviewing a conversion artifact.

Classify the document type — PRD / requirements, design doc / ADR, runbook /
how-to, or general reference — and say which you assumed; the rubric weighs
dimensions differently per type. Note the audience the document claims or
implies.

### 4. Review across all dimensions

Follow `references/rubric.md` (read it now) for the dimensions, severity
levels, and the exact report format. Core dimensions:

- **Completeness** for the doc type (e.g. a PRD without acceptance criteria
  or out-of-scope section; a runbook without rollback steps).
- **Internal consistency** — numbers, names, diagrams, and sections that
  contradict each other.
- **Ambiguity** — requirements a developer and a QA could read differently;
  undefined terms, "should/could" where "must" is meant, missing actors.
- **Staleness** — `LAST_MODIFIED` vs what the page describes; references to
  systems, teams, or decisions known to have changed.
- **Broken references** — links, `[[page links]]`, `[JIRA:KEY]` macros,
  attachments referenced but not present.
- **Structure & readability** — ordering, duplication, wall-of-text sections.
- **Unresolved discussion** — open inline/footer comments that contradict or
  gate the content; flag decisions the doc states as settled that comments
  dispute.

### 5. Optional grounding — only when explicitly asked

If (and only if) the user asks to ground the review (e.g. "check it against
Jira", "verify against the code", `--ground`):

- Extract Jira keys with `\b[A-Z][A-Z0-9]+-\d+\b` (case-insensitive, then
  uppercase). Verify each via Jira REST (same credential chain,
  `GET <base>/rest/api/3/issue/<KEY>?fields=status,summary`) and flag keys
  that don't exist, are Done while the doc calls them planned, or whose
  summary contradicts the doc.
- Extract file paths, service names, endpoints, and repo names; check them
  against `~/dev/repos` (`ls`, `git grep`) and flag references
  to code that doesn't exist or has clearly diverged.
- Grounding findings must state exactly what was checked and how; anything
  not checked is reported as "not verified", never as fact.

### 6. Emit the report

Produce the severity-ranked report defined in `references/rubric.md`. Anchor
every finding to a section heading (and quote a short phrase so the author can
locate it). Identify the reviewed page as `TITLE (vVERSION, LAST_MODIFIED)`.
Print the report and save the exact emitted Markdown to `REPORT_FILE`
(`~/.codex/tmp/confluence-review/<id>.review.md`) — this persistent file is
the sole input to the posting step. Do not post anywhere unless explicitly
requested.

### 7. Post to Confluence — only when explicitly asked

If (and only if) the user asks to post the review to the page:

```bash
python3 ~/.codex/skills/confluence-review/scripts/confluence_api.py post-comment \
  "<page-id>" --report "<REPORT_FILE>" --reviewed-version <VERSION>
```

The helper verifies the live page version first and duplicate-protects with a
report marker. If it prints `STALE_REVIEW`, stop: fetch and review the new
version before posting. Use `--allow-stale` only when the user explicitly
asks to post the older review despite that warning; use `--repost` only when
they explicitly request a duplicate. Report whether it printed
`POSTED_COMMENT_ID` or `SKIPPED_DUPLICATE`. On credential or permission
errors, return the sanitized error — never claim success or fall back to
browser automation.

### 8. Clean up

```bash
python3 ~/.codex/skills/confluence-review/scripts/confluence_api.py cleanup "<page-id>"
```

Cleanup removes the fetched files but deliberately preserves
`<id>.review.md` as the durable artifact. Remove it only if the user asks.

## Rules

- Never report a finding you can't anchor to a real section/phrase of the
  fetched page. No memory-of-the-doc reasoning.
- Distinguish fact from judgment: staleness and grounding claims require the
  checks in steps 4–5; style opinions are Nits.
- Don't inflate nits into blockers. If the document is solid, say so and list
  what makes it solid.
- Read-only by default: never edit the page; posting a comment requires an
  explicit user request for that destination.
- Never print credential values or Authorization headers.
