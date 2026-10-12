"""Inspection only: protected state changes use the domain services."""

from django.contrib import admin

from . import models


class AuditAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


for model in (
    models.BuildProject,
    models.BuildSubmission,
    models.BuildReview,
    models.EnvironmentApproval,
    models.Property,
    models.RoomOwnership,
    models.BuildAudit,
    models.RegionBuildPolicy,
    models.Resident,
    models.GuestInvitation,
    models.RoomOverride,
):
    admin.site.register(model, AuditAdmin)
