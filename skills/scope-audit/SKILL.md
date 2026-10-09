---
name: scope-audit
description: Unbiased scope check of a feature branch or MR before review. Spawns a FRESH background agent that sees only the story's acceptance criteria/rules, the user's explicit requests and the diff, never the implementer's reasoning, and classifies every changed hunk as required, supporting, not required or dead under current config. It also lists ACs the diff doesn't cover. Use as a sub-step whenever a feature is being developed (inside your delivery workflow or by hand): before opening or un-drafting an MR, after applying review/QA fixes, or when the user asks "is everything in this MR needed / in scope?". Read-only; reports, never edits.
---

# Scope audit

A feature MR should carry exactly what its story requires. Anything extra costs
review time and hides bugs. Hardening of shared code, "while I'm here" refactors
and review nice-to-haves that change shared behaviour are the usual culprits.

The implementer can't judge this fairly: they know *why* every line felt
necessary. So the check runs in a **fresh background agent with a bias
firewall**. It gets the requirement sources and the diff, nothing else, and
reads the code itself.

## Organisation overlay (optional)

Before starting, look for `${AGENT_SKILLS_OVERLAY:-~/.config/agent-skills/overlay}/overlays/scope-audit/profile.md`.
If it exists, read it, and any file it points to, before doing anything else.
It supplies what this skill leaves as placeholders (repo profiles, tracker and
CI tool names, environment access, house conventions) and may add steps.
For facts about the organisation the overlay wins; for method and guardrails
this file wins. Without an overlay, discover the values from the repo and the
user, and record what you learn where the skill says to.

## When to run

- Before opening an MR, or before moving a draft MR to ready.
- After applying code-review / QA / Codex findings. This is where scope creep
  usually enters.
- When the user asks whether the changes are needed or in scope.

## Inputs (collect these, then stop adding context)

| Input | Source | Notes |
| --- | --- | --- |
| Repo, worktree path, base ref | `git` in the worktree | Base is the MR target, e.g. `origin/main`. Fetch it first. |
| Story requirements, verbatim | Your tracker's issue-fetch tool or the spec file | Copy the AC, Rules and Scope / Out-of-scope sections word for word. Don't summarise. |
| Explicit user requests | The conversation | Only things the **user** asked for, quoted, with date. E.g. "add a Split flag", "fix QA finding F-2". Not things you or a reviewer proposed. |
| Repo conventions that force changes | The repo profile table below, or CLAUDE.md | E.g. "every MR bumps the app patch version". |

**Bias firewall: never pass:**
- your design rationale or plan;
- review or QA findings and your responses to them;
- earlier verdicts;
- which parts you think are risky;
- the conversation history.

The agent must form its own view from the requirements and the code. If it
needs to understand a mechanism, it reads the code.

## Repo profiles

| Repo | Base ref | Changes forced by convention |
| --- | --- | --- |
| `<group>/<project>` | `origin/main` | E.g. patch-version bump of each touched `<app>` in `package.json` plus the matching `package-lock.json` entry; every new feature-flag constant also gets a local mock entry, because local dev reads only mocks. |

Put every such convention in the requirements file. An auditor that doesn't know a convention will flag its hunks as not required. That happened on the first real run: a required local mock-flag entry was flagged.

**Verdicts are input, not orders.** Before removing a hunk, check that removing it doesn't create a defect or break a convention or a local workflow. Record each keep-against-verdict with its reason in the hand-off.

For an unlisted repo, read its CLAUDE.md for "every MR must…" rules and add a
row (in the overlay profile when one is installed).

## Procedure

1. `git fetch origin <base>` in the worktree, and note the HEAD SHA.
2. Write the requirement sources (verbatim story sections, user requests,
   convention rows) to a file in the scratchpad.
3. Spawn the auditor with the Agent tool: `subagent_type: general-purpose`,
   `run_in_background: true`. Use the prompt below with the paths filled in.
   Never use a fork: a fork inherits your context, which defeats the point.
4. When it returns, act on the verdicts, not your own prior view. Remove
   "not required" and "dead" hunks unless the user decides otherwise. Move
   them to MR follow-ups with an owner. Report "AC not covered" gaps to the
   user.
5. If code changed, re-run tests and QA: the tested tree has moved. Then run
   this audit again until it comes back clean.

## Auditor prompt (template)

```
You are an independent scope auditor. You did not write this code and have no
stake in it. Read-only: do not edit, commit, push, or write to Jira/GitLab/Slack.

Worktree: <path>   Base: <base ref>   HEAD: <sha>
Requirement sources (the ONLY things that justify a change): <path to file>

Task:
1. Run `git diff <base>...HEAD` (also `--stat`). Read every changed hunk, and
   open surrounding code where you need it to understand what a hunk does.
2. Classify every hunk (group trivially related hunks) as exactly one of:
   - REQUIRED: needed to satisfy a cited AC / Rule / explicit user request.
     Cite it (e.g. "AC-1", "Rule 4", "user request 2"). Explain in one line
     how the hunk serves it.
   - SUPPORTING: tests that exercise REQUIRED code, or a repo-convention change
     (cite the convention). A test of NOT-REQUIRED code is NOT-REQUIRED.
   - NOT REQUIRED: no citation applies. Includes refactors, reformatting,
     hardening or behaviour changes in shared code beyond what an AC needs,
     extra options or props nobody asked for, and fixes to pre-existing
     behaviour.
   - DEAD: code that cannot run under the current configuration (e.g. a branch
     that only fires for rows/flags that don't exist). Say why it can't run,
     and list every entry point you checked: routes, every middleware branch
     including header-driven rewrites (e.g. a routing header), direct internal
     paths, other callers. A guard that only looks unreachable through the
     main path is not DEAD.
   If you can't find a citation, the answer is NOT REQUIRED. Don't invent a
   justification.
3. Flag any change to a shared, pre-existing file whose blast radius exceeds
   the story, i.e. it alters behaviour for pages or callers the story never
   mentions, even if some AC benefits. Say which callers are affected.
4. List each AC / Rule / user request that NO hunk satisfies (a coverage gap).
5. Prefer the narrowest alternative: where a REQUIRED need is met by changing
   shared code, say whether it could be met in the new code path instead.

Report:
- a table: file, line range, class, citation or reason;
- the shared-file blast-radius list;
- coverage gaps;
- a one-line verdict: CLEAN, or N hunks to remove.
Facts only. Quote code where it matters.
```

## Guardrails

- The auditor is read-only, and so is this skill. Changes go back through the
  normal implementation and test path.
- Never weaken the firewall to "help" the auditor. If it misreads something,
  that is a signal the code or story is unclear.
- An explicit user request outranks the story, but only when the user actually
  said it. Record the quote.
