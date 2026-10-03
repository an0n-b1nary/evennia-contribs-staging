# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django admin for evennia_rp_chargen."""

from django.contrib import admin

from evennia_rp_chargen.models import (
    AbilityDefinition,
    AbilityTransaction,
    CharacterAbility,
    CharacterBuild,
    TagDefinition,
)


@admin.register(CharacterBuild)
class CharacterBuildAdmin(admin.ModelAdmin):
    list_display = ("character_name", "status", "finalized_at", "reviewed_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("character_name",)
    readonly_fields = ("character", "created_at", "updated_at", "finalized_at", "reviewed_at")


class _KeyFrozenAdmin(admin.ModelAdmin):
    """Keys are referenced from data and never change once saved."""

    def get_queryset(self, request):
        return self.model.all_objects.all()

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        return [*fields, "key"] if obj is not None else fields


@admin.register(TagDefinition)
class TagDefinitionAdmin(_KeyFrozenAdmin):
    list_display = ("name", "key", "kind", "is_archived")
    list_filter = ("kind", "is_archived")
    search_fields = ("name", "key")


@admin.register(AbilityDefinition)
class AbilityDefinitionAdmin(_KeyFrozenAdmin):
    list_display = (
        "name",
        "key",
        "category",
        "is_flaw",
        "acquisition",
        "xp_cost",
        "budget_cost",
        "max_level",
        "tag_kind",
        "is_archived",
    )
    list_filter = ("category", "is_flaw", "acquisition", "is_archived")
    search_fields = ("name", "key")


@admin.register(CharacterAbility)
class CharacterAbilityAdmin(admin.ModelAdmin):
    list_display = ("character", "ability", "tag", "level", "equipped")
    list_filter = ("equipped", "ability")
    raw_id_fields = ("character",)


@admin.register(AbilityTransaction)
class AbilityTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "character_name",
        "kind",
        "ability_name",
        "level_from",
        "level_to",
        "allowance_amount",
        "xp_amount",
    )
    list_filter = ("kind",)
    search_fields = ("character_name", "ability_name")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
