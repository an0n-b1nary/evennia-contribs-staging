"""Chromium acceptance pass over the reference game's map web surface (issue #7).

Python render tests prove the tile data reaches the page; this drives what
Leaflet actually draws with it. Every viewer logs in through the real website
form, plane IDs are read from `/map/` rather than assumed, and each check
writes the measurements it judged by, plus screenshots, to evidence/maps/.
"""

import json
import re
import traceback
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

DESKTOP = {"width": 1440, "height": 900}
NARROW = {"width": 390, "height": 844}

OVERWORLD = "Sandbox Overworld"
UNDERCROFT = "Sandbox Undercroft"
INTERIOR = "Consulate Interior"
OVERLAYS = ("Activity heatmap", "Lore pins", "Hangouts")

# Each drawn cell, in viewport pixels, with what kind of layer drew it.
CELLS_JS = """() => [...document.querySelectorAll(
    '#evennia-maps-live img.evennia-maps-tile,'
    + ' #evennia-maps-live path.evennia-maps-tile-blank,'
    + ' #evennia-maps-live path.evennia-maps-portal-cell')].map((el) => {
  const r = el.getBoundingClientRect();
  const kind = el.tagName.toLowerCase() === 'img' ? 'sprite'
    : el.classList.contains('evennia-maps-portal-cell') ? 'portal' : 'blank';
  return {kind, x: r.left, y: r.top, w: r.width, h: r.height,
          src: el.getAttribute('src') || '', fill: el.getAttribute('fill') || '',
          loaded: kind !== 'sprite' || (el.complete && el.naturalWidth > 0),
          active: el.classList.contains('evennia-maps-tile-active')};
})"""

# Fixed-size pins and the portal glyph, by overlay, with their centres.
PINS_JS = """() => {
  const centre = (el) => { const r = el.getBoundingClientRect();
    return {cx: r.left + r.width / 2, cy: r.top + r.height / 2, w: r.width, h: r.height,
            text: el.textContent.trim(), cls: el.className.baseVal ?? el.className}; };
  const all = (sel) => [...document.querySelectorAll('#evennia-maps-live ' + sel)].map(centre);
  return {heatmap: all('path.evennia-maps-heatmap-marker'), lore: all('.evennia-maps-lore-marker'),
          hangouts: all('.evennia-maps-hangout-marker'), portal: all('.evennia-maps-portal-marker')};
}"""


def place_cells(cells, box, tiles, label="grid"):
    """Match drawn cells to feed tiles; ({origin, pitch, cells}, {room: cell}).

    Cells must be equal squares on one pitch, adjacent, and each feed tile must
    find a cell of the right kind and sprite at its own grid position, north
    up. Pure geometry, so it holds at any zoom. Leaflet clips SVG paths to the
    visible map, so a path cell not wholly inside `box` is counted but not
    measured. Raises AssertionError when no placement fits.
    """
    assert len(cells) == len(tiles), (label, len(cells), len(tiles))

    def measurable(cell):
        # A path clipped away entirely collapses to an empty box.
        return cell["kind"] == "sprite" or (
            cell["w"] > 0
            and cell["x"] >= box["x"] - 1
            and cell["y"] >= box["y"] - 1
            and cell["x"] + cell["w"] <= box["x"] + box["width"] + 1
            and cell["y"] + cell["h"] <= box["y"] + box["height"] + 1
        )

    def kind(tile):
        if tile["portal_plane_id"] is not None:
            return "portal"
        return "sprite" if tile["sprite_url"] else "blank"

    shown = [cell for cell in cells if measurable(cell)]
    assert shown, label
    pitch = shown[0]["w"]
    assert pitch > 0
    for cell in shown:
        assert abs(cell["w"] - pitch) <= 1 and abs(cell["h"] - pitch) <= 1, (label, cell)
    min_x = min(tile["x"] for tile in tiles)
    max_y = max(tile["y"] for tile in tiles)
    # Anchor the grid on one measured cell by trying each tile it could be.
    anchor = shown[0]
    for guess in tiles:
        if kind(guess) != anchor["kind"] or (
            anchor["kind"] == "sprite" and guess["sprite_url"] != anchor["src"]
        ):
            continue
        left = anchor["x"] - (guess["x"] - min_x) * pitch
        top = anchor["y"] - (max_y - guess["y"]) * pitch
        at = {}
        for cell in shown:
            column, row = (cell["x"] - left) / pitch, (cell["y"] - top) / pitch
            spot = (round(column), round(row))
            if abs(column - spot[0]) * pitch > 1 or abs(row - spot[1]) * pitch > 1 or spot in at:
                break
            at[spot] = cell
        else:
            placed, by_room = {}, {}
            for tile in tiles:
                # North is up: a larger y in the feed is a smaller screen row.
                spot = (tile["x"] - min_x, max_y - tile["y"])
                placed[tile["room_name"]] = list(spot)
                cell = at.pop(spot, None)
                if cell is None:
                    continue
                if cell["kind"] != kind(tile) or (
                    cell["kind"] == "sprite" and cell["src"] != tile["sprite_url"]
                ):
                    break
                by_room[tile["room_name"]] = cell
            else:
                if not at:
                    return {
                        "origin_px": [left, top],
                        "pitch_px": pitch,
                        "cells": placed,
                        "unmeasured_clipped": len(cells) - len(shown),
                    }, by_room
    raise AssertionError(f"{label}: no grid placement matches the feed: {cells}")


class MapSuite:
    def __init__(self, session, timeout):
        self.session = session
        self.host = session.host
        self.base = f"http://127.0.0.1:{self.host.ports['http']}"
        self.timeout = timeout * 1000
        self.out = self.host.artifacts / "maps"
        self.out.mkdir(exist_ok=True)
        self.results = []
        self.observations = {}
        self.diagnostics = {}
        self.expected_status = set()
        self.pages = {}

    # -- harness ---------------------------------------------------------

    def case(self, name, function, fresh=True):
        try:
            if fresh:
                # Each check starts from a freshly fitted overworld, so one
                # failure never leaves the next check a half-driven page.
                self.live(self.player, self.ids[OVERWORLD])
                self.labelled = self.label_cells(self.player)
            function()
        except Exception as exc:  # A Playwright timeout is a failed check too.
            detail = str(exc) if isinstance(exc, AssertionError) and str(exc) else ""
            self.results.append(
                {"name": name, "passed": False, "error": detail or traceback.format_exc()}
            )
            return False
        self.results.append({"name": name, "passed": True})
        return True

    def note(self, key, value):
        self.observations[key] = value

    def shot(self, page, name, full_page=False):
        for spec in self.host.credentials.values():
            assert spec["password"] not in page.content(), "Credential visible in screenshot"
        page.screenshot(path=str(self.out / f"{name}.png"), full_page=full_page)

    def open(self, browser, viewer, viewport=DESKTOP):
        """A fresh context for `viewer` (None is anonymous), logged in by the form."""
        key = f"{viewer or 'anonymous'}@{viewport['width']}"
        sink = self.diagnostics.setdefault(
            key,
            {"console_errors": [], "page_errors": [], "failed_requests": [], "http_errors": []},
        )
        context = browser.new_context(viewport=viewport)
        context.set_default_timeout(self.timeout)
        page = context.new_page()
        page.on("pageerror", lambda error: sink["page_errors"].append(str(error)))

        def console(message):
            # A page this pass requested to prove it 404s logs its own load failure.
            path = urlsplit(message.location.get("url", "")).path
            if message.type == "error" and not any(
                path == expected for _, expected in self.expected_status
            ):
                sink["console_errors"].append(message.text)

        page.on("console", console)
        page.on(
            "requestfailed",
            lambda request: sink["failed_requests"].append(
                {"url": request.url, "error": request.failure}
            ),
        )

        def response(resp):
            path = urlsplit(resp.url).path
            if resp.status >= 400 and (resp.status, path) not in self.expected_status:
                sink["http_errors"].append({"url": resp.url, "status": resp.status})

        page.on("response", response)
        if viewer:
            spec = self.host.credentials[viewer]
            page.goto(self.base + "/auth/login/")
            page.fill("input[name=username]", spec["name"])
            page.fill("input[name=password]", spec["password"])
            page.click("form button[type=submit], form input[type=submit]")
            page.wait_for_load_state("networkidle")
            assert "/auth/login" not in page.url, f"{viewer} login did not complete: {page.url}"
        self.pages[key] = page
        return page

    def planes(self, page):
        """Plane name -> pk, exactly as this viewer's /map/ lists them."""
        page.goto(self.base + "/map/")
        found = {}
        for link in page.locator("a[href^='/map/']").all():
            match = re.fullmatch(r"/map/(\d+)/", link.get_attribute("href") or "")
            if match:
                found[link.inner_text().strip()] = int(match.group(1))
        return found

    def tiles(self, page, plane_id):
        response = page.request.get(f"{self.base}/api/v1/planes/{plane_id}/tiles/")
        assert response.status == 200, response.status
        payload = response.json()
        assert not payload.get("next"), "Tile feed paginated; the pass reads one page"
        return payload["results"]

    def live(self, page, plane_id):
        page.goto(f"{self.base}/map/{plane_id}/live/", wait_until="networkidle")
        self.ready(page)

    def ready(self, page):
        # The room-list toggle unhides only after the tile feed has drawn.
        expect(page.locator("#evennia-maps-list-toggle")).to_be_visible()
        assert not page.locator(".evennia-maps-error").count(), page.locator(
            ".evennia-maps-error"
        ).all_inner_texts()
        page.wait_for_timeout(300)  # fitBounds animates.

    def cells(self, page):
        return page.evaluate(CELLS_JS)

    def hover_label(self, page, cell):
        page.mouse.move(cell["x"] + cell["w"] / 2, cell["y"] + cell["h"] / 2)
        tooltip = page.locator(".leaflet-tooltip").last
        expect(tooltip).to_be_visible()
        return tooltip.inner_text()

    def label_cells(self, page):
        """Hover every cell; room name -> (cell, tooltip text). Overlays must be off."""
        labelled = {}
        for cell in self.cells(page):
            text = self.hover_label(page, cell)
            name = text.splitlines()[0].removesuffix(" (portal)").strip()
            labelled[name] = (cell, text)
        page.mouse.move(1, 1)
        return labelled

    def layout(self, page, tiles, label):
        box = page.locator("#evennia-maps-live").bounding_box()
        return place_cells(self.cells(page), box, tiles, label)

    def grid_check(self, page, tiles, label):
        """`layout`, then hover every cell to confirm the tooltip names its room."""
        layout, by_room = self.layout(page, tiles, label)
        assert len(by_room) == len(tiles), (label, layout)
        labelled = self.label_cells(page)
        assert set(labelled) == set(by_room), (label, sorted(labelled), sorted(by_room))
        for name, (cell, _) in labelled.items():
            assert (cell["x"], cell["y"]) == (by_room[name]["x"], by_room[name]["y"]), (
                label,
                name,
            )
        return layout, labelled

    def overlay(self, page, name, on):
        box = page.locator(".leaflet-control-layers-overlays label", has_text=name).locator("input")
        if box.is_checked() != on:
            box.click()
        page.wait_for_timeout(200)

    def base_layer(self, page, name):
        page.locator(".leaflet-control-layers-base label", has_text=name).locator("input").check()
        page.wait_for_timeout(600)

    def zoom_to_limit(self, page, direction):
        button = page.locator(f".leaflet-control-zoom-{direction}")
        for _ in range(12):
            if "leaflet-disabled" in (button.get_attribute("class") or ""):
                break
            button.click()
            page.wait_for_timeout(350)
        assert "leaflet-disabled" in (button.get_attribute("class") or "")

    def panel(self, page):
        panel = page.locator("#evennia-maps-panel")
        expect(panel).to_be_visible()
        expect(panel).not_to_have_attribute("aria-busy", "true")
        return panel

    def panel_contents(self, page):
        panel = self.panel(page)
        return {
            "title": panel.locator(".evennia-maps-panel-title").inner_text(),
            "meta": panel.locator(".evennia-maps-panel-meta").all_inner_texts(),
            "sections": panel.locator("h3").all_inner_texts(),
            "items": {
                section.locator("h3").inner_text(): section.locator("li").all_inner_texts()
                for section in panel.locator("section").all()
            },
            "links": [
                {"text": link.inner_text(), "href": link.get_attribute("href")}
                for link in panel.locator("a").all()
            ],
            "text": panel.inner_text(),
        }

    def links_resolve(self, page, links):
        statuses = {}
        for link in links:
            response = page.request.get(self.base + link["href"])
            statuses[link["href"]] = response.status
        assert all(status == 200 for status in statuses.values()), statuses
        return statuses

    def open_room(self, page, labelled, name):
        cell, _ = labelled[name]
        page.mouse.click(cell["x"] + cell["w"] / 2, cell["y"] + cell["h"] / 2)
        contents = self.panel_contents(page)
        assert contents["title"] == name, contents
        return contents

    # -- checklist ---------------------------------------------------------

    def entry(self):
        page = self.player
        names = sorted(self.player_planes)
        self.note("player_planes", names)
        for plane in (OVERWORLD, UNDERCROFT, INTERIOR, "Sandbox Scratch"):
            assert plane in self.player_planes, names
        self.shot(page, "map-index-player", full_page=True)
        page.goto(f"{self.base}/map/{self.ids[OVERWORLD]}/")
        svg = page.locator("svg.evennia-maps-svg")
        expect(svg).to_be_visible()
        drawn = svg.evaluate(
            """svg => [...svg.querySelectorAll('g.evennia-maps-tile')].map((g) => {
              const art = g.querySelector('image, rect');
              return {title: g.querySelector('title').textContent, kind: art.tagName,
                      x: +art.getAttribute('x'), y: +art.getAttribute('y')};
            })"""
        )
        tiles = self.feed[OVERWORLD]
        by_room = {
            tile["room_name"]: next(d for d in drawn if d["title"].startswith(tile["room_name"]))
            for tile in tiles
        }
        assert len(drawn) == len(tiles), drawn
        archive, plaza = by_room["The Archive"], by_room["Sandbox Plaza"]
        assert archive["x"] == plaza["x"] and archive["y"] < plaza["y"], (archive, plaza)
        assert by_room["The Causeway"]["kind"] == "rect", by_room["The Causeway"]
        self.note("static_overworld", by_room)
        for hidden in ("The Warren", "Arrival Hall", "Posing Studio"):
            assert hidden not in page.content(), hidden
        self.shot(page, "map-static-overworld-player", full_page=True)
        self.live(page, self.ids[OVERWORLD])
        assert page.evaluate("window.L && L.version") == "1.9.4"
        # leaflet.css positions the panes; without it they fall into normal flow.
        assert (
            page.evaluate("getComputedStyle(document.querySelector('.leaflet-pane')).position")
            == "absolute"
        )
        cells = self.cells(page)
        assert cells and all(cell["loaded"] for cell in cells), cells
        layout, labelled = self.grid_check(page, tiles, "overworld fitted")
        archive, plaza = layout["cells"]["The Archive"], layout["cells"]["Sandbox Plaza"]
        assert archive[0] == plaza[0] and archive[1] == plaza[1] - 1, layout
        assert "The Warren" not in labelled
        self.note("overworld_fitted", layout)
        self.shot(page, "live-overworld-player")
        self.labelled = labelled

    def geometry_at_limits(self):
        page = self.player
        tiles = self.feed[OVERWORLD]
        for overlay in OVERLAYS:
            self.overlay(page, overlay, True)
        for direction, label in (("out", "min"), ("in", "max")):
            self.zoom_to_limit(page, direction)
            zoom = {"zoom": label}
            layout, _ = self.layout(page, tiles, f"overworld zoom {label}")
            zoom.update(layout)
            pins = page.evaluate(PINS_JS)
            # Every cell's centre from the fitted grid, clipped or not.
            (left, top), pitch = layout["origin_px"], layout["pitch_px"]
            centres = {
                name: (left + (column + 0.5) * pitch, top + (row + 0.5) * pitch)
                for name, (column, row) in layout["cells"].items()
            }
            offsets = []
            for kind, markers in pins.items():
                for marker in markers:
                    nearest = min(
                        centres.values(),
                        key=lambda c, m=marker: (c[0] - m["cx"]) ** 2 + (c[1] - m["cy"]) ** 2,
                    )
                    offsets.append(
                        max(abs(nearest[0] - marker["cx"]), abs(nearest[1] - marker["cy"]))
                    )
                    zoom.setdefault("pin_size_px", {}).setdefault(kind, [marker["w"], marker["h"]])
            assert max(offsets) <= 1.5, (label, max(offsets))
            zoom["max_pin_offset_px"] = max(offsets)
            self.note(f"overworld_zoom_{label}", zoom)
            self.shot(page, f"live-overworld-zoom-{label}")
        for overlay in OVERLAYS:
            self.overlay(page, overlay, False)

    def terrain(self):
        page = self.player
        legend = page.locator(".evennia-maps-terrain-key")
        expect(legend).to_be_visible()
        rows = legend.locator("li")
        entries = []
        for index in range(rows.count()):
            row = rows.nth(index)
            swatch = row.locator(".evennia-maps-swatch")
            tag = swatch.evaluate("node => node.tagName.toLowerCase()")
            loaded = swatch.evaluate("node => node.tagName !== 'IMG' || node.naturalWidth > 0")
            entries.append({"label": row.inner_text().strip(), "swatch": tag, "loaded": loaded})
        self.note("terrain_legend", entries)
        feed = {tile["room_name"]: tile for tile in self.feed[OVERWORLD]}
        scrub = feed["The Causeway"]["terrain_label"]
        labels = {entry["label"]: entry for entry in entries}
        assert labels.get(scrub, {}).get("swatch") == "span", entries
        assert all(entry["loaded"] for entry in entries), entries
        sprited = {t["terrain_label"] for t in feed.values() if t["sprite_url"]}
        assert {e["label"] for e in entries if e["swatch"] == "img"} == sprited, entries
        causeway, causeway_text = self.labelled["The Causeway"]
        assert causeway["kind"] == "blank", causeway
        assert scrub in causeway_text and "The Waterfront" in causeway_text, causeway_text
        before = page.locator("path.evennia-maps-tile-blank").first.get_attribute("fill")
        page.mouse.move(causeway["x"] + causeway["w"] / 2, causeway["y"] + causeway["h"] / 2)
        page.wait_for_timeout(150)
        after = page.locator("path.evennia-maps-tile-blank").first.get_attribute("fill")
        assert before != after, (before, after)
        market, _ = self.labelled["Market Row"]
        page.mouse.move(market["x"] + market["w"] / 2, market["y"] + market["h"] / 2)
        page.wait_for_timeout(150)
        hovered = page.locator("img.evennia-maps-tile:hover").evaluate(
            "node => getComputedStyle(node).filter"
        )
        assert "brightness" in hovered, hovered
        self.shot(page, "live-hover-sprite")
        page.mouse.move(1, 1)
        self.note(
            "hover",
            {"fallback_fill": [before, after], "sprite_filter": hovered},
        )

    def fallback_contrast(self):
        # The seed puts one fallback swatch beside sprites so the difference
        # can be seen. Sample what was actually drawn, cell by cell.
        page = self.player
        colours = page.evaluate(
            """() => [...document.querySelectorAll('#evennia-maps-live img.evennia-maps-tile,'
                + ' #evennia-maps-live path.evennia-maps-tile-blank')].map((el) => {
              if (el.tagName === 'IMG') {
                const canvas = document.createElement('canvas');
                canvas.width = canvas.height = 1;
                const g = canvas.getContext('2d');
                g.drawImage(el, el.naturalWidth / 2, el.naturalHeight / 2, 1, 1, 0, 0, 1, 1);
                return {src: el.getAttribute('src'), rgb: [...g.getImageData(0, 0, 1, 1).data.slice(0, 3)]};
              }
              const probe = document.createElement('canvas').getContext('2d');
              probe.fillStyle = el.getAttribute('fill');
              const hex = probe.fillStyle.slice(1);
              return {fill: el.getAttribute('fill'),
                      rgb: [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16))};
            })"""
        )
        fallback = [c for c in colours if "fill" in c]
        sprites = {c["src"]: c["rgb"] for c in colours if "src" in c}
        distances = {
            src: round(
                sum((a - b) ** 2 for a, b in zip(rgb, fallback[0]["rgb"], strict=True)) ** 0.5
            )
            for src, rgb in sprites.items()
        }
        self.note(
            "fallback_contrast",
            {"fallback": fallback, "sprites": sprites, "rgb_distance": distances},
        )
        closest = min(distances, key=distances.get)
        assert distances[closest] >= 48, (
            f"The fallback swatch {fallback[0]['fill']} is hard to tell from {closest} "
            f"(RGB distance {distances[closest]})"
        )

    def floors(self):
        page = self.player
        bases = page.locator(".leaflet-control-layers-base label").all_inner_texts()
        bases = [text.strip() for text in bases]
        assert bases == [UNDERCROFT, OVERWORLD] or bases == [OVERWORLD, UNDERCROFT], bases
        self.overlay(page, "Activity heatmap", True)
        assert page.locator("path.evennia-maps-heatmap-marker").count() == 2
        self.overlay(page, "Activity heatmap", False)
        self.base_layer(page, UNDERCROFT)
        under, _ = self.grid_check(page, self.feed[UNDERCROFT], "undercroft")
        page.locator("#evennia-maps-list-toggle").click()
        listing = page.locator("#evennia-maps-list").inner_text()
        assert "The Cistern" in listing and "Market Row" not in listing, listing
        page.locator("#evennia-maps-list-toggle").click()
        self.overlay(page, "Activity heatmap", True)
        assert page.locator("path.evennia-maps-heatmap-marker").count() == 0
        self.shot(page, "live-undercroft-player")
        self.overlay(page, "Activity heatmap", False)
        self.base_layer(page, OVERWORLD)
        back, self.labelled = self.grid_check(page, self.feed[OVERWORLD], "overworld again")
        page.locator("#evennia-maps-list-toggle").click()
        listing = page.locator("#evennia-maps-list").inner_text()
        assert "Market Row" in listing and "The Cistern" not in listing, listing
        page.locator("#evennia-maps-list-toggle").click()
        self.overlay(page, "Activity heatmap", True)
        assert page.locator("path.evennia-maps-heatmap-marker").count() == 2
        self.overlay(page, "Activity heatmap", False)
        self.note("floors", {"base_layers": bases, "undercroft": under, "overworld": back})

    def portals(self):
        page = self.player
        portal_cells = [cell for cell, _ in self.labelled.values() if cell["kind"] == "portal"]
        assert len(portal_cells) == 1, portal_cells
        hall, hall_text = self.labelled["Consulate Hall"]
        assert hall["kind"] == "portal" and hall_text.strip() == "Consulate Hall (portal)"
        assert page.locator(".evennia-maps-portal-marker").count() == 1
        # The Plaza has a `down` exit onto the Undercroft: a floor, not a portal.
        assert self.labelled["Sandbox Plaza"][0]["kind"] == "sprite"
        self.shot(page, "live-portal-before-click")
        with page.expect_navigation():
            page.mouse.click(hall["x"] + hall["w"] / 2, hall["y"] + hall["h"] / 2)
        assert urlsplit(page.url).path == f"/map/{self.ids[INTERIOR]}/live/", page.url
        self.ready(page)
        interior, _ = self.grid_check(page, self.feed[INTERIOR], "interior")
        assert (
            not page.locator(".leaflet-control-layers-base").count()
            or not page.locator(".leaflet-control-layers-base label").count()
        )
        self.shot(page, "live-interior-after-portal")
        self.note("portal", {"from": "Consulate Hall", "to": page.url, "interior": interior})

    def overlays(self):
        page = self.player
        names = page.locator(".leaflet-control-layers-overlays label").all_inner_texts()
        assert [name.strip() for name in names] == list(OVERLAYS), names
        found = {}
        centres = {
            name: (cell["x"] + cell["w"] / 2, cell["y"] + cell["h"] / 2)
            for name, (cell, _) in self.labelled.items()
        }

        def room_at(marker):
            return min(
                centres,
                key=lambda name: (
                    (centres[name][0] - marker["cx"]) ** 2 + (centres[name][1] - marker["cy"]) ** 2
                ),
            )

        for overlay, kind in zip(OVERLAYS, ("heatmap", "lore", "hangouts"), strict=True):
            self.overlay(page, overlay, True)
            pins = page.evaluate(PINS_JS)[kind]
            found[overlay] = [
                {
                    "room": room_at(pin),
                    "size": [pin["w"], pin["h"]],
                    "text": pin["text"],
                    "class": pin["cls"],
                }
                for pin in pins
            ]
            self.shot(page, f"live-overlay-{kind}")
            self.overlay(page, overlay, False)
            assert not page.evaluate(PINS_JS)[kind], f"{overlay} did not clear"
        self.note("overlays", found)
        heat = {pin["room"]: pin["size"][0] for pin in found["Activity heatmap"]}
        assert set(heat) == {"The Archive", "Market Row"}, heat
        assert heat["The Archive"] > heat["Market Row"], heat
        lore_rooms = {tile["room_name"] for tile in self.feed[OVERWORLD] if tile["has_lore"]}
        assert {pin["room"] for pin in found["Lore pins"]} == lore_rooms, found["Lore pins"]
        hangouts = {pin["room"]: (pin["text"], pin["class"]) for pin in found["Hangouts"]}
        assert len(hangouts) == 3 and len({text for text, _ in hangouts.values()}) == 3, hangouts
        assert len({cls for _, cls in hangouts.values()}) == 3, hangouts

    def room_information(self):
        page = self.player
        tips = {name: text for name, (_, text) in self.labelled.items()}
        self.note("tooltips_player", tips)
        feed = {tile["room_name"]: tile for tile in self.feed[OVERWORLD]}
        for name, text in tips.items():
            tile = feed[name]
            if tile["portal_plane_id"] is None:
                assert tile["terrain_label"] in text, (name, text)
                assert tile["primary_region_name"] in text, (name, text)
        assert "The Commons" in tips["Market Row"], tips
        assert "The Waterfront" in tips["Harbor Steps"], tips
        assert "Event soon" in tips["Market Row"], tips
        market = self.open_room(page, self.labelled, "Market Row")
        self.note("panel_market_row", market)
        for section in ("Recent logs", "Upcoming events"):
            assert section in market["sections"], market
        statuses = self.links_resolve(page, market["links"])
        self.shot(page, "live-panel-market-row")
        region = page.locator("#evennia-maps-panel .evennia-maps-panel-meta a")
        assert region.inner_text() == "The Commons"
        region.click()
        page.wait_for_load_state("networkidle")
        assert re.fullmatch(r"/regions/\d+/", urlsplit(page.url).path), page.url
        expect(page.locator("h1")).to_contain_text("The Commons")
        self.live(page, self.ids[OVERWORLD])
        self.labelled = self.label_cells(page)
        harbor = self.open_room(page, self.labelled, "Harbor Steps")
        assert any("The Waterfront" in line for line in harbor["meta"]), harbor
        self.links_resolve(page, harbor["links"])
        page.keyboard.press("Escape")
        archive = self.open_room(page, self.labelled, "The Archive")
        assert "Recent logs" in archive["sections"], archive
        self.links_resolve(page, archive["links"])
        page.keyboard.press("Escape")
        self.note("panel_harbor_steps", harbor)
        self.note("panel_archive", archive)
        self.note("panel_link_statuses", statuses)

    def consulate_hall_information(self):
        # The only active scene and one of two upcoming events in the seed sit
        # on the portal tile, whose cell navigates instead of opening a panel.
        page = self.player
        tile = next(t for t in self.feed[OVERWORLD] if t["room_name"] == "Consulate Hall")
        page.locator("#evennia-maps-list-toggle").click()
        row = page.locator("#evennia-maps-list li", has_text="Consulate Hall")
        listing = row.inner_text()
        page.locator("#evennia-maps-list-toggle").click()
        evidence = {
            "feed": {
                "has_active_scene": tile["has_active_scene"],
                "active_scenes": [scene["title"] for scene in tile["active_scenes"]],
                "upcoming_events": [event["title"] for event in tile["upcoming_events"]],
            },
            "tooltip": self.labelled["Consulate Hall"][1],
            "room_list": listing,
            "room_list_links": row.locator("a").count(),
            "active_highlights_drawn": sum(cell["active"] for cell, _ in self.labelled.values()),
        }
        self.note("consulate_hall", evidence)
        assert tile["has_active_scene"] and tile["upcoming_events"]
        assert "Event soon" in evidence["tooltip"] or evidence["room_list_links"], (
            "Consulate Hall's active scene and upcoming event reach the feed but no tooltip, "
            f"panel or link on the live map shows them: {evidence}"
        )

    def keyboard(self):
        page = self.player
        toggle = page.locator("#evennia-maps-list-toggle")
        for _ in range(120):
            page.keyboard.press("Tab")
            if page.evaluate("document.activeElement.id") == "evennia-maps-list-toggle":
                break
        else:
            raise AssertionError("Tab never reached the room-list toggle")
        page.keyboard.press("Enter")
        expect(toggle).to_have_attribute("aria-expanded", "true")
        for _ in range(40):
            page.keyboard.press("Tab")
            if page.evaluate("document.activeElement.textContent") == "Market Row":
                break
        else:
            raise AssertionError("Tab never reached the Market Row button")
        page.keyboard.press("Enter")
        contents = self.panel_contents(page)
        assert contents["title"] == "Market Row", contents
        assert page.evaluate(
            "document.getElementById('evennia-maps-panel').contains(document.activeElement)"
        )
        page.wait_for_timeout(400)
        cell = next(
            c
            for c in self.cells(page)
            if c["kind"] == "sprite"
            and c["src"].endswith("urban.png")
            and self._hit(page, c) == "Market Row"
        )
        box = page.locator("#evennia-maps-live").bounding_box()
        offset = (
            abs(cell["x"] + cell["w"] / 2 - (box["x"] + box["width"] / 2)),
            abs(cell["y"] + cell["h"] / 2 - (box["y"] + box["height"] / 2)),
        )
        page.keyboard.press("Escape")
        expect(page.locator("#evennia-maps-panel")).to_be_hidden()
        assert page.evaluate("document.activeElement.textContent") == "Market Row"
        page.keyboard.press("Enter")
        self.panel(page)
        page.locator(".evennia-maps-panel-close").click()
        expect(page.locator("#evennia-maps-panel")).to_be_hidden()
        assert page.evaluate("document.activeElement.textContent") == "Market Row"
        self.note("keyboard", {"centre_offset_px": offset, "panel": contents["title"]})
        page.mouse.move(1, 1)
        assert max(offset) <= 24, (
            f"Market Row is {offset} px from the map centre once its panel opens"
        )

    def _hit(self, page, cell):
        text = self.hover_label(page, cell)
        page.mouse.move(1, 1)
        return text.splitlines()[0]

    def narrow(self):
        page = self.player
        self.shot(page, "live-desktop-overview")
        self.open_room(page, self.labelled, "Market Row")
        self.shot(page, "live-desktop-panel-open")
        page.keyboard.press("Escape")
        narrow = self.open(self.browser, "alice", NARROW)
        self.live(narrow, self.ids[OVERWORLD])
        width = narrow.evaluate("[innerWidth, document.documentElement.scrollWidth]")
        assert width[1] <= width[0], width
        narrow.locator("#evennia-maps-list-toggle").click()
        narrow.locator("#evennia-maps-list button", has_text="Market Row").click()
        panel = self.panel(narrow)
        rect = panel.bounding_box()
        viewport = narrow.evaluate("[innerWidth, innerHeight]")
        sheet = {
            "position": panel.evaluate("node => getComputedStyle(node).position"),
            "rect": rect,
            "viewport": viewport,
        }
        assert sheet["position"] == "fixed", sheet
        assert abs(rect["x"]) <= 1 and abs(rect["width"] - viewport[0]) <= 1, sheet
        assert abs(rect["y"] + rect["height"] - viewport[1]) <= 1, sheet
        assert rect["height"] <= viewport[1] * 0.6 + 1, sheet
        # Every panel link is the element actually under its own centre.
        for link in panel.locator("a").all():
            link.scroll_into_view_if_needed()
            assert link.evaluate(
                "node => { const r = node.getBoundingClientRect();"
                " return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)"
                " === node; }"
            ), link.inner_text()
        width = narrow.evaluate("[innerWidth, document.documentElement.scrollWidth]")
        assert width[1] <= width[0], width
        self.shot(narrow, "live-narrow-panel-open")
        narrow.keyboard.press("Escape")
        expect(narrow.locator("#evennia-maps-panel")).to_be_hidden()
        controls = {}
        for selector in (
            ".leaflet-control-zoom-in",
            ".leaflet-control-layers",
            "#evennia-maps-list-toggle",
        ):
            control = narrow.locator(selector).first
            control.scroll_into_view_if_needed()
            controls[selector] = control.evaluate(
                "node => { const r = node.getBoundingClientRect();"
                " const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);"
                " return {inside: r.left >= 0 && r.right <= innerWidth, reachable: node.contains(hit)}; }"
            )
        assert all(c["inside"] and c["reachable"] for c in controls.values()), controls
        self.shot(narrow, "live-narrow-overview", full_page=True)
        sheet["controls"] = controls
        self.note("narrow", sheet)

    def anonymous(self):
        overworld = self.ids[OVERWORLD]
        hidden = sorted(set(self.staff_planes.values()) - set(self.player_planes.values()))
        assert hidden, "No staff-only plane to compare against"
        private = hidden[0]
        for path in (f"/map/{private}/live/", f"/map/{private}/"):
            self.expected_status.add((404, path))
        self.expected_status.add((403, f"/api/v1/planes/{overworld}/tiles/"))
        page = self.open(self.browser, None)
        response = page.goto(f"{self.base}/map/{overworld}/live/")
        redirected = urlsplit(page.url).path
        assert response.status == 200 and redirected == f"/map/{overworld}/", page.url
        expect(page.locator("svg").first).to_be_visible()
        assert not page.locator(".evennia-maps-error").count()
        self.shot(page, "anonymous-live-redirect", full_page=True)
        hidden_live = page.goto(f"{self.base}/map/{private}/live/")
        hidden_static = page.goto(f"{self.base}/map/{private}/")
        feed = page.request.get(f"{self.base}/api/v1/planes/{overworld}/tiles/")
        anonymous_planes = self.planes(page)
        self.note(
            "anonymous",
            {
                "live_redirect": [f"/map/{overworld}/live/", redirected],
                "hidden_plane_live": hidden_live.status,
                "hidden_plane_static": hidden_static.status,
                "tiles_feed": feed.status,
                "planes": sorted(anonymous_planes),
            },
        )
        assert hidden_live.status == 404 and hidden_static.status == 404
        assert feed.status in (401, 403), feed.status
        assert set(anonymous_planes) <= set(self.player_planes), anonymous_planes

    def privacy(self):
        hidden = {
            name: pk for name, pk in self.staff_planes.items() if name not in self.player_planes
        }
        player = self.player
        for pk in hidden.values():
            for path in (f"/map/{pk}/", f"/map/{pk}/live/"):
                self.expected_status.add((404, path))
        statuses = {
            name: [
                player.request.get(f"{self.base}/map/{pk}/").status,
                player.request.get(f"{self.base}/map/{pk}/live/").status,
                player.request.get(f"{self.base}/api/v1/planes/{pk}/tiles/").status,
            ]
            for name, pk in hidden.items()
        }
        assert all(set(codes) == {404} for codes in statuses.values()), statuses
        staff = self.staff
        self.live(staff, self.ids[OVERWORLD])
        staff_cells, staff_labelled = self.grid_check(
            staff, self.staff_feed[OVERWORLD], "overworld staff"
        )
        assert "The Warren" in staff_labelled and "The Warren" not in self.labelled
        self.shot(staff, "live-overworld-staff")
        self.live(self.player, self.ids[OVERWORLD])
        # Layer controls name only floors this viewer may see.
        player_bases = self.player.locator(".leaflet-control-layers-base label").all_inner_texts()
        staff_bases = staff.locator(".leaflet-control-layers-base label").all_inner_texts()
        for name in hidden:
            assert name not in self.player.content(), name
        # A portal whose destination is private is drawn only for viewers who may follow it.
        frontier = "Frontier Demonstration"
        portals = {}
        if frontier in self.player_planes:
            for role, page in (("player", self.player), ("staff", staff)):
                self.live(page, self.ids[frontier])
                portals[role] = page.locator("path.evennia-maps-portal-cell").count()
            assert portals["staff"] > portals["player"], portals
            self.shot(staff, "live-frontier-staff")
            self.shot(self.player, "live-frontier-player")
        # A staff-only floor's layer control, and that a player cannot reach it.
        stacked = {}
        for name, pk in hidden.items():
            self.live(staff, pk)
            labels = staff.locator(".leaflet-control-layers-base label").all_inner_texts()
            if len(labels) > 1:
                stacked[name] = [label.strip() for label in labels]
        self.note(
            "privacy",
            {
                "hidden_from_player": hidden,
                "player_statuses": statuses,
                "staff_overworld": staff_cells,
                "player_base_layers": [t.strip() for t in player_bases],
                "staff_base_layers": [t.strip() for t in staff_bases],
                "frontier_portal_cells": portals,
                "staff_only_stacks": stacked,
            },
        )

    def presence(self):
        session = self.session
        for actor in ("alice", "bob", "staff", "browser-observer"):
            session.connect(actor)
        alice = self.host.credentials["alice"]["name"]
        bob = self.host.credentials["bob"]["name"]
        for name in (alice, bob):
            result = session.send("staff", f"tel {name}=Market Row")
            assert "Traceback" not in result["output"], result
        result = session.send("bob", "+unfindable on")
        assert "Traceback" not in result["output"], result
        viewers = {
            "same room (alice)": self.player,
            "elsewhere (browser-observer)": self.open(self.browser, "browser-observer"),
            "staff": self.staff,
        }
        seen = {}
        for label, page in viewers.items():
            self.live(page, self.ids[OVERWORLD])
            feed = next(
                tile
                for tile in self.tiles(page, self.ids[OVERWORLD])
                if tile["room_name"] == "Market Row"
            )
            labelled = self.label_cells(page)
            panel = self.open_room(page, labelled, "Market Row")
            here = " ".join(panel["items"].get("Here now", []))
            seen[label] = {
                "feed_present": feed["present"],
                "tooltip": labelled["Market Row"][1],
                "panel_here_now": here,
            }
            self.shot(page, f"presence-{label.split(' ')[0]}")
            page.keyboard.press("Escape")
        self.note("presence", seen)
        same, elsewhere, staff = (seen[label] for label in viewers)
        assert bob in same["panel_here_now"] and alice in same["panel_here_now"], same
        assert alice in elsewhere["panel_here_now"] and bob not in elsewhere["panel_here_now"], (
            elsewhere
        )
        assert bob not in json.dumps(elsewhere["feed_present"]), elsewhere
        assert bob in staff["panel_here_now"], staff
        assert "1 here" in elsewhere["tooltip"], elsewhere
        assert "2 here" in same["tooltip"] and "2 here" in staff["tooltip"], seen

    def active_scene_highlight(self):
        # The seed's only active scene is on a portal, which draws no highlight.
        alice = self.host.credentials["alice"]["name"]
        self.session.send("staff", f"tel {alice}=Market Row")
        result = self.session.send("alice", "+scene/open Map acceptance")
        assert re.search("opened|created|Scene #", result["output"], re.I), result["output"]
        page = self.player
        self.live(page, self.ids[OVERWORLD])
        labelled = self.label_cells(page)
        market, text = labelled["Market Row"]
        assert market["active"], market
        assert "Scene now" in text, text
        panel = self.open_room(page, labelled, "Market Row")
        assert "Happening now" in panel["sections"], panel
        self.links_resolve(page, panel["links"])
        page.keyboard.press("Escape")
        self.zoom_to_limit(page, "in")
        self.shot(page, "live-active-scene-zoom-max")
        self.zoom_to_limit(page, "out")
        self.shot(page, "live-active-scene-zoom-min")
        self.live(page, self.ids[OVERWORLD])
        self.shot(page, "live-active-scene-fitted")
        self.note("active_scene", {"market_row": market, "tooltip": text, "panel": panel})

    # -- run ---------------------------------------------------------------

    def run(self):
        with sync_playwright() as playwright:
            self.browser = playwright.chromium.launch()
            try:
                self.player = self.open(self.browser, "alice")
                self.staff = self.open(self.browser, "staff")
                self.player_planes = self.planes(self.player)
                self.staff_planes = self.planes(self.staff)
                self.ids = self.player_planes
                self.feed = {name: self.tiles(self.player, pk) for name, pk in self.ids.items()}
                self.staff_feed = {
                    name: self.tiles(self.staff, pk) for name, pk in self.staff_planes.items()
                }
                self.note(
                    "revision_planes", {"player": self.player_planes, "staff": self.staff_planes}
                )
                cases = [
                    ("§1 entry routes, Leaflet load and fitted geometry", self.entry),
                    ("§1 geometry and pin centring at both zoom extremes", self.geometry_at_limits),
                    ("§1 terrain colours, legend and hover, sprite and fallback", self.terrain),
                    (
                        "§1 the fallback cell is visibly distinct from sprites",
                        self.fallback_contrast,
                    ),
                    ("§2 base-layer control switches floors both ways", self.floors),
                    ("§2 portal marker navigates; floors are not portals", self.portals),
                    ("§3 overlay controls toggle heat, lore and hangouts", self.overlays),
                    ("§3 tooltips, room panels and their links", self.room_information),
                    (
                        "§3 Consulate Hall's scene and event reach the live map",
                        self.consulate_hall_information,
                    ),
                    ("§4 keyboard room list, panel focus and Escape", self.keyboard),
                    ("§4 narrow bottom sheet, reachability and screenshots", self.narrow),
                    ("§5 anonymous redirect and hidden-plane 404s", self.anonymous),
                    (
                        "§5 player and staff views of private rooms, floors and portals",
                        self.privacy,
                    ),
                    ("§5 presence follows viewer permissions and +unfindable", self.presence),
                    ("§1 active-scene highlight on an ordinary tile", self.active_scene_highlight),
                ]
                for name, function in cases:
                    self.case(name, function)
                self.case(
                    "browser diagnostics: no console, page or request errors", self.clean, False
                )
            finally:
                self.host.evidence.write("maps/observations.json", self.observations)
                self.host.evidence.write("maps/diagnostics.json", self.diagnostics)
                self.host.evidence.write(
                    "maps/browser.json",
                    {"chromium": self.browser.version, "viewports": [DESKTOP, NARROW]},
                )
                self.browser.close()
        return self.results

    def clean(self):
        dirty = {
            key: {kind: entries for kind, entries in sink.items() if entries}
            for key, sink in self.diagnostics.items()
        }
        dirty = {key: kinds for key, kinds in dirty.items() if kinds}
        assert not dirty, dirty


def run_maps(session, timeout=30):
    return MapSuite(session, timeout).run()
