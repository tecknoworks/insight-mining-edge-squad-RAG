#!/usr/bin/env bash
#
# check-setup.sh — read-only diagnostics for the Insight Miner monorepo.
#
# Verifies system requirements, installed dependencies, and env files, then
# prints a clear PASS/WARN/FAIL line per check with a troubleshooting hint on
# anything that isn't green. This script NEVER mutates the repo or installs
# anything — it only inspects. Booting the apps is done separately (see SKILL.md).
#
# Exit code: 0 if no FAILs, 1 if any FAIL. WARNs do not fail the run.

set -uo pipefail

# Resolve repo root as the dir two levels up from this script
# (.claude/skills/check-setup/check-setup.sh -> repo root).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$ROOT" || exit 2

# --- Output helpers -------------------------------------------------------
if [ -t 1 ]; then
  GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; BOLD=$'\033[1m'; DIM=$'\033[2m'; RESET=$'\033[0m'
else
  GREEN=''; YELLOW=''; RED=''; BOLD=''; DIM=''; RESET=''
fi

FAILS=0
WARNS=0

pass() { printf '  %s✔ PASS%s  %s\n' "$GREEN" "$RESET" "$1"; }
warn() {
  WARNS=$((WARNS + 1))
  printf '  %s▲ WARN%s  %s\n' "$YELLOW" "$RESET" "$1"
  [ -n "${2:-}" ] && printf '           %s↳ %s%s\n' "$DIM" "$2" "$RESET"
}
fail() {
  FAILS=$((FAILS + 1))
  printf '  %s✘ FAIL%s  %s\n' "$RED" "$RESET" "$1"
  [ -n "${2:-}" ] && printf '           %s↳ fix: %s%s\n' "$DIM" "$2" "$RESET"
}
section() { printf '\n%s%s%s\n' "$BOLD" "$1" "$RESET"; }

# Compare two dotted versions: returns 0 if $1 >= $2.
ver_ge() {
  [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]
}

printf '%s Insight Miner — setup doctor %s\n' "$BOLD" "$RESET"
printf '%s repo: %s%s\n' "$DIM" "$ROOT" "$RESET"

# ==========================================================================
section "1. System requirements"
# ==========================================================================

# Node >= 18 (package.json engines); .nvmrc pins 22 for parity.
if command -v node >/dev/null 2>&1; then
  NODE_V="$(node -v | sed 's/^v//')"
  if ver_ge "$NODE_V" "18.0.0"; then
    NVMRC="$( [ -f .nvmrc ] && tr -d '[:space:]' < .nvmrc )"
    if [ -n "$NVMRC" ] && ! ver_ge "$NODE_V" "$NVMRC.0.0"; then
      warn "node $NODE_V (>= 18 ok, but .nvmrc pins $NVMRC)" "run 'nvm use' (or 'nvm install $NVMRC') for version parity with the team"
    else
      pass "node $NODE_V (>= 18)"
    fi
  else
    fail "node $NODE_V is too old (need >= 18)" "install Node 22: 'nvm install 22 && nvm use' — see .nvmrc"
  fi
else
  fail "node not found" "install Node 22 (https://nodejs.org or 'nvm install 22'); .nvmrc pins the version"
fi

# pnpm >= 9 (packageManager is pnpm@11.x).
if command -v pnpm >/dev/null 2>&1; then
  PNPM_V="$(pnpm -v 2>/dev/null)"
  if ver_ge "$PNPM_V" "9.0.0"; then
    pass "pnpm $PNPM_V (>= 9)"
  else
    fail "pnpm $PNPM_V is too old (need >= 9)" "enable corepack: 'corepack enable && corepack prepare pnpm@latest --activate'"
  fi
else
  fail "pnpm not found" "enable it via corepack: 'corepack enable pnpm' (Node ships corepack), or 'npm i -g pnpm'"
fi

# Python >= 3.11 (server requires-python). uv manages the actual venv, but a
# system interpreter is still needed for uv to build one.
PY_BIN=""
for c in python3.11 python3.12 python3.13 python3; do
  if command -v "$c" >/dev/null 2>&1; then PY_BIN="$c"; break; fi
done
if [ -n "$PY_BIN" ]; then
  PY_V="$("$PY_BIN" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null)"
  if ver_ge "$PY_V" "3.11.0"; then
    pass "python $PY_V (>= 3.11)"
  else
    warn "python $PY_V (< 3.11)" "uv can fetch its own 3.11+ (uv python install 3.11); no system Python 3.11 is strictly required"
  fi
else
  warn "no system python3 found" "not fatal — 'uv sync' can install a managed interpreter (uv python install 3.11)"
fi

# uv (Python dependency + venv manager for server/).
if command -v uv >/dev/null 2>&1; then
  pass "uv $(uv --version 2>/dev/null | awk '{print $2}')"
else
  fail "uv not found (required for the backend)" "install: 'curl -LsSf https://astral.sh/uv/install.sh | sh' — see https://docs.astral.sh/uv/"
fi

# ==========================================================================
section "2. Environment files"
# ==========================================================================

# server/.env — holds secrets (ANTHROPIC_API_KEY, DATABASE_URL). Required.
if [ -f server/.env ]; then
  pass "server/.env exists"
  if grep -Eq '^[[:space:]]*ANTHROPIC_API_KEY=.+' server/.env; then
    pass "server/.env: ANTHROPIC_API_KEY is set"
  else
    warn "server/.env: ANTHROPIC_API_KEY is empty" "Claude summarization + chat will fail at runtime until this is filled in"
  fi
  if grep -Eq '^[[:space:]]*DATABASE_URL=.+' server/.env; then
    pass "server/.env: DATABASE_URL is set"
  else
    warn "server/.env: DATABASE_URL not set" "falls back to the default localhost DSN in app/core/config.py"
  fi
else
  fail "server/.env is missing" "copy the template: 'cp server/.env.example server/.env' then fill in ANTHROPIC_API_KEY"
fi

# Per-stage model vars — non-secret, live in server/.env. Optional (config has defaults).
if [ -f server/.env ]; then
  if grep -Eq '^[[:space:]]*ANTHROPIC_(SUMMARIZATION|CHAT)_MODEL=.+' server/.env; then
    pass "server/.env: per-stage model var(s) set"
  else
    warn "server/.env: no per-stage model vars" "optional — defaults in app/core/config.py apply (claude-haiku-4-5 / claude-sonnet-5)"
  fi
fi

# ==========================================================================
section "3. Installed dependencies"
# ==========================================================================

# Root JS/TS workspace install (also installs husky hooks via prepare).
if [ -d node_modules ]; then
  pass "root node_modules present"
else
  fail "root node_modules missing" "run 'pnpm install' at the repo root"
fi

if [ -d client/node_modules ] || [ -d node_modules/.pnpm ]; then
  pass "client deps installed (pnpm workspace)"
else
  fail "client dependencies not installed" "run 'pnpm install' at the repo root (installs the 'client' workspace member)"
fi

# husky git hooks (installed by the root 'prepare' script on pnpm install).
if [ -d .husky ] && [ -f .husky/commit-msg ] && [ -f .husky/pre-commit ]; then
  HOOKS_PATH="$(git config core.hooksPath 2>/dev/null || true)"
  if [ "$HOOKS_PATH" = ".husky" ] || [ "$HOOKS_PATH" = ".husky/_" ]; then
    pass "husky git hooks installed (core.hooksPath=$HOOKS_PATH)"
  else
    warn "husky files exist but git hooks not wired (core.hooksPath='$HOOKS_PATH')" "run 'pnpm install' (its 'prepare' runs husky) to register the hooks"
  fi
else
  warn "husky hook files missing" "run 'pnpm install' — the root 'prepare' script installs commit-msg + pre-commit hooks"
fi

# Backend venv (created by 'uv sync' from pyproject.toml / uv.lock).
if [ -d server/.venv ]; then
  pass "server/.venv present"
  if command -v uv >/dev/null 2>&1; then
    if uv run --project server python -c 'import fastapi, uvicorn, sqlalchemy' >/dev/null 2>&1; then
      pass "backend imports resolve (fastapi, uvicorn, sqlalchemy)"
    else
      fail "backend deps not fully installed in server/.venv" "run 'uv sync --project server' to install from uv.lock"
    fi
  fi
else
  fail "server/.venv missing (backend deps not installed)" "run 'uv sync --project server' (creates the venv from pyproject.toml / uv.lock)"
fi

# ==========================================================================
section "4. Database connectivity (SQLite)"
# ==========================================================================

# Extract DATABASE_URL from server/.env, else fall back to the config default.
DB_URL=""
if [ -f server/.env ]; then
  DB_URL="$(grep -E '^[[:space:]]*DATABASE_URL=' server/.env | tail -n1 | sed -E 's/^[[:space:]]*DATABASE_URL=//; s/^"//; s/"$//')"
fi
[ -z "$DB_URL" ] && DB_URL="sqlite:///./insight_miner.db"

case "$DB_URL" in
  sqlite:///*)
    # Path is relative to server/ (where the app runs from) unless it's a
    # sqlite:////absolute/path.db (four slashes = absolute).
    DB_PATH="${DB_URL#sqlite:///}"
    case "$DB_PATH" in
      /*) : ;; # already absolute
      *) DB_PATH="server/$DB_PATH" ;;
    esac
    DB_DIR="$(dirname "$DB_PATH")"
    if [ -f "$DB_PATH" ]; then
      if [ -w "$DB_PATH" ]; then
        pass "SQLite DB file exists and is writable ($DB_PATH)"
      else
        fail "SQLite DB file exists but is not writable ($DB_PATH)" "fix permissions: 'chmod u+w $DB_PATH'"
      fi
    elif [ -d "$DB_DIR" ] && [ -w "$DB_DIR" ]; then
      pass "SQLite DB not yet created — will auto-create on first run ($DB_PATH)"
    else
      fail "cannot create SQLite DB — directory missing or not writable ($DB_DIR)" "check the path in DATABASE_URL and directory permissions"
    fi
    ;;
  *)
    warn "DATABASE_URL is not a sqlite:// DSN ('$DB_URL')" "this repo's DB is SQLite (see CLAUDE.md/README) — expected 'sqlite:///./insight_miner.db' unless the team has deliberately changed direction"
    ;;
esac

# ==========================================================================
section "Summary"
# ==========================================================================
if [ "$FAILS" -eq 0 ]; then
  printf '%s All required checks passed%s (%d warning(s)).\n' "$GREEN" "$RESET" "$WARNS"
  printf '%s Next: boot the apps — see SKILL.md step 3 (pnpm dev).%s\n' "$DIM" "$RESET"
  exit 0
else
  printf '%s %d required check(s) FAILED%s, %d warning(s).\n' "$RED" "$FAILS" "$RESET" "$WARNS"
  printf '%s Resolve the FAIL items above (each has a fix), then re-run this doctor.%s\n' "$DIM" "$RESET"
  exit 1
fi
