# Migration notes

This is a new standalone contribution. No existing source tables, migrations,
read markers or pending queues change. `tests/` separates transactional,
concurrency and rendered-page contracts as the suite grows.

The initial migration was extracted from `makemigrations evennia_notices
--dry-run --verbosity 3`. Only the contrib migration was saved; the generated
Evennia proxy migration was discarded. Its ObjectDB dependency is `__first__`
and its account dependency uses Django's established swappable model dependency.
