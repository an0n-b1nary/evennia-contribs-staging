"""Test-suite settings for the contrib sandbox game.

Used only by the test run, never by the live server. Invocation (run from
example_game/, with the sandbox venv's `evennia` on PATH):

    evennia test --settings test_settings.py typeclasses commands world

The PASSWORD_HASHERS override swaps Django's deliberately-slow PBKDF2
hasher for MD5 so account creation in test setUp isn't the dominant cost
of the suite — the same trick scripts/ci_install_contribs.py applies to
the throwaway CI game. settings.py explicitly documents that the fast
hasher must never go into the production-shaped settings file; it belongs
only here.
"""

from server.conf.settings import *  # noqa: F403

# Deliberate test-only speedup: MD5 hashes still verify, so behavior is
# unchanged; hashing just stops dominating the run. NEVER copy this into
# settings.py (see the warning comment in its "Public exposure" section).
PASSWORD_HASHERS = ("django.contrib.auth.hashers.MD5PasswordHasher",)
