# Changelog

## 0.1.2 — 2026-11-26

- `+notices/settings` and the web preferences page omit sources whose optional
  `available(context)` hook does not admit the viewer; `+notices/set` and web
  POSTs refuse them with the same reply as an unknown source. Stored choices are
  kept and apply again once the source is available. Requires Links 0.8.17.
- `PreferenceForm` now requires a keyword-only `context`.
- `set_preference` raises `UnknownPreference`, a `ValueError` subclass with the
  unchanged message, when it refuses an unknown or unavailable source or an
  unknown mode.

## 0.1.1 — 2026-11-09

- Call optional authorized source preparation hooks before login/puppet summaries,
  isolating each source failure. Existing sources without a hook stay supported.
- Backlog transfers remain quiet, including must-act notices; newly created
  immediate notices retain their one hint attempt.
- Calendar can import its pending notices before the first summary, independently
  of signal receiver registration order.

## 0.1.0 — 2026-11-08

- Add an optional durable inbox with source-owned privacy and action evaluation,
  content-free replay receipts, preferences, aggregation, history and web/command surfaces.
