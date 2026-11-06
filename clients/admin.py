from django.contrib import admin

from .models import Client, Enquiry


class EnquiryInline(admin.TabularInline):
    model = Enquiry
    extra = 0
    fields = ('event', 'date', 'location', 'budget', 'status')
    show_change_link = True


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'studio', 'email', 'phone', 'city')
    list_filter = ('city',)
    search_fields = ('name', 'email', 'phone', 'studio__name')
    list_select_related = ('studio',)
    autocomplete_fields = ('studio',)
    inlines = (EnquiryInline,)


@admin.register(Enquiry)
class EnquiryAdmin(admin.ModelAdmin):
    list_display = ('event', 'client', 'studio', 'date', 'budget', 'source', 'follow_up', 'status')
    list_filter = ('status', 'source', 'date')
    search_fields = ('event', 'location', 'client__name', 'studio__name')
    list_select_related = ('client', 'studio')
    autocomplete_fields = ('studio', 'client')
    date_hierarchy = 'date'
