from django.contrib import admin

from .models import (
    CharterParty,
    Clause,
    EventFragment,
    Settlement,
    SettlementLine,
    Voyage,
)


class ClauseInline(admin.TabularInline):
    model = Clause
    extra = 0


@admin.register(CharterParty)
class CharterPartyAdmin(admin.ModelAdmin):
    inlines = [ClauseInline]
    list_display = ["code", "name", "laytime_allowed_hours",
                    "demurrage_rate_per_day", "despatch_rate_per_day"]


class EventFragmentInline(admin.TabularInline):
    model = EventFragment
    extra = 0


@admin.register(Voyage)
class VoyageAdmin(admin.ModelAdmin):
    inlines = [EventFragmentInline]
    list_display = ["label", "vessel_name", "port", "charter_party"]


class SettlementLineInline(admin.TabularInline):
    model = SettlementLine
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    inlines = [SettlementLineInline]
    list_display = ["voyage", "version", "status", "laytime_used_hours",
                    "demurrage_amount", "despatch_amount", "created_at"]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
