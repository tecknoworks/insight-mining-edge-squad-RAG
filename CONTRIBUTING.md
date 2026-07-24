# Contributing

## Branching

Short-lived feature branches only — no `develop`/`release` branches (no GitFlow). `main` is always deployable.

Branch naming: `<type>/<scope>/<short-desc>`

| Type     | Scope examples            | Example                                  |
| -------- | ------------------------- | ---------------------------------------- |
| feat     | server, client, root, api | `feat/server/add-clustering-endpoint`    |
| fix      | server, client, root, api | `fix/client/chat-ui-scroll`              |
| chore    | server, client, root, api | `chore/root/update-pnpm`                 |
| refactor | server, client, root, api | `refactor/api/regenerate-openapi-client` |

## Merging

**Squash-and-merge only.** This keeps `main`'s history linear — one commit per PR. Do not use regular merge commits or rebase-merge on `main`.

## Commit messages

Scoped Conventional Commits: `<type>(<scope>): <description>`

Allowed types: `feat`, `fix`, `chore`, `refactor`, `docs`, `test`, `perf`, `style`, `ci`, `build`
Allowed scopes: `server`, `client`, `root`, `api` (scope is **required** on every commit)

Examples:

- `feat(server): implement embeddings generation`
- `fix(client): resolve unhandled promise in API client`
- `refactor(api): regenerate openapi-ts client`
- `chore(root): add husky commit-msg hook`

## Enforcement

The rules above are enforced automatically by git hooks (husky + lint-staged + commitlint), installed on `pnpm install` via the root `prepare` script:

- **`.husky/commit-msg`** runs commitlint against `commitlint.config.cjs` — the message must be `<type>(<scope>): <description>` with a required scope of `server`, `client`, `root`, or `api`.
- **`.husky/pre-commit`** runs lint-staged (`.lintstagedrc.json`) — prettier on staged JS/TS/JSON/MD/YAML and ruff on staged `server/**/*.py`.

The project-local `/git-branch`, `/git-commit`, and `/git-pr` skills help produce conforming branches, commits, and PRs up front; the hooks are the safety net that rejects anything that slips through. If the allowed types/scopes change, update both `commitlint.config.cjs` and those skills.
