# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Guide pages: Markdown files with YAML front matter.

::

    ---
    key: resources                  # required: a-z, 0-9, '-' and '_'
    title: Gathering & resources    # required
    kind: guide                     # guide (default) | principle | term
    category: Making & trading      # web index grouping (guides)
    audience: player                # player (default) | staff
    requires: RP_RESOURCES_REVEALED # a check name, or a list (all must pass)
    aliases: [gathering]            # other keys that find this page
    principles: [no-quota]          # principle pages this page illustrates
    summary: One line for cards, link hovers and the glossary.
    order: 10                       # sort within a category (default 100)
    footer: false                   # true: linked from every page's footer
    ---
    Body, in the syntax described in ``evennia_guides.markup``.

Pages are read from every installed app's ``guides/`` directory, in
``INSTALLED_APPS`` order, then from each of ``GUIDES_DIRS``. A page whose key
was already loaded replaces the earlier one: that's how a game restates a
contrib's page in its own voice. Files load once per process; a bad file is
logged and skipped, so one typo can't take the guide down. ``validate()`` (and
the ``guides_check`` management command) reports everything that was skipped
or looks wrong.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from django.apps import apps
from django.core.signals import setting_changed
from django.dispatch import receiver

from evennia_guides import checks, conf, markup

logger = logging.getLogger("evennia")

KINDS = ("guide", "principle", "term")
AUDIENCES = ("player", "staff")
# Web routes beside /<key>/.
RESERVED_KEYS = frozenset({"principles", "glossary"})
_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(?P<meta>.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_FIELDS = frozenset(
    {
        "key",
        "title",
        "kind",
        "category",
        "audience",
        "requires",
        "aliases",
        "principles",
        "summary",
        "order",
        "footer",
    }
)


class GuideError(ValueError):
    """A page file that can't be loaded; the message says why."""


@dataclass(frozen=True)
class Page:
    key: str
    title: str
    document: object
    body: str
    source: str
    origin: str
    kind: str = "guide"
    category: str = "General"
    audience: str = "player"
    requires: tuple = ()
    aliases: tuple = ()
    principles: tuple = ()
    summary: str = ""
    order: int = 100
    footer: bool = False


def _str_list(meta, name):
    value = meta.get(name) or ()
    if isinstance(value, str):
        value = (value,)
    if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
        raise GuideError(f"'{name}' must be a string or a list of strings")
    return tuple(v.strip() for v in value if v.strip())


def parse_page(text, *, source="<string>", origin=""):
    """
    Parse one page file.

    Raises:
        GuideError: no front matter, a missing or bad field, or a body that
            ``markup.parse`` rejects.
    """
    text = text.removeprefix("﻿")
    match = _FRONT_MATTER.match(text)
    if not match:
        raise GuideError("no front matter: the file must start with a '---' line")
    try:
        meta = yaml.safe_load(match.group("meta")) or {}
    except yaml.YAMLError as err:
        raise GuideError(f"bad front matter: {err}") from None
    if not isinstance(meta, dict):
        raise GuideError("front matter must be a mapping")
    unknown = set(meta) - _FIELDS
    if unknown:
        raise GuideError(f"unknown front matter field(s): {', '.join(sorted(unknown))}")

    key = str(meta.get("key") or "").strip().lower()
    if not _KEY.match(key):
        raise GuideError(f"bad or missing key {key!r}: use a-z, 0-9, '-' and '_'")
    if key in RESERVED_KEYS:
        raise GuideError(f"key {key!r} is reserved for a guide route")
    title = str(meta.get("title") or "").strip()
    if not title:
        raise GuideError("missing title")
    kind = meta.get("kind", "guide")
    if kind not in KINDS:
        raise GuideError(f"kind must be one of {', '.join(KINDS)}")
    audience = meta.get("audience", "player")
    if audience not in AUDIENCES:
        raise GuideError(f"audience must be one of {', '.join(AUDIENCES)}")
    order = meta.get("order", 100)
    if not isinstance(order, int) or isinstance(order, bool):
        raise GuideError("order must be a whole number")

    body = text[match.end() :]
    try:
        document = markup.parse(body)
    except markup.MarkupError as err:
        raise GuideError(str(err)) from None
    return Page(
        key=key,
        title=title,
        document=document,
        body=body,
        source=source,
        origin=origin,
        kind=kind,
        category=str(meta.get("category") or "General").strip(),
        audience=audience,
        requires=_str_list(meta, "requires"),
        aliases=tuple(alias.lower() for alias in _str_list(meta, "aliases")),
        principles=tuple(tag.lower() for tag in _str_list(meta, "principles")),
        summary=str(meta.get("summary") or "").strip(),
        order=order,
        footer=bool(meta.get("footer", False)),
    )


def guide_dirs():
    """[(origin, Path)] in load order: each app's guides/, then GUIDES_DIRS."""
    found = []
    for config in apps.get_app_configs():
        path = Path(config.path) / "guides"
        if path.is_dir():
            found.append((config.label, path))
    for path in conf.get("GUIDES_DIRS"):
        found.append(("host", Path(path)))
    return found


@dataclass
class Registry:
    pages: dict
    aliases: dict
    errors: list  # [(source, message)]
    replaced: list  # [(key, replaced source, by source)]


def load():
    """Read every page from disk, in load order. Doesn't touch the cache."""
    pages, errors, replaced = {}, [], []
    for origin, directory in guide_dirs():
        if not directory.is_dir():
            errors.append((str(directory), "GUIDES_DIRS entry is not a directory"))
            continue
        for path in sorted(directory.glob("*.md")):
            try:
                page = parse_page(path.read_text(encoding="utf-8"), source=str(path), origin=origin)
            except (GuideError, OSError, UnicodeDecodeError) as err:
                errors.append((str(path), str(err)))
                logger.error("evennia_guides: skipped %s: %s", path, err)
                continue
            if page.key in pages:
                replaced.append((page.key, pages[page.key].source, page.source))
            pages[page.key] = page
    aliases = {}
    for page in pages.values():
        for alias in page.aliases:
            if alias not in pages:
                aliases.setdefault(alias, page.key)
    return Registry(pages, aliases, errors, replaced)


_cache = None


def registry():
    """The loaded pages, read from disk on first use."""
    global _cache
    if _cache is None:
        _cache = load()
    return _cache


def reset():
    """Forget the loaded pages; the next read loads them again."""
    global _cache
    _cache = None


@receiver(setting_changed)
def _reset_on_setting_change(setting, **kwargs):
    if setting.startswith("GUIDES_") or setting == "INSTALLED_APPS":
        reset()


def get_page(key):
    """The page with this key or alias, or None. Doesn't check visibility."""
    reg = registry()
    key = key.lower()
    return reg.pages.get(key) or reg.pages.get(reg.aliases.get(key, ""))


def all_pages():
    """Every loaded page, sorted by kind, category, order and title."""
    return sorted(
        registry().pages.values(),
        key=lambda page: (KINDS.index(page.kind), page.category, page.order, page.title.lower()),
    )


def validate():
    """
    Check every page and report problems: [(level, source, message)].

    ``error``: a skipped file, a link or principle tag naming no page, a check
    name that resolves to nothing, an alias that collides. ``info``: a page
    replaced by a later one with the same key.
    """
    reg = registry()
    problems = [("error", source, message) for source, message in reg.errors]
    problems += [
        ("info", by, f"replaces {key!r} from {replaced}") for key, replaced, by in reg.replaced
    ]
    claimed = {}
    for page in reg.pages.values():
        for alias in page.aliases:
            if alias in reg.pages:
                problems.append(("error", page.source, f"alias {alias!r} is another page's key"))
            elif claimed.setdefault(alias, page.key) != page.key:
                problems.append(
                    ("error", page.source, f"alias {alias!r} is also {claimed[alias]!r}'s alias")
                )
        for key in dict.fromkeys(page.document.links()):
            if key not in reg.pages and key not in reg.aliases:
                problems.append(("error", page.source, f"link [[{key}]] names no page"))
        tags = set(page.principles)
        for insight in page.document.insights():
            tags.update(insight.tags)
        for tag in sorted(tags):
            target = reg.pages.get(tag)
            if target is None or target.kind != "principle":
                problems.append(
                    ("error", page.source, f"principle {tag!r} names no principle page")
                )
        for name in page.requires:
            if not checks.is_known(name):
                problems.append(("error", page.source, f"check {name!r} resolves to nothing"))
    return problems
