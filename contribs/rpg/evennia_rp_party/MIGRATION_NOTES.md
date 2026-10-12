# Migration notes

## Initial 0.1.0 install

No models or Django migrations are added. Combat must be 0.2.1 or newer.
Registration initializes a schema-1 Party envelope on load, including for
older retained combat fights. No existing participant is automatically
partied. Frozen builds and historical journal snapshots remain untouched.

After removal, combat preserves the envelope and disables Party modifiers.
Reinstall with the same stable provider key `party`; declarations made while
absent never gain modifiers retroactively. Back up populated fight data
before upgrades; staff rollback upgrades old checkpoint state on load.
