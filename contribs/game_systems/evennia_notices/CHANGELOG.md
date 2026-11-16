# Changelog

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
