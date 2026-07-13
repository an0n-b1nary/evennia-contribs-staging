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
python3.12 -m venv .venv_sandbox   # NOT the same venv as any other Evennia game;
                                   # Evennia 6.0 runs on 3.10-3.12 (any works)
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

- **A strictly isolated Python 3.10–3.12 venv.** Different Evennia major
  version, different Django/dependency tree — never `pip install` into the
  other game's environment, and never activate its venv while working on this
  one.
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
adduser --disabled-password contrib_sandbox
sudo -iu contrib_sandbox
# Everything below runs as contrib_sandbox. sudo is only needed again for
# steps 7 (systemd) and 8 (nginx/certbot).
```

### 1. Isolate

Evennia 6.0 runs on Python **3.10, 3.11, or 3.12** — any works; use whatever
your OS provides most easily.

```bash
python3.12 -m venv ~/sandbox/venv        # or python3.11 / python3.10
source ~/sandbox/venv/bin/activate
pip install "evennia>=6.0"
```

**If the OS has no suitable Python** — e.g. Ubuntu 20.04 ships only 3.8, and the
deadsnakes PPA can silently refuse to serve newer builds (apt reports "Unable to
locate package python3.12" even with the PPA added and its key accepted) — don't
fight apt; build one from source with **pyenv**. As root, install the build
toolchain:

```bash
sudo apt install -y make build-essential libssl-dev zlib1g-dev libbz2-dev \
  libreadline-dev libsqlite3-dev libffi-dev liblzma-dev wget curl git \
  tk-dev libncursesw5-dev xz-utils
```

`libssl-dev`, `libsqlite3-dev`, and `libffi-dev` are load-bearing for Evennia
(TLS, the SQLite DB, cffi) — omit them and Python still compiles but silently
lacks those modules. Then as `contrib_sandbox`:

```bash
curl -fsSL https://pyenv.run | bash
cat >> ~/.bashrc <<'PYENV'

export PYENV_ROOT="$HOME/.pyenv"
[ -d "$PYENV_ROOT/bin" ] && export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init - bash)"
PYENV
exec bash
pyenv install 3.12.8
~/.pyenv/versions/3.12.8/bin/python -m venv ~/sandbox/venv
source ~/sandbox/venv/bin/activate
```

`pyenv install` prints `Installing...` and then goes **silent for several
minutes while it compiles — it is not frozen.** Confirm progress from a second
shell with `tail -f /tmp/python-build.*.log`, and keep an eye on `free -h` (a
source build can OOM a 1 GB droplet). Once the venv exists, pyenv's job is done —
nothing downstream (or the systemd unit) depends on it; they all call
`~/sandbox/venv/bin/…` directly.

**Keep the venv activated** for every interactive step below (migrate, start,
seed). If pip ever says *"Defaulting to user installation because normal
site-packages is not writeable"*, the venv is **not** active — pip has fallen
back to the system Python, and `evennia>=6.0` will look uninstallable ("no
matching distribution") only because that system Python is too old. Re-run
`source ~/sandbox/venv/bin/activate` and check `python --version`.

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

Put the real subdomain in `server/conf/secret_settings.py`, which Evennia
gitignores by default. This keeps the real domain out of every tracked file —
`settings.py` keeps its committed `sandbox.YOURDOMAIN` placeholder — so there's
nothing for the anonymity guard to catch and no risk of committing it by hand.
Because the four dependent values are derived from `SANDBOX_HOSTNAME` at
definition time in `settings.py`, override them here too:

```bash
cd example_game
tee server/conf/secret_settings.py > /dev/null <<'SECRET'
SANDBOX_HOSTNAME = "sandbox.YOURDOMAIN"
ALLOWED_HOSTS = [SANDBOX_HOSTNAME, "localhost", "127.0.0.1"]
SERVER_HOSTNAME = SANDBOX_HOSTNAME
WEBSOCKET_CLIENT_URL = f"wss://{SANDBOX_HOSTNAME}/ws"
SITE_URL = f"https://{SANDBOX_HOSTNAME}"
SECRET
# then edit the first line to your real subdomain
```

Confirm it's ignored (`git check-ignore server/conf/secret_settings.py` should
echo the path back), and that **every line is flush-left** — a stray leading
space gives `IndentationError: unexpected indent` on boot. Then:

```bash
evennia migrate
evennia start   # create the superuser when prompted
```

The migrate and interactive superuser creation **must be done by hand here.**
systemd (step 7) has no stdin to answer the superuser prompt, so first boot
cannot be left to the service — do it now, then hand the running game to systemd.

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

Do steps 4–6 (migrate, first boot + superuser, seed, snapshot) **before** this —
systemd is last because it can't handle the interactive first boot.

```ini
# /etc/systemd/system/evennia-sandbox.service
[Unit]
Description=Evennia contrib sandbox (example_game)
After=network.target

[Service]
Type=forking
User=contrib_sandbox
# REQUIRED: systemd runs with a bare PATH that does NOT include the venv's bin.
# Evennia's launcher shells out to `twistd`, which lives in the venv — without
# this line it dies with "No such file or directory: 'twistd'" and the service
# never starts. The venv bin must come first.
Environment=PATH=/home/contrib_sandbox/sandbox/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
WorkingDirectory=/home/contrib_sandbox/sandbox/evennia-contribs-staging/example_game
ExecStart=/home/contrib_sandbox/sandbox/venv/bin/evennia start
ExecStop=/home/contrib_sandbox/sandbox/venv/bin/evennia stop
PIDFile=/home/contrib_sandbox/sandbox/evennia-contribs-staging/example_game/server/portal.pid
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now evennia-sandbox
sudo systemctl status evennia-sandbox     # want: active (running)
```

If it sits at `activating (start)` with **Tasks: 1** and no listening ports,
it's stuck, not slow — read `journalctl -u evennia-sandbox -n 40`. The usual
cause is the missing `Environment=PATH` above (the `twistd` error); the other is
that step 4's manual migrate/first-boot was skipped.

### 8. nginx + TLS (as root / via sudo)

**First check whether port 80 is already taken** — on a shared box the other
game may serve its own web directly:

```bash
ss -ltnp | grep -E ':80 |:443 '
```

#### Case A — port 80 is free

Standard flow: a vhost on 80, then `certbot --nginx` (it adds the 443 listener,
the cert, and an 80→443 redirect for you).

```nginx
# /etc/nginx/sites-available/evennia-sandbox
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
ln -s /etc/nginx/sites-available/evennia-sandbox /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d sandbox.YOURDOMAIN
```

#### Case B — port 80 is already held (the shared-droplet case)

You can't bind 80 or use certbot's default http-01 challenge, and you must NOT
reconfigure the running game. Run nginx on **443 only** and validate the cert
via a **DNS challenge**.

1. Issue the cert with DNS-01 (needs no port 80):

   ```bash
   certbot certonly --manual --preferred-challenges dns -d sandbox.YOURDOMAIN
   ```

   It pauses and gives you a TXT record to create: name `_acme-challenge.sandbox`
   (**just that** — your DNS host appends the domain automatically; typing the
   full `_acme-challenge.sandbox.YOURDOMAIN` doubles it and the lookup fails),
   value = the string shown. Add it at your DNS host, then — before pressing
   Enter — confirm from another shell, querying a public resolver to dodge
   negative caching (propagation can lag minutes or more):

   ```bash
   dig +short TXT _acme-challenge.sandbox.YOURDOMAIN @8.8.8.8
   ```

2. Write a **443-only** vhost using the issued cert (no `listen 80`):

   ```nginx
   # /etc/nginx/sites-available/evennia-sandbox
   server {
       listen 443 ssl;
       server_name sandbox.YOURDOMAIN;

       ssl_certificate     /etc/letsencrypt/live/sandbox.YOURDOMAIN/fullchain.pem;
       ssl_certificate_key /etc/letsencrypt/live/sandbox.YOURDOMAIN/privkey.pem;

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

3. Enable it and — crucially — **disable any default vhost that listens on 80**,
   or nginx won't start at all. A single `listen 80` colliding with the other
   game aborts the *entire* nginx process, including your valid 443 site:

   ```bash
   ln -sf /etc/nginx/sites-available/evennia-sandbox /etc/nginx/sites-enabled/
   rm -f /etc/nginx/sites-enabled/default          # removes the symlink only
   nginx -T | grep -E 'listen|server_name'         # verify: only your 443 vhost
   nginx -t && systemctl start nginx
   ```

   Use `nginx -T` (capital T) to hunt a stray `listen 80`: it dumps the
   fully-merged config with every `include` and symlink resolved. Plain
   `grep -r listen /etc/nginx/sites-enabled/` misses them — `grep -r` doesn't
   follow the symlinks that fill `sites-enabled/`.

   Users then reach the sandbox at `https://sandbox.YOURDOMAIN` explicitly; plain
   `http://` on port 80 still hits the other service.

#### Both cases — firewall + renewal

```bash
ufw allow 4100/tcp             # telnet
ufw allow 443/tcp              # Case B: if ufw is active and 443 isn't open
```

**Cert renewal:** Case A's `certbot --nginx` auto-renews. Case B's *manual* DNS
challenge does **not** (no auto-DNS plugin for the registrar) — re-run the
`certbot certonly` command and refresh the TXT record before the 90-day cert
expires. Set a reminder.

---

## Troubleshooting (hard-won)

Symptoms we actually hit deploying this, most in the "two Evennia games, one
droplet" configuration:

| Symptom | Cause & fix |
|---|---|
| `apt`: "Unable to locate package python3.12" on Ubuntu 20.04, even with deadsnakes added | deadsnakes won't serve it (only the `InRelease`, no `Packages`, downloads); build with **pyenv** instead (step 1). |
| pip: "Defaulting to user installation … not writeable"; then `evennia>=6.0` "no matching distribution found" | venv **not activated** → pip used the too-old system Python. `source …/venv/bin/activate`; verify `python --version`. |
| `pyenv install` hangs at `Installing...` for minutes | Normal — it's compiling silently. `tail -f /tmp/python-build.*.log` to watch; check `free -h` for OOM on small boxes. |
| systemd: `Portal process error: No such file or directory: 'twistd'` | venv bin not on systemd's PATH → add `Environment=PATH=…/venv/bin:…` to the unit (step 7). |
| systemd stuck at `activating (start)`, Tasks: 1, no ports listening | Same PATH issue, or the manual migrate/first-boot/superuser (step 4) was skipped. |
| `nginx` won't start / `bind() to 0.0.0.0:80 failed (Address already in use)` | A default vhost with `listen 80` collides with the other game; one bad `listen` aborts all of nginx. Find it with `nginx -T`, disable it (step 8B). |
| Web client returns **Bad Request (400)** | Request host not in `ALLOWED_HOSTS` → set the real `SANDBOX_HOSTNAME` in `secret_settings.py` and restart (step 4). Means nginx *is* proxying correctly. |
| Boot fails: `IndentationError: unexpected indent` in `secret_settings.py` | Stray leading whitespace; every line must be flush-left. `sed -i 's/^[[:space:]]*//' server/conf/secret_settings.py`. |
| DNS TXT / A record "not resolving" | Query a public resolver (`dig +short … @8.8.8.8`) to skip negative caching; check the record **name** wasn't double-suffixed with the domain; allow for slow propagation. |
| Web client loads but won't connect | Websocket — confirm `WEBSOCKET_CLIENT_URL` = `wss://…/ws` and the nginx `/ws` → `4102` proxy block. |

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
