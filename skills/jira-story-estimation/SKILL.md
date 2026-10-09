---
name: jira-story-estimation
description: Estimate or re-estimate JIRA stories so the number reflects the ticket's own acceptance criteria and the real codebase — not a design mockup, not the ticket's own claims about what already exists. Use when asked to estimate, size, story-point or re-estimate one or more JIRA tickets, when a design or prototype has landed and estimates need revisiting, when a backlog's points are suspected of being wrong, or when fanning estimation out across subagents. Covers scope discipline, verification against the real repos and measured data, the adversarial second pass, and writing the number back with an audit trail.
---

# Estimating a JIRA story

An estimate is a claim about **how much work this ticket's acceptance criteria
require**, given the code that exists today. Everything below exists to stop the
number drifting away from that claim.

The failure modes this prevents, all observed in real sessions: pricing a design
instead of the ticket; charging one ticket for a sibling ticket's scope; taking
"this already exists" at face value when it exists in a different repository;
assuming a field exists, or assuming it doesn't; and running a second opinion
that manufactures disagreement instead of finding error.

## Organisation overlay (optional)

Before starting, look for `${AGENT_SKILLS_OVERLAY:-~/.config/agent-skills/overlay}/overlays/jira-story-estimation/profile.md`.
If it exists, read it, and any file it points to, before doing anything else.
It supplies what this skill leaves as placeholders (repo profiles, tracker and
CI tool names, environment access, house conventions) and may add steps.
For facts about the organisation the overlay wins; for method and guardrails
this file wins. Without an overlay, discover the values from the repo and the
user, and record what you learn where the skill says to.

## The one rule

**Estimate the ticket. A design is a rendering reference, not a scope source.**

A design shows *how* the thing named in the ACs should look. It does not
authorise work the ACs do not ask for. When the design shows something the ACs
do not, that work belongs to a sibling ticket or to no ticket — never silently
to the one in front of you.

This is the single largest source of over-estimation. In real backlog audits it
has accounted for most of the over-estimated stories, and correcting it shrinks
the backlog substantially. The sharpest form: a ticket whose business rules
*explicitly exclude* what was charged for (hypothetically, a rule saying a menu
has "exactly one option" while the design shows three). The design showed
otherwise and the design won. That is the mistake. (The overlay may carry
worked examples.)

When ticket and design conflict, **estimate the ticket as written** and raise
the conflict with the BA. Do not silently pick one.

## 1. Gather before you judge

- Fetch the **current** description and **all** comments. Read ACs, business
  rules and scope, not just the summary.
- A prior estimation comment is a **claim to test**, not a fact to inherit.
- Check `status` first. Do not re-point work that is in progress or in review —
  it invalidates its own audit trail.
- **`updated` timestamps lie.** Boards get bulk-edited; a single bulk edit can
  touch dozens of tickets in sequence (stripping title prefixes, say), making
  the timestamp useless as a change signal. To detect real scope change, diff the current AC
  text against what the stored audit comment says it assessed.
- Titles get edited. Re-read rather than trusting memory of the ticket.

## 2. Build the AC inventory first — before any number

List every AC by number with a one-line verdict grounded in real code:

```
AC1 — passes today: <file:line>
AC2 — small change: <what, and what it reuses>
AC3 — real build: <why nothing exists>
AC4 — blocked: <the specific missing field/route/decision>
```

**Every point you charge must trace to a named AC.** If you cannot name the AC,
it does not count. Write the inventory before choosing the number, not after —
reversing the order lets the number drive the evidence.

## 3. Verify, don't infer

**Check which repository owns a cited path.** Tickets routinely say "this
already exists today" while citing a file in the legacy system being replaced.
That is a *port* — a build — not a no-op. Only paths in the repo that actually
ships count as existing. Check out the sibling repos and grep them; never
reason about a repo you have not opened.

**Grep the API source before claiming a field is missing or present.** Two
opposite errors, both seen: declaring a field absent when the search index
carried it (present in the index, missing only from the service's response
type — a small change, not a data-platform request), and assuming a field
existed when nothing in the API had it (a `grep -rni "<field>"` across the whole
API returns zero hits).

**Distinguish headline coverage from per-field population.** Hypothetically,
"20% of records have performance data" reads as sparse, yet within those
records the individual columns may be 70–90% populated. Estimating off the headline figure misprices the
work and misjudges whether it can be demonstrated at all.

**Verify the load-bearing claim specifically.** If one fact carries the whole
estimate, check that fact directly — run the query, read the mapping, execute
the library call. One agent disproved a claimed "axis model change" cost by
running the charting library against a real config; that single check moved the
estimate a whole band.

## 4. Attribute everything out of scope

Maintain an explicit `outOfScope` list. For each element the design or your
instinct wants to charge for, but the ACs do not ask for:

- name the **sibling ticket key** that owns it, or
- mark it **unstoried** and flag that it needs a ticket,
- and state plainly that it **did not affect the number**.

This is the mechanism that stops double-counting. Without it, one ticket was
charged for two siblings' scope that was already separately estimated — the same
work priced three times. Making the attribution mandatory and explicit is what
caught it.

Also out of scope, and not chargeable here:
- **Restyles and re-skins no AC asks for.** A design being visually different
  from production is not this ticket's work unless an AC says so.
- **Sequencing.** "The section container may not exist yet" is a dependency
  note, not build cost.
- **Thin data**, where the team builds ahead of data and gates on empty. Price
  the component plus its empty-state; report coverage separately under
  demonstrability. Thin data changes what can be *demoed*, not what it costs.

## 5. Choose the number

Confirm the scale in use and that it is **writable** — see §7. Anchor on
comparable tickets in the same backlog, not on abstract size. State the anchor.

Useful distinctions when the number feels large:
- **Blocked on a decision** (no URL pattern defined, entitlement unconfirmed)
- **Blocked on data** (field absent from the index; needs ingestion work)
- **Genuinely large** (multi-surface, multi-service, multi-repo)

Only the third is points. The first two are small-and-blocked, and saying so is
more useful than a big number. A ticket whose feature has vanished from the
design, has no data anywhere, and has two unanswered blocking questions should
be recommended for closure, not sized.

If the value exceeds the scale's largest "committable" number, supply a
**concrete split**: sub-story titles, a one-line scope each, and a point value
each — ready for a BA to action without further analysis.

## 6. The second pass — and how not to prompt it

A second independent pass catches real error. **How you prompt it decides
whether it produces signal or noise.**

- Telling it to "default to disagreeing if you can justify it" produced
  disagreement on **8 of 9** stories — mostly manufactured.
- Telling it to "reach your own honest number; agree if they are right,
  disagree only with evidence" produced **7 of 7 agreement** first time, and
  the disputes that did surface were substantive.

Prompt the challenger to hunt for **specific classes of error**, not to
disagree: costs charged that no AC requires; costs omitted entirely; an
already-exists claim whose file is in the wrong repo; a missed or invented AC.
Make it verify against the checkouts rather than reasoning from the summary.

When the two passes differ, **adjudicate on the evidence** — do not split the
difference or mechanically take the higher value. A `max()` rule inflated a
whole batch until it was overridden by hand.

## 7. Check the scale is writable before promising it

Estimation tooling often validates the allowed values. A tracker tool that
accepts only a Fibonacci-style set (for example `[1, 2, 3, 5, 8, 13]`) makes a
doubling scale (needing 4 and 16) unwritable through the normal path; the
overlay names any such tool and its allowed values. Probe with one write before
committing to a scale. If a fallback route is needed, say so plainly — routing
around a team's validator is a process decision for the user, not a workaround
to apply quietly, and it usually skips provenance labelling too.

## 8. Write it back with its reasoning

Post an audit comment alongside the number carrying:
- the AC-by-AC inventory and what drove the number
- costs explicitly **removed**, and why
- the `outOfScope` attributions
- cross-repo work and data blockers, with `file:line`
- the split proposal if there is one
- for a re-estimate: what changed since the previous estimate, and what did not

Two reasons this matters: the next pass can *test* your reasoning instead of
re-deriving it, and a reviewer can tell whether you priced the ticket or the
picture.

## Before you commit the number — checklist

- [ ] Every point traces to a named AC
- [ ] Nothing charged that the ACs or business rules exclude
- [ ] Design scope attributed to sibling tickets or marked unstoried
- [ ] "Already exists" claims checked against the repo that actually ships
- [ ] Field existence verified in the API/index, not assumed either way
- [ ] Coverage figures are per-field, not headline
- [ ] Thin data reported as demonstrability, not priced as effort
- [ ] Sequencing and restyles excluded
- [ ] In-flight tickets left alone
- [ ] Scale confirmed writable
- [ ] Split proposal supplied if over the committable size
