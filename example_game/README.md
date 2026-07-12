# example_game — Contrib Sandbox

A persistent, hand-tested downstream Evennia 6.0 game that installs and wires
together every contrib in this repo. It exists for two reasons:

1. **Reference integration.** It's the "how do these 10 contribs actually get
   wired into a real game" example this repo otherwise lacks — settings,
   cmdsets, server hooks, and the typeclass seams that can't auto-wire.
2. **A living sandbox to hand-test against**, as new contribs (Regions, Maps,
   crafting) get extracted and land here.

Full design background is tracked separately (local-only planning docs, not
part of this repo).

---

## What's wired up

All 10 current contribs, in dependency order — `evennia_links` first, then
the five apps that depend on it (`evennia_rptracker`, `evennia_scenes`,
`evennia_boards`, `evennia_lore`, `evennia_plots`), then the four standalone
apps (`evennia_calendar`, `evennia_jobs`, `evennia_xp`,
`evennia_accessibility`). See `server/conf/settings.py` for the full
`INSTALLED_APPS` list and every XP/rptracker/lore/boards/plots setting.

**Settings hooks point at the contribs' own shipped integration functions**
(`evennia_*.integrations.*`), not at hand-written glue — except five
dotted-path settings that have no shipped default:

| Setting | Wired to |
|---|---|
| `RPTRACKER_FLAG_REVIEW_HOOK` | `world/sandbox/glue.py` → files an `evennia_jobs` ticket |
| `BOARDS_ANTIGAMING_REPORTER` | `world/sandbox/glue.py` → files an `evennia_jobs` ticket |
| `LORE_SESSION_CONTEXT_PROVIDER` | `world/sandbox/glue.py` → resolves room/scene context via rptracker + plots |
| `RPTRACKER_XP_PROJECTION` | left `None` (cosmetic-only `+activity` lines) |
| plots' `XP_POST_BATCH_HOOKS` entry | omitted — no `flip_thread_flags` equivalent ships |

**Typeclass seams** (`typeclasses/characters.py`, `typeclasses/rooms.py`,
`commands/pose_seam.py`) feed `evennia_rptracker` and `evennia_scenes` on
every pose/say and room entry — these cannot auto-wire per each contrib's
README ("Evennia ships no room-receive signal; you must call this
manually").

Not yet extracted as contribs: Regions, Maps, crafting. This sandbox will
grow to cover them as they land.

---

## Local dry-run (before touching the droplet)

You can validate the wiring on your own machine first — same steps as the
droplet, just without nginx/systemd/TLS:

```bash
python3.12 -m venv .venv_sandbox   # NOT the same venv as any other Evennia game
source .venv_sandbox/bin/activate  # or .venv_sandbox\Scripts\activate on Windows
pip install "evennia>=6.0"
for d in contribs/base_systems/evennia_links \
         contribs/game_systems/evennia_rptracker \
         contribs/game_systems/evennia_scenes \
         contribs/game_systems/evennia_boards \
         contribs/game_systems/evennia_lore \
         contribs/game_systems/evennia_plots \
         contribs/game_systems/evennia_calendar \
         contribs/game_systems/evennia_jobs \
         contribs/game_systems/evennia_xp \
         contribs/utils/evennia_accessibility; do
    pip install -e "$d"
done
cd example_game
evennia migrate
evennia start   # create the superuser when prompted
evennia seed_sandbox
```

Connect with a telnet client to `localhost:4100` and run through the
Verification checklist below — telnet is the local smoke-test path. The
webclient at `http://localhost:4101` loads, but its websocket points at
`WEBSOCKET_CLIENT_URL` (the production subdomain), so the in-page client
won't fully connect until you're deployed behind nginx with the real
hostname set.

---

## Droplet deployment

This droplet already runs a separate, unrelated Evennia **3.x** game on the
default ports. Two things keep the sandbox from interfering with it:

- **A strictly isolated Python 3.12 venv.** Different Evennia major version,
  different Django/dependency tree — never `pip install` into the other
  game's environment, and never activate its venv while working on this one.
- **A shifted port block** (see `server/conf/settings.py`): telnet `4100`,
  webclient `4102`, webserver proxy/internal `4101`/`4105`, `AMP_PORT`
  `4106`. `AMP_PORT` is the one that's easy to forget — it's "internal" but
  still binds a real TCP port on the host, and the default `4006` collides
  with the other game.

The droplet has so far only been accessed as root. This sandbox is a
public-facing service sharing the host with another game, so it runs as a
**dedicated non-root user** — a compromise of the game process should not be
a compromise of the whole box (or the other game).

### 0. Create the service user (as root)

```bash
adduser --disabled-password covsandbox
sudo -iu covsandbox
# Everything below runs as covsandbox. sudo is only needed again for
# steps 7 (systemd) and 8 (nginx/certbot).
```

### 1. Isolate

```bash
python3.12 -m venv ~/sandbox/venv
source ~/sandbox/venv/bin/activate
pip install "evennia>=6.0"
```

### 2. Clone this repo

```bash
git clone https://github.com/an0n-b1nary/evennia-contribs-staging.git ~/sandbox/evennia-contribs-staging
cd ~/sandbox/evennia-contribs-staging
```

### 3. Install the contribs, in dependency order

```bash
for d in contribs/base_systems/evennia_links \
         contribs/game_systems/evennia_rptracker \
         contribs/game_systems/evennia_scenes \
         contribs/game_systems/evennia_boards \
         contribs/game_systems/evennia_lore \
         contribs/game_systems/evennia_plots \
         contribs/game_systems/evennia_calendar \
         contribs/game_systems/evennia_jobs \
         contribs/game_systems/evennia_xp \
         contribs/utils/evennia_accessibility; do
    pip install -e "$d"
done
```

### 4. Set the real hostname, migrate, first boot

Edit `example_game/server/conf/settings.py` and replace
`SANDBOX_HOSTNAME = "sandbox.YOURDOMAIN"` with the real subdomain — do this
locally only, don't commit the real domain (anonymity guard).

```bash
cd example_game
evennia migrate
evennia start   # create the superuser when prompted
```

### 5. Seed content

```bash
evennia seed_sandbox   # rerunnable; idempotent
```

### 6. Snapshot the golden DB

```bash
evennia stop
cp server/evennia.db3 server/evennia_default.db3
git add server/evennia_default.db3 && git commit -m "chore: snapshot golden sandbox DB"
evennia start
```

Re-snapshot after every `evennia migrate`.

### 7. systemd (as root / via sudo)

```ini
# /etc/systemd/system/evennia-sandbox.service
[Unit]
Description=Evennia contrib sandbox (example_game)
After=network.target

[Service]
Type=forking
User=covsandbox
WorkingDirectory=/home/covsandbox/sandbox/evennia-contribs-staging/example_game
ExecStart=/home/covsandbox/sandbox/venv/bin/evennia start
ExecStop=/home/covsandbox/sandbox/venv/bin/evennia stop
PIDFile=/home/covsandbox/sandbox/evennia-contribs-staging/example_game/server/portal.pid
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now evennia-sandbox
```

### 8. nginx + TLS (as root / via sudo)

```nginx
server {
    server_name sandbox.YOURDOMAIN;
    listen 80;

    location /ws {
        proxy_pass http://127.0.0.1:4102;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }

    location / {
        proxy_pass http://127.0.0.1:4101;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
sudo certbot --nginx -d sandbox.YOURDOMAIN
sudo ufw allow 4100/tcp   # telnet
```

---

## Resetting

Two mechanisms, for two different needs:

- **`evennia seed_sandbox`** — content-only. Purges and rebuilds the default
  rooms/board/calendar-event/lore/plot content (tagged/name-matched, so
  reruns don't duplicate). Keeps accounts and characters.
- **`scripts/reset_to_golden.sh`** — full wipe. Stops the server, swaps in
  the committed `server/evennia_default.db3`, restarts. Wipes accounts too.
  Re-snapshot the golden file after every `evennia migrate` (see step 6).

---

## Verification checklist

1. **Coexistence** — the other game's telnet/web still respond; no port
   collision.
2. **Reachability** — `https://sandbox.YOURDOMAIN/` (webclient) and
   `telnet sandbox.YOURDOMAIN 4100` both connect.
3. **Every contrib runs** — one command each, no import/lock/settings
   errors: `+bb`, `+calendar`, `+request`, `+lore`, `+plot`, `+xp`,
   `+activity`, `+scene`.
4. **Seams fire** — pose in a seeded room, then `+activity` shows a tracked
   RP session and `+scene` (after `+scene/open`) shows auto-captured poses.
5. **Seeder is idempotent** — run `evennia seed_sandbox` twice; no
   duplicate rooms/boards/entries.
6. **Golden reset works** — make a throwaway change, run
   `scripts/reset_to_golden.sh`, confirm the world is back to default.
