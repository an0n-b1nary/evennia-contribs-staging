# Terrain swatches

Four 32x32 flat-colour PNGs, ~100 bytes each, referenced by
`MAPS_TERRAIN_TILESET` in `server/conf/settings.py`.

**These are placeholders, not art.** They exist so the web map has something
to draw that is visibly *not* the fallback swatch, which is the only way to
demonstrate that `MAPS_TERRAIN_TILESET` does anything. Replace them with real
tile art of the same dimensions and nothing else needs to change.

There is deliberately no `scrub.png`, even though `scrub` is a valid terrain
in `MAPS_TERRAIN_PRECEDENCE`. The seeded Causeway carries that terrain, so one
tile on the grid always renders as the map's plain fallback swatch beside the
sprited ones. Adding `scrub.png` here (and a line in the tileset) would remove
that demonstration.
