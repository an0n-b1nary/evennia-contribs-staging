# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
The web guide. Mount it under one namespace-carrying include::

    path("guide/", include("evennia_guides.urls"))

Views:
    /guide/              GuideIndexView       guide pages by category
    /guide/principles/   GuidePrinciplesView  each principle and the insights tagged with it
    /guide/glossary/     GuideGlossaryView    every term
    /guide/<key>/        GuidePageView        one page

Everything is public; staff (``GUIDES_STAFF_LOCK``) also see staff pages and
pages hidden from players, marked. A page a reader can't see is a 404, the
same as a page that doesn't exist.
"""

from urllib.parse import urlencode

from django.http import Http404
from django.urls import NoReverseMatch, reverse
from django.utils.safestring import mark_safe
from django.views.generic import TemplateView

from evennia_guides import checks, conf, pages, render


class GuideMixin:
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.staff = checks.is_staff(getattr(request, "user", None))

    def visible(self, kind=None):
        return [
            page
            for page in pages.all_pages()
            if (kind is None or page.kind == kind) and checks.can_view(page, staff=self.staff)
        ]

    def entry(self, page):
        """A page's listing entry: the page, its URL, and why it's hidden (staff)."""
        return {"page": page, "url": render.page_url(page), "hidden": render.hidden_reason(page)}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["guide_staff"] = self.staff
        context["guide_has_principles"] = bool(self.visible("principle"))
        context["guide_has_glossary"] = bool(self.visible("term"))
        return context


class GuideIndexView(GuideMixin, TemplateView):
    template_name = "evennia_guides/guide_index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        categories = {}
        staff_pages = []
        for page in self.visible("guide"):
            if page.audience == "staff":
                staff_pages.append(self.entry(page))
            else:
                categories.setdefault(page.category, []).append(self.entry(page))
        context["categories"] = sorted(categories.items(), key=lambda item: item[0].lower())
        context["staff_pages"] = staff_pages
        return context


class GuidePageView(GuideMixin, TemplateView):
    template_name = "evennia_guides/guide_page.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        page = pages.get_page(self.kwargs["key"])
        if (
            page is None
            or page.key != self.kwargs["key"]
            or not checks.can_view(page, staff=self.staff)
        ):
            raise Http404("No such guide page.")
        body, toc = render.html(page, staff=self.staff)
        principles = [
            self.entry(found)
            for key in page.principles
            if (found := pages.get_page(key)) is not None
            and found.kind == "principle"
            and checks.can_view(found, staff=self.staff)
        ]
        footer = [
            self.entry(other) for other in self.visible() if other.footer and other.key != page.key
        ]
        context.update(
            page=page,
            body=mark_safe(body),
            toc=toc if len(toc) >= 3 else [],
            hidden=render.hidden_reason(page) if self.staff else "",
            principles=principles,
            footer_pages=footer,
            ask_url=ask_url(page, self.request),
            page_title=page.title,
        )
        return context


class GuidePrinciplesView(GuideMixin, TemplateView):
    template_name = "evennia_guides/guide_principles.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tagged = {}  # principle key -> [{page entry, insight}]
        illustrated = {}  # principle key -> [page entry]
        for page in self.visible():
            for key in page.principles:
                illustrated.setdefault(key, []).append(self.entry(page))
            for insight in page.document.insights():
                for key in insight.tags:
                    tagged.setdefault(key, []).append(
                        {"page": self.entry(page), "insight": insight}
                    )
        context["principles"] = [
            {
                **self.entry(page),
                "body": mark_safe(render.html(page, staff=self.staff)[0]),
                "insights": tagged.get(page.key, []),
                "pages": illustrated.get(page.key, []),
            }
            for page in self.visible("principle")
        ]
        return context


class GuideGlossaryView(GuideMixin, TemplateView):
    template_name = "evennia_guides/guide_glossary.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        terms = sorted(self.visible("term"), key=lambda page: page.title.lower())
        context["terms"] = [
            {
                **self.entry(page),
                "body": mark_safe(render.html(page, staff=self.staff)[0]),
            }
            for page in terms
        ]
        return context


def ask_url(page, request=None):
    """
    The "Ask about this page" link, prefilled with a title and the page's URL,
    or None when ``GUIDES_ASK_URL`` is off or doesn't reverse.
    """
    target = conf.get("GUIDES_ASK_URL")
    if not target:
        return None
    if "/" not in target:
        try:
            target = reverse(target, kwargs=conf.get("GUIDES_ASK_URL_KWARGS") or None)
        except NoReverseMatch:
            return None
    where = render.page_url(page) or page.key
    if request is not None:
        where = request.build_absolute_uri(where)
    query = urlencode(
        {
            "title": f"Guide question: {page.title}",
            "description": f"About the guide page {page.title} ({where}):\n\n",
        }
    )
    return f"{target}{'&' if '?' in target else '?'}{query}"
