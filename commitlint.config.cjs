// Enforces the scoped Conventional Commits convention from CONTRIBUTING.md:
//   <type>(<scope>): <description>
// Scope is REQUIRED on every commit and must be one of the allowed scopes.
module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [
      2,
      'always',
      ['feat', 'fix', 'chore', 'refactor', 'docs', 'test', 'perf', 'style', 'ci', 'build'],
    ],
    'scope-empty': [2, 'never'],
    'scope-enum': [2, 'always', ['server', 'client', 'root', 'api']],
  },
};
