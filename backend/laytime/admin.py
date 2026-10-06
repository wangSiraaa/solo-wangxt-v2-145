from django.contrib import admin

from .models import CharterParty, Clause, Event, Settlement, Stoppage, Voyage


class ClauseInline(admin.TabularInline):
    model = Clause
    extra = 0


@admin.register(CharterParty)
class CharterPartyAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    inlines = [ClauseInline]


class EventInline(admin.TabularInline):
    model = Event
    extra = 0


class StoppageInline(admin.TabularInline):
    model = Stoppage
    extra = 0


@admin.register(Voyage)
class VoyageAdmin(admin.ModelAdmin):
    list_display = ("reference", "vessel_name", "port_name", "operation")
    inlines = [EventInline, StoppageInline]


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ("voyage", "version", "status", "total_amount", "currency")
    readonly_fields = ("report",)
