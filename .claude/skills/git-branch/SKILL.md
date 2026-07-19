---
name: git-branch
description: Create a new git branch following this repo's <type>/<scope>/<short-desc> naming convention (see CONTRIBUTING.md).
---

Create a branch for: $ARGUMENTS

1. Determine `<type>` from the work described — one of `feat`, `fix`, `chore`, `refactor`, `docs`, `test`, `perf`, `style`, `ci`, `build`.
2. Determine `<scope>` — one of `server`, `client`, `root`, `api`. If the work genuinely spans more than one, pick the scope of the primary change, not `root` by default. Ask the user if it's ambiguous — don't guess.
3. Turn the description into a short kebab-case slug (a few words, no type/scope repeated in it).
4. Before branching, make sure `main` is up to date: `git fetch origin main` and check whether local `main` is behind (per this repo's [Git Safety Protocol](../../../CLAUDE.md), never discard local work to do this — if `main` has diverged, surface it instead of forcing).
5. Create and switch to the branch: `git checkout -b <type>/<scope>/<short-desc>` from an up-to-date `main`.

Reference: [CONTRIBUTING.md](../../../CONTRIBUTING.md#branching) for the full naming table and examples.
