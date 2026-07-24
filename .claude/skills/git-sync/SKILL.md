---
name: git-sync
description: Sync local main with the remote after a PR merges and safely clean up the merged branch, accounting for this repo's squash-merge policy (see CONTRIBUTING.md).
---

Sync and clean up after a merge for: $ARGUMENTS

Use this once a PR has been squash-merged on GitHub, to bring local `main` up to date and retire the merged feature branch. `$ARGUMENTS` may name the branch to clean up; default to the branch you're currently on.

1. Note the branch you're on and check for uncommitted work with `git status`. If anything is uncommitted or staged, **stop and surface it** — do not stash, discard, or commit it to make the sync go through (per this repo's [Git Safety Protocol](../../../CLAUDE.md)). Let the user decide first.
2. Fetch the latest remote state and prune deleted remote branches: `git fetch --prune origin`.
3. Update local `main`:
   - `git checkout main`
   - `git merge --ff-only origin/main` — fast-forward only.
   - If the fast-forward fails, local `main` has diverged (it has commits not on the remote). **Do not force it** with `-f`/`reset --hard`. Surface the divergence and let the user decide — direct commits to `main` are not part of this flow (all changes land via squash-merged PRs).
4. Retire the merged feature branch (the one from step 1, or `$ARGUMENTS`):
   - Because this repo is **squash-and-merge only** ([CONTRIBUTING.md](../../../CONTRIBUTING.md#merging)), the merged commit on `main` is a brand-new SHA — so `git branch -d` will refuse the branch as "not merged" even though its PR landed. Do **not** reach for `git branch -D` blindly to get around that; that flag also deletes branches whose work never merged.
   - Instead, confirm the PR actually merged before deleting: `gh pr view <branch> --json state,mergedAt`. Only when `state` is `MERGED` (non-null `mergedAt`), delete the local branch with `git branch -D <branch>`.
   - If `gh` reports the PR as `OPEN`, `CLOSED` (not merged), or finds no PR, **leave the branch alone** and say why — deleting it could lose unmerged work.
5. Report the result: what SHA `main` advanced to (`git log --oneline -1`), which branch was deleted (or why it was kept), and offer to start the next piece of work with `/git-branch`.

Never delete a branch, discard uncommitted changes, or force-update `main` without the checks above.
