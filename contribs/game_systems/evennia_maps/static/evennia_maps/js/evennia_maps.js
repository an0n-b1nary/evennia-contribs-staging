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
 * Recent logs and upcoming events render into the ordinary tile popup
 * instead of a separate layer, since they're per-tile detail rather than a
 * map-wide pattern. Every overlay is privacy-filtered server-side exactly
 * like the base tile data; this file never re-derives visibility.
 *
 * Terrain display (label, colour, sprite) comes from MAPS_TERRAINS on the
 * server (terrain.terrain_style), so this file never needs the vocabulary.
 * Tiles brighten on hover and carry a tooltip; a terrain legend sits in the
 * corner, and a room list beneath the map gives keyboard and screen-reader
 * users every tile, each with a button that opens the same popup.
 *
 * Overlay data arrives only from whichever partner contribs the game has
 * installed (evennia_regions/scenes/lore/calendar). Absent ones simply
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

  // Swatch for a tile whose terrain has neither a sprite nor a colour.
  var FALLBACK_FILL = "#3a3a3a";

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
      color: tile.has_active_scene ? "#ffce54" : "rgba(255, 255, 255, 0.25)",
      weight: 1,
      fillColor: tile.terrain_color || FALLBACK_FILL,
      fillOpacity: 1,
    });
  }

  function lighten(hex, amount) {
    // terrain_color is validated server-side as #rgb, #rgba, #rrggbb or
    // #rrggbbaa; alpha is dropped, which is fine for a hover fill.
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
      layer.setStyle({ fillColor: lighten(base, 0.25), color: "#ffffff", weight: 2 });
    });
    layer.on("mouseout", function () {
      layer.setStyle({ fillColor: base, color: stroke, weight: 1 });
    });
  }

  function badges(tile) {
    var items = [];
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
        color: "#b39ddb",
        weight: 1,
        fillColor: "#2b2536",
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

  function linkList(heading, items, urlTemplate) {
    if (!items || !items.length || !urlTemplate) {
      return "";
    }
    // Titles are player-authored, so they are escaped here even though the
    // server resolved the fallback.
    var html = "<div>" + heading + ":<ul>";
    items.forEach(function (item) {
      html +=
        '<li><a href="' +
        urlFor(urlTemplate, item.id) +
        '">' +
        escapeHtml(item.title) +
        "</a></li>";
    });
    return html + "</ul></div>";
  }

  function popupContent(tile, urls) {
    var roomLabel = escapeHtml(tile.room_name);
    if (urls.room) {
      roomLabel = '<a href="' + urlFor(urls.room, tile.room_id) + '">' + roomLabel + "</a>";
    }
    var html = '<div class="evennia-maps-popup"><h3>' + roomLabel + "</h3>";
    if (tile.has_active_scene) {
      html += "<div>A scene is active here.</div>";
    }
    if (tile.hangout_type) {
      html += "<div>" + escapeHtml(hangoutLabel(tile.hangout_type)) + "</div>";
    }
    if (tile.primary_region_id && urls.region) {
      html += '<a href="' + urlFor(urls.region, tile.primary_region_id) + '">View region</a>';
    }
    html += linkList("Happening now", tile.active_scenes, urls.scene);
    html += linkList("Recent logs", tile.recent_scenes, urls.scene);
    html += linkList("Upcoming events", tile.upcoming_events, urls.event);
    return html + "</div>";
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

  function populateLayer(groups, tiles, container) {
    var urls = {
      room: container.dataset.roomUrlTemplate,
      region: container.dataset.regionUrlTemplate,
      scene: container.dataset.sceneUrlTemplate,
      event: container.dataset.eventUrlTemplate,
    };
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
        var layer = tileLayer(tile)
          .bindPopup(popupContent(tile, urls))
          .bindTooltip(tooltipContent(tile), {
            sticky: true,
            direction: "top",
            className: "evennia-maps-tooltip",
          });
        addHover(layer, tile);
        if (groups.byRoom) {
          groups.byRoom[tile.room_id] = layer;
        }
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
      node.style.background = tile.terrain_color || FALLBACK_FILL;
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

  function renderRoomList(listEl, tiles, byRoom, map, liveMapUrlTemplate) {
    // The keyboard and screen-reader route to every tile: rooms grouped by
    // region, each a button that opens the tile's popup on the map.
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
              var layer = byRoom[tile.room_id];
              if (layer) {
                var centre = cellCenter(tile);
                map.setView(centre, Math.max(map.getZoom(), 1));
                layer.openPopup(centre);
              }
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
    var byRoomById = {};

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
          byRoomById[planeId] = {};
          populateLayer(
            {
              tiles: groupsById[planeId],
              heatmap: overlayGroups.heatmap,
              lore: overlayGroups.lore,
              hangouts: overlayGroups.hangouts,
              byRoom: byRoomById[planeId],
            },
            tiles,
            container
          );
          renderLegend(legend.getContainer(), tiles);
          if (listToggle && listEl) {
            renderRoomList(
              listEl,
              tiles,
              byRoomById[planeId],
              map,
              container.dataset.liveMapUrlTemplate
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
