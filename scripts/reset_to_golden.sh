#!/usr/bin/env bash
# Full wipe-to-default reset for the example_game contrib sandbox.
#
# Stops the server, swaps the live database for the committed golden
# snapshot (server/evennia_default.db3), and restarts. This resets
# EVERYTHING — accounts, characters, and content — not just seeded content.
# For a content-only reset that keeps accounts, use `evennia seed_sandbox`
# instead (world/sandbox/management/commands/seed_sandbox.py).
#
# Usage (from anywhere):
#   scripts/reset_to_golden.sh
#
# The golden snapshot must be re-taken after any `evennia migrate`:
#   evennia stop
#   cp server/evennia.db3 server/evennia_default.db3
#   git add server/evennia_default.db3 && git commit -m "..."
#   evennia start

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GAME_DIR="$REPO_ROOT/example_game"
GOLDEN_DB="$GAME_DIR/server/evennia_default.db3"
LIVE_DB="$GAME_DIR/server/evennia.db3"

if [ ! -f "$GOLDEN_DB" ]; then
    echo "error: no golden snapshot at $GOLDEN_DB" >&2
    echo "Take one first: evennia stop && cp server/evennia.db3 server/evennia_default.db3" >&2
    exit 1
fi

echo "Stopping example_game..."
evennia --gamedir "$GAME_DIR" stop

echo "Restoring golden snapshot..."
cp "$GOLDEN_DB" "$LIVE_DB"

echo "Starting example_game..."
evennia --gamedir "$GAME_DIR" start

echo "Done. example_game restored to golden snapshot."
