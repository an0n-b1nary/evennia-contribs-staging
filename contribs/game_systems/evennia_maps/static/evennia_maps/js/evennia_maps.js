/**
 * evennia_maps — Leaflet dynamic map.
 *
 * Reads its config from data-* attributes on #evennia-maps-live (see
 * templates/evennia_maps/plane_live_map.html) rather than being handed
 * server-rendered tile data — tiles are privacy-filtered per request by
 * the API's PlaneViewSet.tiles(), so this file always asks the API fresh
 * instead of caching a payload across navigations.
 *
 * Z-stack layers: each sibling elevation in the same zstack is its own
 * MapPlane/dataset, not a toggle over one payload. Every sibling gets an
 * empty L.layerGroup up front so the layer control has a stable object to
 * hold; the group is *populated in place* the first time that elevation is
 * selected. Swapping in a different group object instead would leave the
 * control pointing at the discarded one.
 *
 * Portals are geometry-inferred server-side (portal_plane_id) — this file
 * only renders the marker and navigates.
 *
 * Overlays: the activity heatmap, lore pins, and hangout markers are
 * toggleable Leaflet overlay layers built from fields already present on
 * each tile (recent_scene_count, has_lore, hangout_type) — no extra fetch.
 * Every overlay is privacy-filtered server-side exactly like the base tile
 * data; this file never re-derives visibility.
 *
 * The room panel: clicking a tile (or its room-list button) asks the
 * room-detail route about that one room and shows the answer beside the
 * map, or as a bottom sheet on a narrow screen. That is where per-viewer
 * content lives — lore your character knows, who is in the room with you —
 * plus whatever sections partner contribs add (see evennia_maps/detail.py).
 * Without the route, or if it fails, the panel shows what the tile feed
 * already carries.
 *
 * Terrain display (label, colour, sprite) comes from MAPS_TERRAINS on the
 * server (terrain.terrain_style), so this file never needs the vocabulary.
 * Tiles brighten on hover and carry a tooltip; a terrain legend sits in the
 * corner, and a room list beneath the map gives keyboard and screen-reader
 * users every tile, each with a button that opens the same panel.
 *
 * Who's here (tile.present, from evennia_social) is a "N here" badge and a
 * list of names in the panel. The server has already left out characters
 * who chose not to be found, so this file shows what it is given.
 *
 * Overlay data arrives only from whichever partner contribs the game has
 * installed (evennia_regions/scenes/lore/calendar/social). Absent ones simply
 * leave their field at its empty value, and an outbound URL template that
 * came back empty means that contrib's pages aren't mounted — the link is
 * dropped rather than pointed at nothing.
 */
(function () {
  "use strict";

  // One grid cell is TILE_PX *map units* across, matching views.py's TILE_SIZE
  // so the live map and the static SVG agree on scale.
  //
  // Cells are drawn as imageOverlay/rectangle in map units rather than as
  // fixed-size marker icons. Under L.CRS.Simple one map unit is one pixel at
  // zoom 0, so a marker placed at a raw grid coordinate sits one pixel from its
  // neighbour while being drawn TILE_PX pixels wide - every tile on a plane
  // lands inside a single tile's footprint. Geometry in map units scales with
  // zoom, which a marker's iconSize (screen pixels) cannot.
  var TILE_PX = 32;

  // Colours for the cells Leaflet draws as SVG paths. A path takes its colours
  // from Leaflet's inline attributes rather than from CSS, so init() reads the
  // same --evennia-maps-* custom properties the stylesheet uses; these are the
  // stylesheet's defaults, kept when a property is unset. "tile" is also the
  // swatch for a terrain with neither a sprite nor a colour.
  var palette = {
    tile: "#3a3a3a",
    edge: "rgba(255, 255, 255, 0.25)",
    hover: "#ffffff",
    active: "#ffce54",
    portal: "#b39ddb",
    "portal-fill": "#2b2536",
  };

  function readPalette(element) {
    var style = window.getComputedStyle(element);
    Object.keys(palette).forEach(function (name) {
      var value = style.getPropertyValue("--evennia-maps-" + name).trim();
      if (value) {
        palette[name] = value;
      }
    });
  }

  function cellBounds(tile) {
    // Leaflet takes [lat, lng]; under CRS.Simple lat is y and increases upward,
    // which matches the static SVG's (max_y - y) flip. North is up in both.
    return [
      [tile.y * TILE_PX, tile.x * TILE_PX],
      [(tile.y + 1) * TILE_PX, (tile.x + 1) * TILE_PX],
    ];
  }

  function cellCenter(tile) {
    // Pins sit at the middle of the cell, not its corner. They stay fixed-size
    // on purpose - a pin that scaled with zoom would be unreadable zoomed out.
    return [(tile.y + 0.5) * TILE_PX, (tile.x + 0.5) * TILE_PX];
  }

  function hangoutLabel(type) {
    if (!type) {
      return "";
    }
    // The owning contrib defines the vocabulary; render whatever we're
    // handed rather than keeping a second copy of the list here, which
    // would silently drop a newly-added type.
    return String(type).charAt(0).toUpperCase() + String(type).slice(1);
  }

  function hangoutSlug(type) {
    // escapeHtml() does not escape quotes, so a value interpolated into an
    // attribute needs its own filter — CSS class names are [a-z0-9_-] anyway.
    return String(type).toLowerCase().replace(/[^a-z0-9_-]/g, "");
  }

  function urlFor(template, id) {
    // Templates are reversed with a 0 placeholder pk server-side. An empty
    // template means the owning contrib's URLs are not mounted.
    return template ? template.replace("/0/", "/" + id + "/") : "";
  }

  function fetchAllTiles(urlTemplate, planeId) {
    var tiles = [];

    function fetchPage(pageUrl) {
      return fetch(pageUrl, { headers: { Accept: "application/json" } })
        .then(function (resp) {
          if (!resp.ok) {
            throw new Error("tiles fetch failed: " + resp.status);
          }
          return resp.json();
        })
        .then(function (payload) {
          tiles = tiles.concat(payload.results || []);
          if (payload.next) {
            return fetchPage(payload.next);
          }
          return tiles;
        });
    }

    return fetchPage(urlFor(urlTemplate, planeId));
  }

  function escapeHtml(text) {
    var div = document.createElement("div");
    div.textContent = text === null || text === undefined ? "" : text;
    return div.innerHTML;
  }

  function tileLayer(tile) {
    var bounds = cellBounds(tile);
    if (tile.sprite_url) {
      // sprite_url comes from MAPS_TERRAIN_TILESET, which is operator-
      // controlled; Leaflet sets it as the src of an <img> it owns, so there is
      // no markup interpolation to escape here. The cell's border and its
      // active-scene highlight are CSS on that <img>.
      return L.imageOverlay(tile.sprite_url, bounds, {
        className:
          "evennia-maps-tile" + (tile.has_active_scene ? " evennia-maps-tile-active" : ""),
        alt: "",
        interactive: true,
      });
    }
    // No sprite for this terrain: draw the cell itself. Stroke and fill are
    // path options rather than CSS because an SVG path takes its colours from
    // Leaflet's inline attributes.
    return L.rectangle(bounds, {
      className: "evennia-maps-tile-blank",
      color: tile.has_active_scene ? palette.active : palette.edge,
      weight: 1,
      fillColor: tile.terrain_color || palette.tile,
      fillOpacity: 1,
    });
  }

  function lighten(hex, amount) {
    // terrain_color is validated server-side as #rgb, #rgba, #rrggbb or
    // #rrggbbaa; alpha is dropped, which is fine for a hover fill. A themed
    // fallback fill may be any CSS colour, so a non-hex value is left as is
    // and the hover shows through the stroke alone.
    if (!/^#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(hex)) {
      return hex;
    }
    var digits = hex.slice(1);
    if (digits.length <= 4) {
      digits = digits
        .slice(0, 3)
        .split("")
        .map(function (d) {
          return d + d;
        })
        .join("");
    }
    var channels = [0, 2, 4].map(function (i) {
      var value = parseInt(digits.slice(i, i + 2), 16);
      return Math.round(value + (255 - value) * amount);
    });
    return "rgb(" + channels.join(", ") + ")";
  }

  function addHover(layer, tile) {
    // Sprite tiles are <img> elements and brighten through CSS (:hover); a
    // swatch is an SVG path whose fill is an inline Leaflet attribute, so it
    // is restyled here instead.
    if (tile.sprite_url) {
      return;
    }
    var base = layer.options.fillColor;
    var stroke = layer.options.color;
    layer.on("mouseover", function () {
      layer.setStyle({ fillColor: lighten(base, 0.25), color: palette.hover, weight: 2 });
    });
    layer.on("mouseout", function () {
      layer.setStyle({ fillColor: base, color: stroke, weight: 1 });
    });
  }

  function badges(tile) {
    var items = [];
    if (tile.present && tile.present.length) {
      items.push(tile.present.length + " here");
    }
    if (tile.has_active_scene) {
      items.push("Scene now");
    }
    if (tile.upcoming_events && tile.upcoming_events.length) {
      items.push("Event soon");
    }
    if (tile.has_lore) {
      items.push("Lore here");
    }
    if (tile.hangout_type) {
      items.push(hangoutLabel(tile.hangout_type));
    }
    return items;
  }

  function tooltipContent(tile) {
    // Everything here is escaped: room and region names are player- or
    // staff-authored, and bindTooltip renders HTML.
    var html = "<strong>" + escapeHtml(tile.room_name) + "</strong>";
    var detail = [tile.terrain_label, tile.primary_region_name].filter(Boolean);
    if (detail.length) {
      html += "<div>" + escapeHtml(detail.join(" · ")) + "</div>";
    }
    var flags = badges(tile);
    if (flags.length) {
      html +=
        '<div class="evennia-maps-badges">' +
        flags
          .map(function (flag) {
            return '<span class="evennia-maps-badge">' + escapeHtml(flag) + "</span>";
          })
          .join(" ") +
        "</div>";
    }
    return html;
  }

  function portalLayers(tile) {
    // Two layers: the cell, which scales, and the glyph, which does not - the
    // arrow has to stay legible at every zoom, so it is a pin like the lore and
    // hangout markers rather than part of the cell.
    return [
      L.rectangle(cellBounds(tile), {
        className: "evennia-maps-portal-cell",
        color: palette.portal,
        weight: 1,
        fillColor: palette["portal-fill"],
        fillOpacity: 1,
      }),
      L.marker(cellCenter(tile), {
        icon: L.divIcon({
          className: "",
          html: '<div class="evennia-maps-portal-marker">&#8635;</div>',
          iconSize: [TILE_PX, TILE_PX],
        }),
        interactive: false,
      }),
    ];
  }

  function fillTemplate(template, ids) {
    // Each id replaces the first "/0/" left, so a template reversed with two
    // placeholder pks takes the plane and then the room.
    var url = template;
    ids.forEach(function (id) {
      url = url.replace("/0/", "/" + id + "/");
    });
    return url;
  }

  function detailFromTile(tile, urls) {
    // The panel without the room-detail route, or when it fails: what the
    // tile feed already carries, and no partner sections.
    function linked(items, template) {
      return (items || []).map(function (item) {
        return { id: item.id, title: item.title, url: urlFor(template, item.id) };
      });
    }
    return {
      room_name: tile.room_name,
      room_url: urlFor(urls.room, tile.room_id),
      description: "",
      terrain_label: tile.terrain_label,
      hangout_type: tile.hangout_type,
      region: tile.primary_region_id
        ? {
            name: tile.primary_region_name,
            url: urlFor(urls.region, tile.primary_region_id),
          }
        : null,
      present: tile.present || [],
      active_scenes: linked(tile.active_scenes, urls.scene),
      recent_scenes: linked(tile.recent_scenes, urls.scene),
      upcoming_events: linked(tile.upcoming_events, urls.event),
      sections: [],
    };
  }

  function el(tag, className, text) {
    // The panel is built from DOM nodes and textContent only: room names,
    // descriptions, titles and partner sections are all player- or
    // staff-authored, so none of it ever passes through markup.
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = text;
    }
    return node;
  }

  function linkOrText(label, url) {
    // URLs come from the server: reversed route templates, or section links
    // the room-detail route has already limited to site-relative paths.
    if (!url) {
      return document.createTextNode(label);
    }
    var link = el("a", "", label);
    link.href = url;
    return link;
  }

  function panelSection(title, summary, items) {
    var wrap = el("section", "evennia-maps-panel-section");
    wrap.appendChild(el("h3", "", title));
    if (summary) {
      wrap.appendChild(el("p", "evennia-maps-panel-summary", summary));
    }
    if (items && items.length) {
      var list = el("ul");
      items.forEach(function (item) {
        var row = el("li", item.locked ? "evennia-maps-panel-locked" : "");
        row.appendChild(linkOrText(item.label, item.url));
        if (item.note) {
          row.appendChild(el("span", "evennia-maps-panel-note", item.note));
        } else if (item.locked) {
          // Locked is styled, but never only styled: say it too.
          row.appendChild(el("span", "evennia-maps-panel-note", "not yet known"));
        }
        list.appendChild(row);
      });
      wrap.appendChild(list);
    }
    return wrap;
  }

  function renderPanel(titleEl, body, detail) {
    titleEl.textContent = "";
    titleEl.appendChild(linkOrText(detail.room_name, detail.room_url));
    body.textContent = "";

    var meta = [];
    if (detail.terrain_label) {
      meta.push(document.createTextNode(detail.terrain_label));
    }
    if (detail.region && detail.region.name) {
      meta.push(linkOrText(detail.region.name, detail.region.url));
    }
    if (detail.hangout_type) {
      meta.push(document.createTextNode(hangoutLabel(detail.hangout_type)));
    }
    if (meta.length) {
      var line = el("p", "evennia-maps-panel-meta");
      meta.forEach(function (node, index) {
        if (index) {
          line.appendChild(document.createTextNode(" · "));
        }
        line.appendChild(node);
      });
      body.appendChild(line);
    }
    if (detail.description) {
      body.appendChild(el("p", "evennia-maps-panel-desc", detail.description));
    }
    if (detail.present && detail.present.length) {
      body.appendChild(
        panelSection(
          "Here now",
          "",
          detail.present.map(function (name) {
            return { label: name };
          })
        )
      );
    }
    [
      ["Happening now", detail.active_scenes],
      ["Recent logs", detail.recent_scenes],
      ["Upcoming events", detail.upcoming_events],
    ].forEach(function (pair) {
      if (pair[1] && pair[1].length) {
        body.appendChild(
          panelSection(
            pair[0],
            "",
            pair[1].map(function (item) {
              return { label: item.title, url: item.url };
            })
          )
        );
      }
    });
    (detail.sections || []).forEach(function (section) {
      body.appendChild(panelSection(section.title, section.summary, section.items));
    });
    if (!body.childNodes.length) {
      body.appendChild(el("p", "evennia-maps-panel-empty", "Nothing else is known about this place yet."));
    }
  }

  function makePanel(map, detailUrlTemplate, urls) {
    // One panel per page, reused for every room. A request token drops a
    // slow answer for a room the player has already clicked away from.
    var panel = document.getElementById("evennia-maps-panel");
    if (!panel) {
      return null;
    }
    var titleEl = panel.querySelector(".evennia-maps-panel-title");
    var body = panel.querySelector(".evennia-maps-panel-body");
    var closeButton = panel.querySelector(".evennia-maps-panel-close");
    var request = 0;
    var trigger = null;

    function setOpen(open) {
      panel.hidden = !open;
      // Beside the map the panel takes width from it, so Leaflet re-measures.
      map.invalidateSize();
    }

    function close() {
      request += 1;
      setOpen(false);
      if (trigger && document.body.contains(trigger)) {
        trigger.focus();
      }
      trigger = null;
    }

    closeButton.addEventListener("click", close);
    panel.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    });

    function open(tile, planeId, from) {
      var mine = (request += 1);
      trigger = from || null;
      var fallback = detailFromTile(tile, urls);
      setOpen(true);
      if (!detailUrlTemplate) {
        renderPanel(titleEl, body, fallback);
        panel.focus();
        return;
      }
      titleEl.textContent = tile.room_name;
      body.textContent = "";
      body.appendChild(el("p", "evennia-maps-panel-empty", "Loading…"));
      panel.setAttribute("aria-busy", "true");
      panel.focus();
      fetch(fillTemplate(detailUrlTemplate, [planeId, tile.room_id]), {
        headers: { Accept: "application/json" },
      })
        .then(function (resp) {
          if (!resp.ok) {
            throw new Error("room detail fetch failed: " + resp.status);
          }
          return resp.json();
        })
        .then(function (detail) {
          if (mine === request) {
            renderPanel(titleEl, body, detail);
          }
        })
        .catch(function () {
          if (mine !== request) {
            return;
          }
          renderPanel(titleEl, body, fallback);
          body.insertBefore(
            el("p", "evennia-maps-panel-error", "Some details about this place couldn't be loaded."),
            body.firstChild
          );
        })
        .then(function () {
          if (mine === request) {
            panel.removeAttribute("aria-busy");
          }
        });
    }

    return { open: open, close: close };
  }

  function heatmapMarker(tile) {
    var count = tile.recent_scene_count || 0;
    if (!count) {
      return null;
    }
    var radius = Math.min(4 + count * 2, 16);
    return L.circleMarker(cellCenter(tile), {
      radius: radius,
      className: "evennia-maps-heatmap-marker",
    }).bindTooltip(count + " recent scene" + (count === 1 ? "" : "s"));
  }

  function lorePinMarker(tile) {
    if (!tile.has_lore) {
      return null;
    }
    return L.marker(cellCenter(tile), {
      icon: L.divIcon({
        className: "",
        html: '<div class="evennia-maps-lore-marker">&#9733;</div>',
        iconSize: [TILE_PX, TILE_PX],
      }),
    }).bindTooltip("Lore is associated with this area.");
  }

  function hangoutMarker(tile) {
    if (!tile.hangout_type) {
      return null;
    }
    var label = hangoutLabel(tile.hangout_type);
    return L.marker(cellCenter(tile), {
      icon: L.divIcon({
        className: "",
        html:
          '<div class="evennia-maps-hangout-marker evennia-maps-hangout-' +
          hangoutSlug(tile.hangout_type) +
          '">' +
          escapeHtml(label.charAt(0)) +
          "</div>",
        iconSize: [TILE_PX, TILE_PX],
      }),
    }).bindTooltip(escapeHtml(label));
  }

  function populateLayer(groups, tiles, container, onSelect) {
    var liveMapUrlTemplate = container.dataset.liveMapUrlTemplate;

    groups.tiles.clearLayers();
    groups.heatmap.clearLayers();
    groups.lore.clearLayers();
    groups.hangouts.clearLayers();

    tiles.forEach(function (tile) {
      var isPortal = tile.portal_plane_id !== null && tile.portal_plane_id !== undefined;

      if (isPortal) {
        var portal = portalLayers(tile);
        var cell = portal[0];
        // bindTooltip renders its content as HTML, so escape the room key.
        cell.bindTooltip(escapeHtml(tile.room_name) + " (portal)");
        cell.on("click", function () {
          window.location.href = urlFor(liveMapUrlTemplate, tile.portal_plane_id);
        });
        portal.forEach(function (layer) {
          groups.tiles.addLayer(layer);
        });
      } else {
        var layer = tileLayer(tile).bindTooltip(tooltipContent(tile), {
          sticky: true,
          direction: "top",
          className: "evennia-maps-tooltip",
        });
        layer.on("click", function () {
          onSelect(tile, null);
        });
        addHover(layer, tile);
        groups.tiles.addLayer(layer);
      }

      var heatmap = heatmapMarker(tile);
      if (heatmap) {
        groups.heatmap.addLayer(heatmap);
      }
      var lorePin = lorePinMarker(tile);
      if (lorePin) {
        groups.lore.addLayer(lorePin);
      }
      var hangout = hangoutMarker(tile);
      if (hangout) {
        groups.hangouts.addLayer(hangout);
      }
    });

    return groups;
  }

  function boundsFor(tiles) {
    if (!tiles.length) {
      return null;
    }
    var xs = tiles.map(function (t) {
      return t.x;
    });
    var ys = tiles.map(function (t) {
      return t.y;
    });
    // Cells occupy [n, n+1), so the far edge is max + 1 - a box drawn to max
    // alone would clip the last row and column out of the fitted view.
    return L.latLngBounds(
      [Math.min.apply(null, ys) * TILE_PX, Math.min.apply(null, xs) * TILE_PX],
      [(Math.max.apply(null, ys) + 1) * TILE_PX, (Math.max.apply(null, xs) + 1) * TILE_PX]
    );
  }

  function swatch(tile) {
    // Built as DOM nodes rather than HTML so sprite URLs and colours never
    // pass through markup.
    var node;
    if (tile.sprite_url) {
      node = document.createElement("img");
      node.src = tile.sprite_url;
      node.alt = "";
    } else {
      node = document.createElement("span");
      node.style.background = tile.terrain_color || palette.tile;
    }
    node.className = "evennia-maps-swatch";
    return node;
  }

  function terrainRows(tiles) {
    var seen = {};
    var rows = [];
    tiles.forEach(function (tile) {
      var isPortal = tile.portal_plane_id !== null && tile.portal_plane_id !== undefined;
      if (tile.terrain && !isPortal && !seen[tile.terrain]) {
        seen[tile.terrain] = true;
        rows.push(tile);
      }
    });
    return rows.sort(function (a, b) {
      return (a.terrain_label || a.terrain).localeCompare(b.terrain_label || b.terrain);
    });
  }

  function renderLegend(box, tiles) {
    box.textContent = "";
    var rows = terrainRows(tiles);
    box.hidden = !rows.length;
    if (!rows.length) {
      return;
    }
    var details = document.createElement("details");
    details.open = true;
    var summary = document.createElement("summary");
    summary.textContent = "Terrain";
    details.appendChild(summary);
    var list = document.createElement("ul");
    rows.forEach(function (tile) {
      var item = document.createElement("li");
      item.appendChild(swatch(tile));
      item.appendChild(document.createTextNode(tile.terrain_label || tile.terrain));
      list.appendChild(item);
    });
    details.appendChild(list);
    box.appendChild(details);
  }

  function renderRoomList(listEl, tiles, map, liveMapUrlTemplate, onSelect) {
    // The keyboard and screen-reader route to every tile: rooms grouped by
    // region, each a button that centres the map on the room and opens its
    // panel, returning focus to the button when the panel closes.
    listEl.textContent = "";
    var groups = {};
    tiles.forEach(function (tile) {
      var name = tile.primary_region_name || "No region";
      (groups[name] = groups[name] || []).push(tile);
    });
    Object.keys(groups)
      .sort()
      .forEach(function (name) {
        var heading = document.createElement("h2");
        heading.className = "h6 mt-3";
        heading.textContent = name;
        listEl.appendChild(heading);
        var list = document.createElement("ul");
        list.className = "list-unstyled";
        groups[name]
          .sort(function (a, b) {
            return a.room_name.localeCompare(b.room_name);
          })
          .forEach(function (tile) {
            var item = document.createElement("li");
            var button = document.createElement("button");
            button.type = "button";
            button.className = "btn btn-link btn-sm p-0";
            var isPortal = tile.portal_plane_id !== null && tile.portal_plane_id !== undefined;
            button.textContent = tile.room_name + (isPortal ? " (portal)" : "");
            button.addEventListener("click", function () {
              if (isPortal) {
                window.location.href = urlFor(liveMapUrlTemplate, tile.portal_plane_id);
                return;
              }
              map.setView(cellCenter(tile), Math.max(map.getZoom(), 1));
              onSelect(tile, button);
            });
            item.appendChild(button);
            var detail = [tile.terrain_label].concat(badges(tile)).filter(Boolean);
            if (detail.length) {
              var note = document.createElement("span");
              note.className = "text-muted small ml-2";
              note.textContent = detail.join(" · ");
              item.appendChild(note);
            }
            list.appendChild(item);
          });
        listEl.appendChild(list);
      });
  }

  function showError(container, message) {
    // Sibling of the map container, not a child — Leaflet owns the
    // container's children and would clear an injected node.
    var banner = container.parentNode.querySelector(".evennia-maps-error");
    if (!banner) {
      banner = document.createElement("div");
      banner.className = "evennia-maps-error";
      container.parentNode.insertBefore(banner, container.nextSibling);
    }
    banner.textContent = message;
  }

  function init() {
    var container = document.getElementById("evennia-maps-live");
    if (!container) {
      return;
    }
    if (typeof L === "undefined") {
      showError(container, "The map library could not be loaded.");
      return;
    }
    readPalette(container);

    var tilesUrlTemplate = container.dataset.tilesUrlTemplate;
    var layers = JSON.parse(container.dataset.layers || "[]");
    var currentPlaneId = parseInt(container.dataset.planeId, 10);

    var map = L.map(container, { crs: L.CRS.Simple, minZoom: -4, maxZoom: 4 });
    map.setView([0, 0], 0);

    // One group per sibling elevation, created eagerly and empty so the
    // layer control holds a stable object; contents arrive lazily.
    var groupsById = {};
    var loading = {};
    layers.forEach(function (layer) {
      groupsById[layer.id] = L.layerGroup();
    });
    if (!groupsById[currentPlaneId]) {
      groupsById[currentPlaneId] = L.layerGroup();
    }

    // Overlay groups are shared across elevations (only one elevation is
    // ever the active base layer), so they're rebuilt from that elevation's
    // tiles on every load() rather than kept per-plane like groupsById.
    var overlayGroups = {
      heatmap: L.layerGroup(),
      lore: L.layerGroup(),
      hangouts: L.layerGroup(),
    };

    var urls = {
      room: container.dataset.roomUrlTemplate,
      region: container.dataset.regionUrlTemplate,
      scene: container.dataset.sceneUrlTemplate,
      event: container.dataset.eventUrlTemplate,
    };
    var panel = makePanel(map, container.dataset.tileDetailUrlTemplate, urls);

    function selectFor(planeId) {
      return function (tile, from) {
        if (panel) {
          panel.open(tile, planeId, from);
          return;
        }
        // A game template from before the room panel has no <aside> for it:
        // name the room in a plain popup rather than doing nothing.
        L.popup()
          .setLatLng(cellCenter(tile))
          .setContent("<strong>" + escapeHtml(tile.room_name) + "</strong>")
          .openOn(map);
      };
    }

    var legend = L.control({ position: "bottomright" });
    legend.onAdd = function () {
      var box = L.DomUtil.create("div", "evennia-maps-terrain-key");
      L.DomEvent.disableClickPropagation(box);
      L.DomEvent.disableScrollPropagation(box);
      box.hidden = true;
      return box;
    };
    legend.addTo(map);

    var listToggle = document.getElementById("evennia-maps-list-toggle");
    var listEl = document.getElementById("evennia-maps-list");
    if (listToggle && listEl) {
      listToggle.addEventListener("click", function () {
        var open = listToggle.getAttribute("aria-expanded") === "true";
        listToggle.setAttribute("aria-expanded", open ? "false" : "true");
        listEl.hidden = open;
      });
    }

    function load(planeId, fit) {
      if (!loading[planeId]) {
        loading[planeId] = fetchAllTiles(tilesUrlTemplate, planeId);
      }
      return loading[planeId]
        .then(function (tiles) {
          var onSelect = selectFor(planeId);
          populateLayer(
            {
              tiles: groupsById[planeId],
              heatmap: overlayGroups.heatmap,
              lore: overlayGroups.lore,
              hangouts: overlayGroups.hangouts,
            },
            tiles,
            container,
            onSelect
          );
          renderLegend(legend.getContainer(), tiles);
          if (listToggle && listEl) {
            renderRoomList(
              listEl,
              tiles,
              map,
              container.dataset.liveMapUrlTemplate,
              onSelect
            );
            listToggle.hidden = !tiles.length;
          }
          var bounds = fit ? boundsFor(tiles) : null;
          if (bounds) {
            map.fitBounds(bounds, { padding: [40, 40], maxZoom: 2 });
          }
        })
        .catch(function () {
          // Most often a 403: the tiles API requires an authenticated
          // account, while this page itself may be public.
          showError(container, "Could not load map tiles. You may need to log in.");
        });
    }

    groupsById[currentPlaneId].addTo(map);
    load(currentPlaneId, true);

    var overlayLayers = {
      "Activity heatmap": overlayGroups.heatmap,
      "Lore pins": overlayGroups.lore,
      Hangouts: overlayGroups.hangouts,
    };

    if (layers.length > 1) {
      var baseLayers = {};
      layers.forEach(function (layer) {
        baseLayers[layer.name] = groupsById[layer.id];
      });
      L.control.layers(baseLayers, overlayLayers, { collapsed: false }).addTo(map);
      map.on("baselayerchange", function (event) {
        var selected = layers.find(function (layer) {
          return groupsById[layer.id] === event.layer;
        });
        if (selected) {
          load(selected.id, true);
        }
      });
    } else {
      L.control.layers(null, overlayLayers, { collapsed: false }).addTo(map);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
