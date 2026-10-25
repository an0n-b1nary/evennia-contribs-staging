# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Drive the live map in Chromium with evennia-calendar genuinely absent (issue #7, §6).

The CI calendar-partners job proves the server side of this profile. This runs
the browser side: a disposable game, started on private localhost ports, with
calendar never installed, registered or mounted. The map, its remaining
overlays and room-panel links must work, and nothing may offer calendar.

Prepare the game exactly as CONTRIBUTING's absent-calendar recipe does, in a
fresh Python 3.12 venv that also has playwright and its Chromium:

    evennia --init ci_game
    python scripts/ci_install_contribs.py ci_game --exclude evennia-calendar
    (cd ci_game && evennia migrate --noinput < /dev/null)
    python scripts/map_calendar_absent.py ci_game

Never point it at a shared or live game: it adds settings and URL modules, a
seeded plane and accounts, and starts and stops that game's server.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, distributions, version
from importlib.util import find_spec
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

URLS = '''"""Map partner pages with calendar absent; written by map_calendar_absent.py."""

from django.urls import include, path
from evennia.web.urls import urlpatterns as evennia_default_urlpatterns

urlpatterns = [
    path("map/", include("evennia_maps.urls")),
    path("regions/", include("evennia_regions.urls")),
    path("", include(("evennia_scenes.urls", "evennia_scenes"))),
    path("lore/", include("evennia_lore.urls")),
    path("api/v1/", include("evennia_maps.api.urls")),
    path("api/v1/", include("evennia_regions.api.urls")),
] + evennia_default_urlpatterns
'''

# Runs inside `evennia shell` once the server has finished its initial setup.
SEED = """
import json
from django.conf import settings
from django.utils import timezone
from evennia import create_account, create_object
from evennia_lore.models import LoreEntry, LoreRegionLink
from evennia_maps.models import MapPlane, RoomTile
from evennia_regions.models import Region, RegionMembership
from evennia_scenes.models import Scene

spec = json.loads(open("map_browser_viewer.json").read())
plane = MapPlane.objects.create(name="Partner plane")
region = Region.objects.create(name="Partner District")
hall = create_object(settings.BASE_ROOM_TYPECLASS, key="Partner Hall")
yard = create_object(settings.BASE_ROOM_TYPECLASS, key="Partner Yard")
for room, x in ((hall, 0), (yard, 1)):
    RoomTile.objects.create(plane=plane, room=room, room_name=room.key, x=x, y=0)
    RegionMembership.objects.create(region=region, room=room, is_primary=True)
account = create_account(spec["name"], email="viewer@example.invalid", password=spec["password"],
                         permissions=["Player"])
author = create_object(settings.BASE_CHARACTER_TYPECLASS, key="Partner author", location=hall)
Scene.objects.create(title="Public partner scene", room=hall, creator=author)
Scene.objects.create(title="Recent partner scene", room=hall, status=Scene.Status.CLOSED,
                     ended_at=timezone.now(), creator=author)
entry = LoreEntry.objects.create(entry_number=1, title="Partner lore",
                                 status=LoreEntry.Status.PUBLISHED)
LoreRegionLink.objects.create(entry=entry, region_id=region.pk)
print("SEEDED", plane.pk)
"""


def free_ports(count=5):
    sockets = []
    try:
        for _ in range(count):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def calendar_is_absent():
    if find_spec("evennia_calendar") is not None:
        return False
    try:
        version("evennia-calendar")
    except PackageNotFoundError:
        return True
    return False


class Game:
    def __init__(self, directory, out):
        self.directory = directory
        self.out = out
        self.launcher = shutil.which("evennia")
        telnet, http, internal, websocket, amp = free_ports()
        self.http = http
        self.env = {
            **os.environ,
            "EVENNIA_SUPERUSER_USERNAME": "map-owner",
            "EVENNIA_SUPERUSER_EMAIL": "owner@example.invalid",
            "EVENNIA_SUPERUSER_PASSWORD": secrets.token_urlsafe(32),
        }
        self.viewer = {"name": "map-viewer", "password": secrets.token_urlsafe(24)}
        (directory / "map_browser_urls.py").write_text(URLS, encoding="utf-8")
        (directory / "map_browser_viewer.json").write_text(
            json.dumps(self.viewer), encoding="utf-8"
        )
        (directory / "server/conf/map_browser_settings.py").write_text(
            "from server.conf.settings import *  # noqa: F403\n"
            'ROOT_URLCONF = "map_browser_urls"\n'
            'MAPS_UNMAPPABLE_ROOM_TYPES = ("ooc",)\n'
            f"TELNET_PORTS = [{telnet}]\n"
            'TELNET_INTERFACES = ["127.0.0.1"]\n'
            f"WEBSERVER_PORTS = [({http}, {internal})]\n"
            'WEBSERVER_INTERFACES = ["127.0.0.1"]\n'
            f"WEBSOCKET_CLIENT_PORT = {websocket}\n"
            'WEBSOCKET_CLIENT_INTERFACE = "127.0.0.1"\n'
            f'WEBSOCKET_CLIENT_URL = "ws://127.0.0.1:{websocket}"\n'
            f"AMP_PORT = {amp}\n"
            'AMP_INTERFACE = "127.0.0.1"\n'
            'ALLOWED_HOSTS = ["127.0.0.1", "localhost"]\n'
            f'CSRF_TRUSTED_ORIGINS = ["http://127.0.0.1:{http}"]\n',
            encoding="utf-8",
        )

    def evennia(self, *arguments, check=True, timeout=240):
        result = subprocess.run(
            [self.launcher, *arguments, "--settings=map_browser_settings.py"],
            cwd=self.directory,
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        with (self.out / "launcher.log").open("a", encoding="utf-8") as log:
            log.write(f"$ evennia {' '.join(arguments[:1])}\n{result.stdout}{result.stderr}\n")
        if check and result.returncode:
            raise RuntimeError(
                f"evennia {arguments[0]} exited {result.returncode}; see launcher.log"
            )
        return result.stdout

    def start(self):
        self.evennia("start")
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.http), timeout=1):
                    return
            except OSError:
                time.sleep(0.5)
        raise RuntimeError("Webserver never accepted connections; see launcher.log")

    def stop(self):
        self.evennia("stop", check=False, timeout=60)


def browse(base, viewer, out):
    from playtesting.maps import place_cells
    from playwright.sync_api import expect, sync_playwright

    diagnostics = {
        "console_errors": [],
        "page_errors": [],
        "failed_requests": [],
        "http_errors": [],
    }
    observations = {}
    results = []

    def case(name, function):
        try:
            function()
            results.append({"name": name, "passed": True})
        except Exception as exc:
            results.append({"name": name, "passed": False, "error": repr(exc)[:4000]})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(30000)
        page.on("pageerror", lambda error: diagnostics["page_errors"].append(str(error)))
        page.on(
            "console",
            lambda m: diagnostics["console_errors"].append(m.text) if m.type == "error" else None,
        )
        page.on(
            "requestfailed",
            lambda r: diagnostics["failed_requests"].append({"url": r.url, "error": r.failure}),
        )
        page.on(
            "response",
            lambda r: (
                diagnostics["http_errors"].append({"url": r.url, "status": r.status})
                if r.status >= 400
                else None
            ),
        )
        observations["chromium"] = browser.version
        page.goto(base + "/auth/login/")
        page.fill("input[name=username]", viewer["name"])
        page.fill("input[name=password]", viewer["password"])
        page.click("form button[type=submit], form input[type=submit]")
        page.wait_for_load_state("networkidle")
        page.goto(base + "/map/")
        link = page.locator("a", has_text="Partner plane")
        plane = int(urlsplit(link.get_attribute("href")).path.strip("/").split("/")[-1])

        def static():
            page.goto(f"{base}/map/{plane}/")
            expect(page.locator("svg.evennia-maps-svg")).to_be_visible()
            assert "/calendar/" not in page.content()
            page.screenshot(path=str(out / "static-map.png"), full_page=True)

        def live():
            page.goto(f"{base}/map/{plane}/live/", wait_until="networkidle")
            expect(page.locator("#evennia-maps-list-toggle")).to_be_visible()
            container = page.locator("#evennia-maps-live")
            assert container.get_attribute("data-event-url-template") == ""
            tiles = page.request.get(f"{base}/api/v1/planes/{plane}/tiles/").json()["results"]
            assert all(tile["upcoming_events"] == [] for tile in tiles), tiles
            cells = page.evaluate(
                "() => [...document.querySelectorAll('#evennia-maps-live img.evennia-maps-tile,"
                " #evennia-maps-live path.evennia-maps-tile-blank')].map((el) => {"
                " const r = el.getBoundingClientRect();"
                " return {kind: el.tagName === 'IMG' ? 'sprite' : 'blank', x: r.left, y: r.top,"
                " w: r.width, h: r.height, src: el.getAttribute('src') || ''}; })"
            )
            layout, _ = place_cells(cells, container.bounding_box(), tiles, "partner plane")
            observations["layout"] = layout
            overlays = page.locator(".leaflet-control-layers-overlays label").all_inner_texts()
            observations["overlay_controls"] = [text.strip() for text in overlays]
            assert observations["overlay_controls"] == ["Activity heatmap", "Lore pins", "Hangouts"]
            for name, selector in (
                ("Activity heatmap", "path.evennia-maps-heatmap-marker"),
                ("Lore pins", ".evennia-maps-lore-marker"),
            ):
                page.locator(".leaflet-control-layers-overlays label", has_text=name).locator(
                    "input"
                ).check()
                assert page.locator(f"#evennia-maps-live {selector}").count() >= 1, name
            page.screenshot(path=str(out / "live-map-overlays.png"))

        def panel():
            page.goto(f"{base}/map/{plane}/live/", wait_until="networkidle")
            page.locator("#evennia-maps-list-toggle").click()
            page.locator("#evennia-maps-list button", has_text="Partner Hall").click()
            box = page.locator("#evennia-maps-panel")
            expect(box).to_be_visible()
            expect(box).not_to_have_attribute("aria-busy", "true")
            sections = box.locator("h3").all_inner_texts()
            links = {a.inner_text(): a.get_attribute("href") for a in box.locator("a").all()}
            observations["panel"] = {"sections": sections, "links": links}
            assert "Upcoming events" not in sections, sections
            for wanted in ("Happening now", "Recent logs", "Lore"):
                assert wanted in sections, sections
            assert links.get("Partner District", "").startswith("/regions/"), links
            for href in links.values():
                assert "/calendar/" not in href, href
                assert page.request.get(base + href).status == 200, href
            assert "/calendar/" not in page.content()
            page.screenshot(path=str(out / "live-map-panel.png"))

        def clean():
            dirty = {kind: entries for kind, entries in diagnostics.items() if entries}
            assert not dirty, dirty

        case("§6 static map renders with no calendar link", static)
        case("§6 live map draws its tiles and remaining overlays", live)
        case("§6 room panel partner links work; no event section or calendar link", panel)
        case("§6 browser diagnostics: no console, page or request errors", clean)
        browser.close()
    return results, observations, diagnostics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", type=Path)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / ".playtest-runs")
    args = parser.parse_args(argv)
    game_dir = args.game_dir.resolve()
    if not (game_dir / "server/conf/settings.py").is_file():
        parser.error(f"no Evennia game at {game_dir}")
    if not shutil.which("evennia"):
        parser.error("evennia is not on PATH; activate the calendar-absent environment")
    if not calendar_is_absent():
        print(
            "evennia-calendar is installed or importable; use a fresh environment", file=sys.stderr
        )
        return 2
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    out = (args.out / f"{stamp}-calendar-absent" / "evidence").resolve()
    out.mkdir(parents=True)
    game = Game(game_dir, out)
    code = 0
    try:
        game.start()
        seeded = game.evennia("shell", "-c", SEED)
        assert "SEEDED" in seeded, seeded
        results, observations, diagnostics = browse(
            f"http://127.0.0.1:{game.http}", game.viewer, out
        )
        observations["revision"] = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True
        ).stdout.strip()
        observations["installed"] = {
            dist.metadata["Name"]: dist.version
            for dist in distributions()
            if dist.metadata["Name"].startswith("evennia")
        }
        for name, value in (
            ("results.json", results),
            ("observations.json", observations),
            ("diagnostics.json", diagnostics),
        ):
            (out / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        for result in results:
            print(
                ("PASS " if result["passed"] else "FAIL ") + result["name"], result.get("error", "")
            )
        code = 0 if all(result["passed"] for result in results) else 1
    finally:
        game.stop()
    print(f"-> {out}")
    return code


if __name__ == "__main__":
    sys.exit(main())
