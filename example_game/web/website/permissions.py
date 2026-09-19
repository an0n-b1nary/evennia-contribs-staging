"""Compatibility exports for the shared web permission policy.

Native example-game pages and every installed contrib now use the same
``evennia_links.is_staff_user`` predicate. Keeping this module as a re-export
preserves the import path used by existing game-local code without creating a
second implementation.
"""

from evennia_links import is_staff_user

__all__ = ["is_staff_user"]
