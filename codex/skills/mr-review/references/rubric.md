# Review rubric

Read this after fetching the MR. It defines what to check, how to ground each
finding, how to rank severity, and the exact report shape to emit.

## Grounding rule (non-negotiable)

Every finding must be justified against the **real repository state at the MR
HEAD** in `$WORKTREE`, not against the diff alone. Before writing any finding:

- Open the changed file in `$WORKTREE` and read the whole function/class it lives
  in, plus its imports — the diff hunk hides surrounding context.
- Trace each changed symbol across the whole repo: its definition, **every call
  site**, tests, types/interfaces, config, env vars, DB migrations, and generated
  code. Use `git grep -n` inside `$WORKTREE`.
- Confirm a claimed defect can actually happen: find an input or call path that
  reaches it. If you cannot, downgrade it to a question, not a defect.

A finding with no `file:line` anchor in the current tree is not admissible.

## Dimensions (check every one)

1. **Correctness** — logic errors, off-by-one, wrong operators, unhandled `null`/
   `undefined`, race conditions, incorrect async/await, broken invariants.
2. **Impact / regressions** — does a changed signature, return shape, or behavior
   break an existing caller, test, or consumer found elsewhere in the repo?
3. **Security** — injection (SQL/command/template), authz/authn gaps, secrets in
   code, unsafe deserialization, SSRF, path traversal, missing input validation,
   overly broad CORS/permissions.
4. **Error handling & resilience** — swallowed errors, missing timeouts/retries,
   partial failure states, unhandled promise rejections.
5. **Data & migrations** — non-idempotent or destructive migrations, missing
   backfills, nullable/constraint mismatches with code.
6. **Tests** — is the new behavior actually covered? Do existing tests still hold?
   Are tests asserting real behavior or trivially passing?
7. **Conventions** — violations of the repo's `AGENTS.md` / `CLAUDE.md` rules,
   local patterns, naming, import style, lint/type rules.
8. **Maintainability** — dead code, duplication that ignores an existing helper,
   needless complexity, leaky abstractions. Report only if concrete.

## Verify, don't just assert

When feasible and cheap, confirm claims by running the repo's own checks inside
`$WORKTREE` (read the repo's `AGENTS.md`/`CLAUDE.md`/`package.json`/`Makefile`
for the real commands): type-check, lint, and the specific tests touching the
changed area. Note in the report what you ran and the result. Never invent a
green result — if you did not run it, say "not verified".

## Severity ranking

- **Blocker** — will break prod, lose/corrupt data, or is a real security hole.
- **High** — likely bug or regression under a realistic path; wrong behavior.
- **Medium** — narrow-condition bug, missing test for risky logic, convention
  break with real consequences.
- **Low / Nit** — style, naming, minor cleanup. Group these; do not pad.

Report findings most-severe first. If nothing is a Blocker/High, say so plainly
rather than inflating nits.

## Report format (emit exactly this)

```
# MR Review — <title or branch>
Repo: <repo>  •  Base: <target>  •  Head: <sha short>  •  Files: <n>

## Verdict
<Approve / Approve with nits / Request changes>  — one-sentence why.

## Verification run
- <command> → <pass/fail/skipped + why>

## Findings
### [Blocker|High|Medium|Low] <one-line title>
- Where: `path/to/file.ext:line` (+ related `other.ext:line` if impact is remote)
- What: precise description of the defect.
- Why it matters / how it triggers: the concrete path or input.
- Fix: the smallest correct change (sketch, not necessarily full code).

## Open questions
- <things you could not resolve from the code; ask the author>
```

Keep each finding tight. No generic advice ("consider adding tests") without a
specific target and reason.
