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
- `chore(root): add docker compose healthchecks`

## Enforcement (not yet active)

Commit-message and staged-file lint/format rules above are enforced by convention today. Automated enforcement (husky pre-commit + commit-msg hooks running lint-staged and commitlint) is planned but deferred until the root `pnpm` workspace `package.json` is scaffolded — follow the rules above manually until then.
