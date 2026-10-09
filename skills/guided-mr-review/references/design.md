# guided-mr-review — design notes

Why the skill is shaped the way it is, which options were weighed, and what
could come next. Written October 2026.

## Problem

`mr-review` hands over a finished findings list. That works when the agent's
review is enough on its own. When a human has to own the approval, it leaves
two gaps:

1. The reviewer can't tell which findings need their judgement and which are
   already settled. They either re-check everything or accept everything.
2. A pre-written verdict anchors the reviewer, who then agrees with it instead
   of judging (automation bias).

Neighbouring tools solve different problems. An author-written reviewer guide
explains the change to reviewers. A diff explainer teaches the change. A
walkthrough table summarises each file. None of them tells *this* reviewer
which few decisions are theirs.

## What the research says

- **Position drives attention.** Files shown earlier in a review get more
  comments, even after controlling for confounders. Alphabetical order (the
  usual default) puts problematic files no higher than chance, and ordering
  by the code diff does better.
  - Fregnan et al., *First Come First Served*: https://arxiv.org/pdf/2306.06956
  - Bagirov et al., 51,566 reviews in an industrial setting: https://arxiv.org/pdf/2609.22610
- **Developers want better order.** In a survey of 1,355 developers, only
  about 10% find alphabetical order optimal. Most want dependency-aware or
  customizable ordering, and say alphabetical order increases context
  switching. *Breaking the Alphabet*, ICSE 2026:
  https://arxiv.org/pdf/2609.04207
- **Cross-file defects depend on working memory.** Defects whose cause and
  effect are in different places are found less reliably by reviewers with
  lower working-memory capacity. Smaller changes are reviewed better. Baum et
  al.: https://link.springer.com/10.1007/s10664-022-10123-8
- **Checklists help less than you'd expect.** Guidance helps on simple
  reviews, but no strong link to performance was found overall. That argues
  for a few sharp questions, not long checklists. Same body of work, summarised
  in https://arxiv.org/pdf/2306.06956.
- **Route attention by risk.** Spend human review on what is costly to get
  wrong, judged by blast radius and reversibility, and let automation take the
  mechanical checks.
  - https://www.cortex.io/post/risk-based-code-review
  - https://www.softwareseni.com/how-to-govern-ai-coding-tools-and-decide-where-the-fix-belongs/
- **AI review comes with automation bias.** Keep humans at the points where a
  decision is made.
  - https://arxiv.org/pdf/2605.17548
  - https://leaddev.com/ai/as-ai-helps-us-write-more-code-whos-catching-the-bugs
- **Prior art in products.**
  - Graphite Code Tours: a narrative tour beside the diff, https://graphite.com/blog/code-tours
  - CodeRabbit walkthrough: a per-file summary table, https://docs.coderabbit.ai/guide/index

## How the design follows

| Finding | Design choice |
|---|---|
| Position drives attention | Stops are ranked by risk, never by path |
| Cross-file defects need working memory | Every stop names its partner location |
| Checklists help little | 2–5 stops, each with one question; "nothing needs you" is allowed |
| Risk routing | Mechanical checks go in "Already verified — skip these" with evidence; humans get intent, cross-file effects, unverified risk and blast radius |
| Automation bias | Stops are neutral questions. The agent's view comes only on request or after the user's verdict. Only proven defects are stated as facts. |

## Options considered

1. **Brief, plus an optional walk.** Chosen. One screen by default, with an
   interactive pass when wanted. The walk drafts comments in the user's voice.
2. **Brief only.** The cheapest version. It was folded into option 1 as the
   default output.
3. **Blind walk (coach mode).** Hides the agent's findings at each stop until
   the user has answered. Strongest against automation bias, but slowest. It
   would be a natural `--blind` flag on the walk.
4. **Shareable page tour.** An artifact page with ordered stops, snippets,
   checkboxes and notes, like Code Tours. Most visual, and shareable with a
   co-reviewer, but costs the most to build and maintain.

## Possible next steps

- `--blind` for the walk (option 3).
- Export the brief and walk record as a shareable page (option 4).
- Measure the skill: across several MRs, record whether the user's eventual
  comments landed on the stops, or somewhere the brief didn't point.
