#!/usr/bin/env bash
# Archive the portfolio ledger + equity curves before a destructive operation.
#
#   ./scripts/archive_portfolios.sh [label]
#
# Writes one CSV per table to ~/.local/state/autonomous-trader/archive/<label>/ and
# REFUSES to finish if any table came out empty.
#
# Why not pg_dump: portfolio_nav is a TimescaleDB hypertable, and
# `pg_dump --data-only -t portfolio_nav` dumps the (always empty) parent table — the
# rows live in _timescaledb_internal chunks. That silently produced a 0-row NAV
# archive on 2026-08-31 and the equity curves were lost in the reset that followed.
# `\COPY (SELECT ...)` reads through the parent like any query, so it sees every chunk.
set -euo pipefail

LABEL="${1:-$(date +%Y-%m-%d-%H%M)}"
DEST="${ARCHIVE_DIR:-$HOME/.local/state/autonomous-trader/archive}/$LABEL"
CONTAINER="${DB_CONTAINER:-trader-db}"
DB="${POSTGRES_DB:-autonomous_trader}"
USER_="${POSTGRES_USER:-trader}"
TABLES=(portfolios cash_movements trade_orders portfolio_positions portfolio_nav)

mkdir -p "$DEST"
failed=0
for table in "${TABLES[@]}"; do
  out="$DEST/$table.csv"
  docker exec -i "$CONTAINER" psql -U "$USER_" -d "$DB" \
    -c "\\COPY (SELECT * FROM $table) TO STDOUT WITH CSV HEADER" > "$out"
  rows=$(( $(wc -l < "$out") - 1 ))
  if [ "$rows" -le 0 ]; then
    echo "ERROR: $table archived 0 rows — refusing to call this a backup." >&2
    failed=1
  else
    echo "$table: $rows rows -> $out"
  fi
done

gzip -f "$DEST"/*.csv
[ "$failed" -eq 0 ] || exit 1
echo "archive complete: $DEST"
