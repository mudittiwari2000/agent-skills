---
name: prod-flag-ledger
description: Keep a ledger of every feature flag added in delivery work and which environments it is on, then, when the user shares release notes (a Confluence release-notes page, the generator's markdown, a tag or tag range, or pasted text) on a release date, work out which flags must be turned ON in production for that release and which are still waiting. Use whenever a story adds, renames or removes a feature flag (Split.io or any other provider), when the user says a flag was switched on/off in an environment, when they send release notes or say "we're releasing X today", or ask "which flags do I still need to turn on in prod?". Records and reports only; never toggles a flag.
---

# Prod flag ledger

The user releases code to production with its new feature flags **off**, then
turns each flag on by hand in the flag provider's dashboard once the code
carrying it is live. This skill makes sure no flag is forgotten:

1. **Record:** every flag a delivery workflow adds goes into the ledger the
   moment it is created, with its per-environment state.
2. **Release check:** given release notes, report exactly which flags the
   release ships that still need turning on in prod, with any preconditions.
3. **Update:** when the user turns a flag on (or off), record it and close the
   entry.

The skill never changes a flag's state in any provider. It reports, and the
user acts.

## Organisation overlay (optional)

Before starting, look for `${AGENT_SKILLS_OVERLAY:-~/.config/agent-skills/overlay}/overlays/prod-flag-ledger/profile.md`.
If it exists, read it, and any file it points to, before doing anything else.
It supplies what this skill leaves as placeholders (repo profiles, tracker and
CI tool names, environment access, house conventions) and may add steps.
For facts about the organisation the overlay wins; for method and guardrails
this file wins. Without an overlay, discover the values from the repo and the
user, and record what you learn where the skill says to.

## The ledger

A non-secret JSON file. Its location comes from the overlay, which may name
a config/secret helper to read and locate it through. Without an overlay, use
`$FLAG_LEDGER_FILE`; if that is unset, ask the user where to keep it and
suggest they export it. Read single values with `jq '<jq-path>' "$LEDGER"`.
Edit it with `jq` into a temp file and `mv` over the original, keeping mode
600. Never hand-write the file in place.

Entry shape (`.flags[]`):

| Field | Meaning |
| --- | --- |
| `flag` | Exact flag key as created in the provider, e.g. `new_listing_page_toggle`. |
| `provider` | `split` today; any provider name works. |
| `repo`, `apps[]` | Where the code that reads the flag lives. `apps` scopes a monorepo release. |
| `jira`, `mr` | Delivering ticket and MR (IID or URL). `mr` is null until the MR exists. |
| `merge_commit` | Commit on the default branch that first carries the flag check. Null until merged; filled in at the first release check that can see it. |
| `first_version` | First release version/tag containing `merge_commit` (e.g. `<app>-v1.4.2`). |
| `environments.<env>` | `{state: on/off/unknown, as_of: YYYY-MM-DD, source: user/observed}`. Only the user or a read of the provider sets these. |
| `prod_preconditions[]` | Anything that must be true before turning it on in prod: another flag on first, a data backfill, a cutover. |
| `status` | `pending_prod`, then `on_in_prod`, or `retired` (flag code removed) / `abandoned` (MR closed unmerged). |
| `history[]` | Dated events: added, env changed, shipped in a release, retired. |

Dates are absolute (`YYYY-MM-DD`), never "today".

## Repo profiles

Repo-specific facts live here (the overlay holds the real rows). For a repo not listed, discover the values (the
flag-constant file from the diff that added the flag, the tag pattern from
`git tag --sort=-creatordate | head`) and add a row before relying on it.

| Repo | Flag registry in code | Release tag pattern | Release notes source |
| --- | --- | --- | --- |
| `<group>/<project>` | `packages/<shared-pkg>/src/constants/feature-flags.ts` (constants), plus any app-specific registries your flag-adding workflow names | `<app>-v<version>`, e.g. `<app>-v1.4.2` | Repo's release-notes generator: wiki page plus local markdown, grouped by ticket |

## Mode 1: Record a flag (when a flag is added)

Trigger: any workflow (your delivery workflows, manual edits)
adds a flag key to code, or the user says they created one.

1. Collect `flag`, `provider`, `repo`, `apps`, `jira`, a one-line `summary` of
   what ON does and what OFF does, and the current per-environment state.
   Ask the user for any environment state you don't know. Never assume a
   dashboard state.
2. If an entry for the same `flag` + `repo` already exists, update it rather
   than adding a duplicate.
3. Record `prod_preconditions` you can see from the work (e.g. "prod host not
   yet served by this app", "needs flag X on first").
4. Append a `history` event and write the ledger.
5. Tell the user in one line: the flag key, its env states, and that it's
   tracked for prod.

Also record a flag rename (new entry, old one `retired`) and a removed flag
(`retired` once the removal reaches prod).

## Mode 2: Release check (user shares release notes)

Inputs, in any form:
- **Confluence release-notes URL:** read it, e.g. via the Atlassian tools or
  the release-notes generator's own wiki API access.
- **The generator's local markdown file.**
- **A tag or tag range:** `<app>-v1.4.2`, or `v1.4.0 → v1.4.2`.
- **Pasted text.**

From the input, resolve the **repo, app(s), release tag (the `to` end) and,
when present, the previous prod tag (the `from` end)**. If the notes give only
a date or ticket list, ask for the tag.

For every ledger entry with `status: pending_prod` in that repo whose `apps`
overlap the release:

1. **Fill in missing merge data.** If `merge_commit` is null and `mr` is set,
   read the MR (GitLab MCP or `glab api`). If it's merged, store
   `merge_commit`. If `mr` is null, find the MR by the Jira key in branch names
   or titles.
2. **Decide whether the release ships the flag's code.** The authoritative
   test is git, not prose:
   `git fetch --tags origin && git merge-base --is-ancestor <merge_commit> <release-tag>`.
   Cross-check that the flag key is really in the tagged tree with
   `git grep -n "<flag>" <release-tag> -- <registry path and app paths>`.
   - Ancestor and present: **ships in this release.** If the previous prod
     tag is known and already contains it, the code shipped in an **earlier**
     release, and the flag is overdue rather than new.
   - Not an ancestor: **not in this release.**
   - Merged but the key is absent from the tree: flag it as an
     inconsistency. The flag was renamed or reverted, so check before
     advising.
   - The Jira key appears in the notes but git says no (or the reverse):
     trust git, and mention the mismatch.
3. **Read preconditions.** List them unresolved unless the user or evidence
   says they're met. Don't advise turning a flag on while a precondition is
   unmet. Say what's blocking instead.
4. **Order matters.** If one flag depends on another, list the dependency
   first.

Report, as a short table per bucket:

- **Turn ON in prod after this release deploys:** flag key, ticket, what
  ON does, current dev/stage state, preconditions met (yes or what's missing).
  A flag that is OFF on stage is a warning: it was never verified on stage.
- **Already shipped earlier, still OFF in prod (overdue):** same columns,
  plus the first version that carried it.
- **Tracked but not in this release:** flag and ticket only, one line each.
- **Inconsistencies:** anything from step 2 that needs a human look.

Then update the ledger: set `first_version` for flags that ship, and add a
`history` event `shipped in <tag>`. Do **not** mark anything `on_in_prod`
until the user confirms they switched it on.

## Mode 3: Update state

When the user says a flag was turned on or off in an environment: set
`environments.<env>`, add a `history` event, and set `status: on_in_prod` when
prod is ON. When asked "which flags are pending?", list `pending_prod` entries
grouped by repo/app, oldest first, with their preconditions.

## Guardrails

- Never toggle, create or delete a flag in any provider. Report only.
- Never infer an environment state. Only the user, or a read-only query of
  the provider made with the user's credentials, sets it.
- Git ancestry decides "is it in the release"; release-notes prose only
  corroborates it.
- Don't drop an entry because a release check didn't see it. Entries leave
  `pending_prod` only through `on_in_prod`, `retired` or `abandoned`, each
  with a dated history event.
- Keep the ledger non-secret: no SDK keys or targeting rules containing
  customer data.
