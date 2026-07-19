---
name: git-commit
description: Stage changes and create a commit message following this repo's scoped Conventional Commits convention (see CONTRIBUTING.md).
---

Create a commit for: $ARGUMENTS

1. Run `git status` and `git diff` to see what's actually changed — never assume from the request alone.
2. Stage only the files relevant to this change by name (never `git add -A` / `git add .`) — see this repo's [Git Safety Protocol](../../../CLAUDE.md).
3. Pick `<type>` — one of `feat`, `fix`, `chore`, `refactor`, `docs`, `test`, `perf`, `style`, `ci`, `build` — that matches what the diff actually does, not what was originally asked for.
4. Pick `<scope>` — one of `server`, `client`, `root`, `api`. Scope is **required**, never omit or invent one outside this list. If the staged diff spans more than one scope, either split into separate commits per scope or ask the user which scope takes precedence — don't default to `root`.
5. Write the message as `<type>(<scope>): <description>` — imperative, concise, no trailing period. Match the style of [CONTRIBUTING.md](../../../CONTRIBUTING.md#commit-messages)'s examples (e.g. `feat(server): implement embeddings generation`).
6. Commit via a HEREDOC (per this repo's git commit instructions) — never `--no-verify`, never amend unless explicitly asked.
7. Run `git status` after to confirm the commit succeeded and nothing unstaged was left behind unexpectedly.

Only commit when the user has explicitly asked for a commit — do not commit proactively.
