from django.contrib import admin

from .models import Booking, TeamAssignment, TeamMember


class TeamAssignmentInline(admin.TabularInline):
    model = TeamAssignment
    extra = 0
    autocomplete_fields = ('member',)


@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display = ('name', 'role', 'phone', 'studio')
    list_filter = ('role',)
    search_fields = ('name', 'phone', 'studio__name')
    list_select_related = ('studio',)
    autocomplete_fields = ('studio',)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('event', 'client', 'studio', 'date', 'end_date', 'location')
    list_filter = ('date',)
    search_fields = ('event', 'location', 'client__name', 'studio__name')
    list_select_related = ('client', 'studio')
    autocomplete_fields = ('studio', 'client', 'quotation')
    date_hierarchy = 'date'
    inlines = (TeamAssignmentInline,)
