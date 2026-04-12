#!/usr/bin/env bash
# delete_signals.sh — Wipe all signal data from Supabase DB
set -euo pipefail

BACKEND_ENV="$(cd "$(dirname "$0")" && pwd)/backend/.env"

DATABASE_URL=$(grep '^DATABASE_URL=' "$BACKEND_ENV" | cut -d= -f2-)
if [[ -z "$DATABASE_URL" ]]; then
  echo "ERROR: DATABASE_URL not found in $BACKEND_ENV"
  exit 1
fi

# Strip pgbouncer params not supported by psql
DB_URL="${DATABASE_URL%%\?*}"

echo "Deleting all signals from Supabase..."
psql "$DB_URL" -c "TRUNCATE signals RESTART IDENTITY;"
echo "Done. All signal data deleted."
