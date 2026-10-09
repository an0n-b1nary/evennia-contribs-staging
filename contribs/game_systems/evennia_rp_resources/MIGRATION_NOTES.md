# Adoption notes

This contrib introduces new tables and has no legacy schema to migrate.
Install links 0.6 or newer, add the apps, run migrations, seed a generic
catalogue, register the commands and wire the server-start and login hooks.
Resource keys remain stable for the lifetime of the game; archive retired
entries. Batch receipts and grant history should be retained for audit.
