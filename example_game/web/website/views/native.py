"""Game-level refinements to Evennia's native website list views."""

from django.conf import settings
from django.http import Http404, HttpResponse
from django.utils.text import slugify
from django.views.generic import ListView
from evennia.web.website.views.channels import ChannelMixin
from evennia.web.website.views.characters import CharacterListView, CharacterManageView
from evennia.web.website.views.help import HelpDetailView, HelpListView

from web.website.permissions import is_staff_user

PLAYER_CATEGORY_ORDER = (
    "General",
    "Character",
    "Communication",
    "Social",
    "Roleplaying",
    "Scenes",
    "Storytelling",
    "Events",
    "Lore",
    "Requests",
    "Travel",
    "Sandbox",
)
STAFF_CATEGORY_ORDER = ("Building", "Staff", "Admin", "System")
STAFF_ONLY_HELP_CATEGORIES = {category.casefold() for category in STAFF_CATEGORY_ORDER}
CATEGORY_LABELS = {
    category.casefold(): category for category in PLAYER_CATEGORY_ORDER + STAFF_CATEGORY_ORDER
}
CATEGORY_LABELS["comms"] = "Communication"


def _raw_category(entry):
    """Return the unmodified category used by the stock detail URL."""
    category = (
        getattr(entry, "help_category", None)
        or getattr(entry, "db_help_category", None)
        or settings.DEFAULT_HELP_CATEGORY
    )
    return str(category).strip()


def _display_key(entry):
    """Preserve command spelling instead of the stock lowercased sort key."""
    return (
        getattr(entry, "auto_help_display_key", None)
        or getattr(entry, "key", None)
        or getattr(entry, "db_key", None)
        or "unknown_topic"
    )


def _help_text(entry):
    """Read the searchable body from the native DB, file, or command sources."""
    return (
        getattr(entry, "db_entrytext", None)
        or getattr(entry, "entrytext", None)
        or getattr(entry, "__doc__", None)
        or ""
    )


def _ordered_categories(is_staff):
    labels = list(PLAYER_CATEGORY_ORDER)
    if is_staff:
        labels.extend(STAFF_CATEGORY_ORDER)
    return {label.casefold(): index for index, label in enumerate(labels)}


def _display_category(raw_category):
    """Return one canonical label for known and aliased help categories."""
    return CATEGORY_LABELS.get(raw_category.casefold(), raw_category)


def _prepare_help_entries(entries, request, search=""):
    """Filter and annotate native help objects without changing their URL data."""
    staff = is_staff_user(request)
    query = search.casefold().strip()
    order = _ordered_categories(staff)
    prepared = []

    for entry in entries:
        raw_category = _raw_category(entry)
        if raw_category.casefold() in STAFF_ONLY_HELP_CATEGORIES and not staff:
            continue

        display_category = _display_category(raw_category)
        display_key = _display_key(entry)
        if query:
            haystack = " ".join(
                (raw_category, display_category, str(display_key), str(_help_text(entry)))
            ).casefold()
            if query not in haystack:
                continue

        # Display-only attributes leave help_category/key untouched, so native
        # detail links retain their original category and topic.
        entry.sandbox_help_category = display_category
        entry.sandbox_help_key = display_key
        entry.sandbox_help_anchor = slugify(display_category)
        prepared.append(entry)

    def sort_key(entry):
        label = entry.sandbox_help_category
        return (
            order.get(label.casefold(), len(order)),
            label.casefold() if label.casefold() not in order else "",
            str(entry.sandbox_help_key).casefold(),
        )

    return sorted(prepared, key=sort_key)


class _SandboxHelpMixin:
    """Apply the same fail-closed Builder gate to list and detail access."""

    search_enabled = False

    def get_queryset(self):
        entries = super().get_queryset()
        search = self.request.GET.get("q", "") if self.search_enabled else ""
        return _prepare_help_entries(entries, self.request, search=search)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_web_staff"] = is_staff_user(self.request)
        if self.search_enabled:
            context["q"] = self.request.GET.get("q", "").strip()
        return context


class SandboxHelpListView(_SandboxHelpMixin, HelpListView):
    """Native help index with a search field and audience-aware categories."""

    search_enabled = True
    template_name = "website/help_list.html"


class SandboxHelpDetailView(_SandboxHelpMixin, HelpDetailView):
    """Hide restricted help details as well as their index entries."""

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if isinstance(obj, HttpResponse):
            raise Http404("Help topic not found")
        return obj


class SandboxChannelListView(ChannelMixin, ListView):
    """Native channel list without the internal channel or duplicate sidebar."""

    page_title = "Channels"
    paginate_by = 100
    template_name = "website/channel_list.html"

    def get_queryset(self):
        channels = super().get_queryset()
        mudinfo_settings = getattr(settings, "CHANNEL_MUDINFO", {}) or {}
        mudinfo = mudinfo_settings.get("key", "MudInfo") or "MudInfo"
        return channels.exclude(db_key__iexact=mudinfo)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_web_staff"] = is_staff_user(self.request)
        return context


class SandboxCharacterListView(CharacterListView):
    """Native public character list using the game's open-canvas template."""

    template_name = "website/character_list.html"


class SandboxCharacterManageView(CharacterManageView):
    """Native account character-management list with explicit pagination."""

    template_name = "website/character_manage_list.html"
