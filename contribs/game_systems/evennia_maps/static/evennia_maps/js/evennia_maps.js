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
 * Overlay data arrives only from whichever partner contribs the game has
 * installed (evennia_regions/scenes/lore/calendar). Absent ones simply
 * leave their field at its empty value, and an outbound URL template that
 * came back empty means that contrib's pages aren't mounted — the link is
 * dropped rather than pointed at nothing.
 */
(function () {
  "use strict";

  var TILE_PX = 32;

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

  function tileIcon(tile) {
    var classes =
      "evennia-maps-tile-icon" + (tile.has_active_scene ? " evennia-maps-tile-active" : "");
    // sprite_url comes from MAPS_TERRAIN_TILESET (operator-controlled),
    // room_name from a builder-settable room key — escape both anyway, so a
    // room named with markup can't inject into the marker.
    var inner = tile.sprite_url ? '<img src="' + escapeHtml(tile.sprite_url) + '" alt="" />' : "";
    return L.divIcon({
      className: "",
      html: '<div class="' + classes + '">' + inner + "</div>",
      iconSize: [TILE_PX, TILE_PX],
    });
  }

  function portalIcon() {
    return L.divIcon({
      className: "",
      html: '<div class="evennia-maps-portal-marker">&#8635;</div>',
      iconSize: [TILE_PX, TILE_PX],
    });
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
    var html = '<div class="evennia-maps-popup"><h3>' + escapeHtml(tile.room_name) + "</h3>";
    if (tile.has_active_scene) {
      html += "<div>A scene is active here.</div>";
    }
    if (tile.hangout_type) {
      html += "<div>" + escapeHtml(hangoutLabel(tile.hangout_type)) + "</div>";
    }
    if (tile.primary_region_id && urls.region) {
      html += '<a href="' + urlFor(urls.region, tile.primary_region_id) + '">View region</a>';
    }
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
    return L.circleMarker([tile.y, tile.x], {
      radius: radius,
      className: "evennia-maps-heatmap-marker",
    }).bindTooltip(count + " recent scene" + (count === 1 ? "" : "s"));
  }

  function lorePinMarker(tile) {
    if (!tile.has_lore) {
      return null;
    }
    return L.marker([tile.y, tile.x], {
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
    return L.marker([tile.y, tile.x], {
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
      var marker = L.marker([tile.y, tile.x], {
        icon: isPortal ? portalIcon() : tileIcon(tile),
      });

      if (isPortal) {
        // bindTooltip renders its content as HTML, so escape the room key.
        marker.bindTooltip(escapeHtml(tile.room_name) + " (portal)");
        marker.on("click", function () {
          window.location.href = urlFor(liveMapUrlTemplate, tile.portal_plane_id);
        });
      } else {
        marker.bindPopup(popupContent(tile, urls));
      }
      groups.tiles.addLayer(marker);

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
    return L.latLngBounds(
      [Math.min.apply(null, ys), Math.min.apply(null, xs)],
      [Math.max.apply(null, ys), Math.max.apply(null, xs)]
    );
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

    function load(planeId, fit) {
      if (!loading[planeId]) {
        loading[planeId] = fetchAllTiles(tilesUrlTemplate, planeId);
      }
      return loading[planeId]
        .then(function (tiles) {
          populateLayer(
            {
              tiles: groupsById[planeId],
              heatmap: overlayGroups.heatmap,
              lore: overlayGroups.lore,
              hangouts: overlayGroups.hangouts,
            },
            tiles,
            container
          );
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
