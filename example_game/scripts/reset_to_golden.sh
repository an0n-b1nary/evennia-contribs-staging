#!/usr/bin/env bash
# Full wipe-to-default reset for the example_game contrib sandbox.
#
# ---------------------------------------------------------------------
# The snapshot has to be retaken and recommitted after every `evennia
# migrate`, or it restores a schema the code no longer matches.
# Use `+sandbox/reset` or `evennia seed_sandbox`
# for content resets; neither touches accounts.
#
# To rebuild it, follow README step 6 or run scripts/snapshot_golden.py. Generate
# it locally, never from the droplet: a droplet-born snapshot publishes
# that server's superuser email and password hash, and a golden reset
# restores those rows, making the published hash the live admin
# credential. See issue #6.
# ---------------------------------------------------------------------
#
# Stops the server, swaps the live database for the committed golden
# snapshot (server/evennia_default.db3), refreshes dated fixtures, and restarts. This resets
# EVERYTHING — accounts, characters, and content — not just seeded content.
# For a content-only reset that keeps accounts, use `evennia seed_sandbox`
# instead (world/sandbox/management/commands/seed_sandbox.py).
#
# Usage (from anywhere):
#   example_game/scripts/reset_to_golden.sh
#
# The golden snapshot must be re-taken after any `evennia migrate`:
#   python example_game/scripts/snapshot_golden.py
#   git add server/evennia_default.db3 && git commit -m "..."

set -euo pipefail

GAME_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GOLDEN_DB="$GAME_DIR/server/evennia_default.db3"
LIVE_DB="$GAME_DIR/server/evennia.db3"

if [ ! -f "$GOLDEN_DB" ]; then
    echo "error: no golden snapshot at $GOLDEN_DB" >&2
    echo "Take one first:" >&2
    echo "  python $GAME_DIR/scripts/snapshot_golden.py" >&2
    exit 1
fi

# The launcher resolves the game dir from the *current working directory*, not
# from `--gamedir`. settings_default.py computes GAME_DIR by walking up from
# os.getcwd() at import time, and the launcher's set_gamedir() — the only thing
# that would chdir on --gamedir's behalf — sits behind an
# `if "GAMEDIR" not in globals()` guard in init_game_directory() that is never
# true, because GAMEDIR is assigned at module level. So `evennia --gamedir X
# stop` from elsewhere silently targets evennia's packaged game_template.
# cd first, then run the launcher bare.
cd "$GAME_DIR"

echo "Stopping example_game..."
# Tolerate an already-stopped server; the goal here is "ensure stopped".
evennia stop || true

# `evennia stop` returns before the processes have actually exited. Copying
# over evennia.db3 while the server still holds it open loses the reset (or
# corrupts the file), so wait for both pidfiles to clear before swapping.
for _ in $(seq 1 30); do
    if [ ! -f "$GAME_DIR/server/server.pid" ] && [ ! -f "$GAME_DIR/server/portal.pid" ]; then
        break
    fi
    sleep 1
done
if [ -f "$GAME_DIR/server/server.pid" ] || [ -f "$GAME_DIR/server/portal.pid" ]; then
    echo "error: server did not shut down within 30s; refusing to swap the live DB" >&2
    echo "Check $GAME_DIR/server/logs/ and stop it by hand, then rerun." >&2
    exit 1
fi

echo "Restoring golden snapshot..."
cp "$GOLDEN_DB" "$LIVE_DB"
# SQLite keeps the tail of recent writes in these sidecar files. Leaving the
# old ones next to a restored DB replays post-snapshot state back over it.
rm -f "$LIVE_DB-wal" "$LIVE_DB-shm"

echo "Starting example_game..."
# Dates in a committed snapshot age while it sits in Git. Refresh the fixtures
# so demo challenges aren't already idle-expired when the reset starts up.
evennia migrate --noinput < /dev/null
evennia seed_sandbox < /dev/null
evennia start

echo "Done. example_game restored to golden snapshot."
