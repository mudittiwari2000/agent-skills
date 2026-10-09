# Repo profiles

Discovered, per-repo facts that speed up review. These are hints, not truths:
re-verify before relying on a row, and fix the row when it is wrong. Keep the
rows generic. Do not put personal paths, user names or secret values here.
Add a repo the first time a review discovers something non-obvious about it.

Rows for an organisation's private repos belong in the overlay profile
(`overlays/mr-review/profile.md`, see SKILL.md), never in this public file.

| Repo (match by remote path) | Kind | Review surfaces | Verification notes |
|---|---|---|---|
| `<group>/<project>` (example) | Product code / agent tooling | Where behaviour lives: entry points, shared packages, manifests, the repo's own agent rules files. | How to run its checks in a fresh worktree; known pre-existing failures to baseline; mergeability quirks (e.g. per-MR version bumps). |
