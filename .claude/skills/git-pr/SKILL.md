---
name: git-pr
description: Open a pull request for the current branch following this repo's squash-merge-only policy and scoped Conventional Commits title format (see CONTRIBUTING.md).
---

Open a PR for: $ARGUMENTS

1. Confirm the current branch follows the `<type>/<scope>/<short-desc>` naming convention from [CONTRIBUTING.md](../../../CONTRIBUTING.md#branching); if it doesn't, flag it rather than silently proceeding.
2. Review every commit on this branch since it diverged from `main` (`git log main..HEAD`, `git diff main...HEAD`) — not just the latest commit.
3. Draft a PR title in the same scoped Conventional Commits form as the branch/commits: `<type>(<scope>): <description>` (under ~70 chars).
4. Draft a body summarizing the change and a test plan, per this repo's PR body format.
5. Push the branch and open the PR with `gh pr create` in one go — do not pause to confirm first (the user has opted into automatic push + PR creation for this skill).
6. Remind the user this repo is **squash-and-merge only** (see [CONTRIBUTING.md](../../../CONTRIBUTING.md#merging)) — when the PR is merged, "Squash and merge" must be selected explicitly; it is not enforced automatically until branch protection is configured on the remote.
7. Return the PR URL.

Never merge the PR yourself unless the user explicitly asks you to.
