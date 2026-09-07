"""Screenshot the example_game web surfaces for UI/UX review.

Walks a list of routes against a running Evennia webserver, capturing a
full-page PNG per route per viewport plus a text report of HTTP status and
browser console errors. Output goes to a gitignored directory; nothing this
script produces is meant to be committed.

Authentication forges a Django session row for an existing account and hands
the browser the resulting cookie, so no password ever appears on a command
line or in this file. That only works where this process can open the game's
database -- i.e. a local run. Pointing --base-url at a remote deploy still
works, but only for the anonymous pass (--anon).

Usage (from the repo root, with .venv_sandbox active or via its python):

    cd example_game && evennia start          # in another shell
    python ../scripts/ui_shots.py             # logged in as account #1
    python ../scripts/ui_shots.py --anon      # what a logged-out visitor sees
    python ../scripts/ui_shots.py --only map-live --viewport desktop

Requires playwright (pip) and its chromium build (playwright install chromium).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GAME_DIR = REPO_ROOT / "example_game"

# Every route worth looking at, as (slug, path). The slug names the PNG, so
# keep it filesystem-safe and stable -- re-running with the same slug set is
# what makes two capture runs comparable side by side.
#
# The pks are the ones the sandbox seeder creates (plane 1 = Sandbox Overworld,
# region 1 = The Commons). If a reseed renumbers them, fix them here rather
# than teaching the script to guess: a screenshot of the wrong plane is worse
# than a 404 you can see in the report.
DEFAULT_PAGES: list[tuple[str, str]] = [
    ("home", "/"),
    ("map-index", "/map/"),
    ("map-plane", "/map/1/"),
    ("map-live", "/map/1/live/"),
    ("regions-index", "/regions/"),
    ("region-detail", "/regions/1/"),
    ("calendar", "/calendar/"),
    ("calendar-event", "/calendar/1/"),
    ("plots", "/plots/"),
    ("plot-detail", "/plots/1/"),
    ("scenes", "/scenes/"),
    # Both scene states, because they render differently and the archive only
    # ever shows you the closed one: 1 is the open scene the map's
    # has_active_scene overlay reads, 4 is a closed one with an ended_at.
    ("scene-detail-open", "/scenes/1/"),
    ("scene-detail-closed", "/scenes/4/"),
    ("boards", "/boards/"),
    ("board-detail", "/boards/1/"),
    # Board 2 is seeded with no posts -- kept in the list on purpose, as the
    # cheapest standing check on how an empty collection presents itself.
    ("board-detail-empty", "/boards/2/"),
    ("lore", "/lore/"),
    ("lore-detail", "/lore/1/"),
    ("jobs", "/jobs/"),
    ("xp", "/xp/"),
    ("characters", "/characters/"),
    ("channels", "/channels/"),
    ("help", "/help/"),
    ("webclient", "/webclient/"),
    ("admin", "/admin/"),
    ("api-root", "/api/v1/"),
]

# Two widths, because every one of these pages is reachable from a phone and
# the narrow one is where MUSH web UIs usually fall apart.
VIEWPORTS: dict[str, dict[str, int]] = {
    "desktop": {"width": 1440, "height": 900},
    "mobile": {"width": 390, "height": 844},
}


def bootstrap_django() -> None:
    """Configure Django against the example_game settings, in-process."""
    sys.path.insert(0, str(GAME_DIR))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.conf.settings")
    os.chdir(GAME_DIR)
    import django

    django.setup()


def session_cookie(account_id: int) -> tuple[str, str]:
    """Return (cookie_name, cookie_value) for a session logged in as `account_id`.

    Builds a real session row the way django.contrib.auth.login does, minus the
    request object. The auth hash is what makes the cookie valid, so a password
    change invalidates these exactly as it would a real login.
    """
    from django.conf import settings
    from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
    from django.contrib.sessions.backends.db import SessionStore
    from evennia.accounts.models import AccountDB

    account = AccountDB.objects.get(pk=account_id)
    store = SessionStore()
    store[SESSION_KEY] = str(account.pk)
    store[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
    store[HASH_SESSION_KEY] = account.get_session_auth_hash()
    store.save()
    return settings.SESSION_COOKIE_NAME, store.session_key


def capture(args: argparse.Namespace) -> int:
    from playwright.sync_api import sync_playwright

    pages = DEFAULT_PAGES
    if args.only:
        wanted = set(args.only)
        missing = wanted - {slug for slug, _ in DEFAULT_PAGES}
        if missing:
            print(f"unknown page slug(s): {', '.join(sorted(missing))}", file=sys.stderr)
            return 2
        pages = [(slug, path) for slug, path in pages if slug in wanted]

    viewports = {k: v for k, v in VIEWPORTS.items() if not args.viewport or k in args.viewport}

    stamp = args.label or _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out).resolve() / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    cookies = []
    if not args.anon:
        bootstrap_django()
        name, value = session_cookie(args.account)
        host = re.sub(r"^https?://", "", args.base_url).split("/")[0].split(":")[0]
        cookies = [{"name": name, "value": value, "domain": host, "path": "/"}]

    auth = "anonymous" if args.anon else f"account #{args.account}"
    report: list[str] = [
        f"# ui_shots {stamp}",
        f"base_url: {args.base_url}",
        f"auth: {auth}",
        "",
    ]
    failures = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for vp_name, vp in viewports.items():
                context = browser.new_context(viewport=vp, device_scale_factor=args.scale)
                if cookies:
                    context.add_cookies(cookies)
                page = context.new_page()
                console: list[str] = []

                def note_console(msg, sink=console):
                    if msg.type in ("error", "warning"):
                        sink.append(f"{msg.type}: {msg.text}")

                page.on("console", note_console)
                page.on("pageerror", lambda err, sink=console: sink.append(f"pageerror: {err}"))

                for slug, path in pages:
                    console.clear()
                    url = args.base_url.rstrip("/") + path
                    try:
                        resp = page.goto(url, wait_until="networkidle", timeout=args.timeout)
                        status = resp.status if resp else "?"
                    # Report a failed page and keep going; one bad route must not
                    # cost the whole capture run.
                    except Exception as err:
                        report.append(f"[{vp_name}] {slug} {path} -> EXCEPTION {err}")
                        failures += 1
                        continue
                    # networkidle only tracks HTTP; the webclient paints from a
                    # websocket, so its first frame can arrive after "idle".
                    if args.settle:
                        page.wait_for_timeout(args.settle)
                    shot = out_dir / f"{slug}__{vp_name}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    if status != 200:
                        failures += 1
                    report.append(f"[{vp_name}] {slug} {path} -> {status}  {shot.name}")
                    report.extend(f"    {entry}" for entry in console)
                context.close()
        finally:
            browser.close()

    (out_dir / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    print(f"\n-> {out_dir}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:4101",
        help="running webserver (default: the sandbox's shifted port)",
    )
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / ".screenshots"),
        help="output directory (a timestamped subdir is created inside)",
    )
    parser.add_argument("--label", help="name the subdir this instead of a timestamp")
    parser.add_argument("--anon", action="store_true", help="capture as a logged-out visitor")
    parser.add_argument("--account", type=int, default=1, help="account id to log in as")
    parser.add_argument("--only", nargs="+", metavar="SLUG", help="capture just these pages")
    parser.add_argument("--viewport", nargs="+", choices=sorted(VIEWPORTS), help="limit viewports")
    parser.add_argument("--scale", type=float, default=1.0, help="device scale factor")
    parser.add_argument("--timeout", type=int, default=20000, help="per-page timeout (ms)")
    parser.add_argument(
        "--settle",
        type=int,
        default=0,
        help="extra wait after load, ms -- needed for websocket-painted pages (webclient)",
    )
    return capture(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
