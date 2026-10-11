#!/usr/bin/env bash
# Fails if the committed OpenAPI document / generated types are stale relative to the API.
set -euo pipefail
cd "$(dirname "$0")/../.."
export DATABASE_URL="${DATABASE_URL:-sqlite:///./contracts-check.sqlite3}"
pnpm contracts:generate >/dev/null
rm -f apps/api/contracts-check.sqlite3
if ! git diff --exit-code --quiet -- packages/contracts/openapi.json packages/contracts/src/generated; then
  echo "Contracts are out of date. Run 'pnpm contracts:generate' and commit the result." >&2
  git --no-pager diff --stat -- packages/contracts >&2
  exit 1
fi
echo "Contracts are up to date."
