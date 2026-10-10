# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
The guide page body: CommonMark plus two additions, rendered to HTML.

- ``:::insight[Title]{principle-key, ...}`` ... ``:::`` is a Design insight,
  placed right after the paragraph it comments on. The ``{...}`` tags are
  optional; each names a principle page.
- ``[[key]]`` or ``[[key|label]]`` links to another guide page. A link to a
  page the reader can't see is plain text, so it can't reveal that the page
  exists.

Container lines start at column 0; insights don't nest. A top-level
``## Heading`` starts a section, listed in the page's table of contents.

Raw HTML in a page is shown as text, never passed through.
"""

import re
from dataclasses import dataclass, field
from html import escape

from django.utils.text import slugify
from markdown_it import MarkdownIt

_OPEN = re.compile(
    r"^:::\s*(?P<kind>[a-z]+)\s*(?:\[(?P<arg>[^\]]*)\])?\s*(?:\{(?P<tags>[^}]*)\})?\s*$"
)
_CLOSE = re.compile(r"^:::\s*$")
_FENCE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})")
_H2 = re.compile(r"^##[ \t]+(?P<text>.+?)[ \t]*#*[ \t]*$")
WIKILINK = re.compile(r"\[\[([a-z0-9][a-z0-9_-]*)(?:\|([^\]\n]+))?\]\]", re.IGNORECASE)


class MarkupError(ValueError):
    """A page body that can't be parsed; the message names the line."""


@dataclass
class Text:
    source: str
    tokens: list


@dataclass
class Insight:
    title: str
    tags: tuple
    anchor: str
    blocks: list = field(default_factory=list)


@dataclass
class Section:
    heading: str | None
    anchor: str | None
    blocks: list = field(default_factory=list)


@dataclass
class Document:
    sections: list

    def insights(self):
        """Every insight, in page order."""
        return [
            block
            for section in self.sections
            for block in section.blocks
            if isinstance(block, Insight)
        ]

    def links(self):
        """The key of every ``[[link]]``, in page order (not ones inside code)."""
        keys = []
        for section in self.sections:
            if section.heading:
                keys += [key.lower() for key, _label in WIKILINK.findall(section.heading)]
            texts = [
                text
                for block in section.blocks
                for text in (block.blocks if isinstance(block, Insight) else [block])
            ]
            for text in texts:
                for token in text.tokens:
                    keys += [
                        child.meta["key"]
                        for child in token.children or ()
                        if child.type == "guide_link"
                    ]
        return keys


@dataclass
class RenderContext:
    """
    What the renderer needs to know about the reader.

    Args:
        staff: the reader may follow links to pages hidden from players (marked).
        resolve: ``resolve(key) -> (page, visible_to_players)`` or None for an
            unknown key.
        page_url: ``page_url(page) -> str``.
    """

    staff: bool
    resolve: object
    page_url: object

    def link(self, key):
        """``(page, hidden)``: the page this reader may follow, or ``(None, False)``."""
        found = self.resolve(key.lower())
        if found is None:
            return None, False
        page, visible = found
        if visible:
            return page, False
        return (page, True) if self.staff else (None, False)


def _wikilink_rule(state, silent):
    if not state.src.startswith("[[", state.pos):
        return False
    match = WIKILINK.match(state.src, state.pos)
    if not match:
        return False
    if not silent:
        token = state.push("guide_link", "", 0)
        token.meta = {"key": match.group(1).lower(), "label": (match.group(2) or "").strip()}
    state.pos = match.end()
    return True


def _render_guide_link(self, tokens, idx, options, env):
    meta = tokens[idx].meta
    ctx = env["ctx"]
    page, hidden = ctx.link(meta["key"])
    if meta["label"]:
        label = meta["label"]
    elif page is not None:
        label = page.title
    else:
        label = meta["key"].replace("-", " ").replace("_", " ")
    if page is None:
        return escape(label)
    attrs = f' href="{escape(ctx.page_url(page))}"'
    if hidden:
        attrs += ' class="evennia-guides-link-hidden" title="Hidden from players"'
    elif page.summary:
        attrs += f' title="{escape(page.summary)}"'
    return f"<a{attrs}>{escape(label)}</a>"


def _render_table_open(self, tokens, idx, options, env):
    return (
        '<div class="evennia-guides-table-scroll" role="region" aria-label="Table" tabindex="0">\n'
        '<table class="table table-sm">\n'
    )


def _render_table_close(self, tokens, idx, options, env):
    return "</table>\n</div>\n"


def _build_markdown():
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    md.inline.ruler.before("link", "guide_link", _wikilink_rule)
    md.add_render_rule("guide_link", _render_guide_link)
    md.add_render_rule("table_open", _render_table_open)
    md.add_render_rule("table_close", _render_table_close)
    return md


MD = _build_markdown()


class _Anchors:
    def __init__(self):
        self.used = set()

    def make(self, text, prefix=""):
        base = prefix + (slugify(text) or "section")
        anchor, n = base, 2
        while anchor in self.used:
            anchor, n = f"{base}-{n}", n + 1
        self.used.add(anchor)
        return anchor


def parse(body):
    """
    Parse a page body into a Document.

    Raises:
        MarkupError: an unknown, nested or unclosed block, a stray ``:::``, or
            an insight with no title.
    """
    anchors = _Anchors()
    sections = [Section(None, None)]
    insight = None
    lines = []
    fence = None

    def flush():
        text = "\n".join(lines)
        lines.clear()
        if text.strip():
            target = insight if insight is not None else sections[-1]
            target.blocks.append(Text(text, MD.parse(text)))

    for lineno, line in enumerate(body.splitlines(), 1):
        if fence:
            lines.append(line)
            stripped = line.strip()
            if stripped.startswith(fence) and set(stripped) == {fence[0]}:
                fence = None
            continue
        match = _FENCE.match(line)
        if match:
            fence = match.group("fence")
            lines.append(line)
            continue
        match = _OPEN.match(line)
        if match:
            if match.group("kind") != "insight":
                raise MarkupError(f"line {lineno}: unknown block ':::{match.group('kind')}'")
            if insight is not None:
                raise MarkupError(f"line {lineno}: an insight can't sit inside another insight")
            title = (match.group("arg") or "").strip()
            if not title:
                raise MarkupError(f"line {lineno}: ':::insight' needs a title: :::insight[Title]")
            flush()
            tags = tuple(
                tag.strip().lower() for tag in (match.group("tags") or "").split(",") if tag.strip()
            )
            insight = Insight(title, tags, anchors.make(title, prefix="insight-"))
            sections[-1].blocks.append(insight)
            continue
        if _CLOSE.match(line):
            if insight is None:
                raise MarkupError(f"line {lineno}: ':::' closes nothing")
            flush()
            insight = None
            continue
        match = _H2.match(line)
        if match and insight is None:
            flush()
            heading = match.group("text")
            sections.append(Section(heading, anchors.make(heading)))
            continue
        lines.append(line)
    if insight is not None:
        raise MarkupError(f"the ':::insight[{insight.title}]' block is never closed")
    flush()
    return Document(sections)


def render_html(document, ctx):
    """
    Render a page body for one reader.

    Returns:
        tuple: ``(html, toc)``, where ``toc`` is ``[(anchor, heading text), ...]``.
    """
    env = {"ctx": ctx}
    parts, toc = [], []
    for section in document.sections:
        if section.heading:
            parts.append(
                f'<h2 id="{section.anchor}">{MD.renderInline(section.heading, env)}</h2>\n'
            )
            toc.append((section.anchor, _plain(section.heading)))
        for block in section.blocks:
            if isinstance(block, Insight):
                parts.append(_render_insight(block, ctx, env))
            else:
                parts.append(MD.renderer.render(block.tokens, MD.options, env))
    return "".join(parts), toc


def _plain(source):
    """Heading text without markup, for the table of contents."""
    text = WIKILINK.sub(lambda m: m.group(2) or m.group(1).replace("-", " "), source)
    return re.sub(r"[*_`]", "", text).strip()


def _render_insight(insight, ctx, env):
    title = escape(insight.title)
    body = "".join(MD.renderer.render(block.tokens, MD.options, env) for block in insight.blocks)
    principles = []
    for tag in insight.tags:
        page, hidden = ctx.link(tag)
        if page is not None and not hidden:
            principles.append(f'<a href="{escape(ctx.page_url(page))}">{escape(page.title)}</a>')
    tags = (
        f'<p class="evennia-guides-insight-tags">Principle: {", ".join(principles)}</p>\n'
        if principles
        else ""
    )
    return (
        f'<aside class="evennia-guides-insight" id="{insight.anchor}" '
        f'aria-label="Design insight: {title}">\n'
        '<p class="evennia-guides-insight-label">Design insight</p>\n'
        f'<p class="evennia-guides-insight-title">{title}</p>\n'
        f"{body}{tags}</aside>\n"
    )
