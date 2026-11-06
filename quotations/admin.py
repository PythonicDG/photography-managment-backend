from django.contrib import admin

from .models import Quotation, QuotationPackage


class QuotationPackageInline(admin.StackedInline):
    model = QuotationPackage
    extra = 0
    autocomplete_fields = ('source',)


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = ('number', 'version', 'client', 'studio', 'event', 'date', 'total_display', 'advance', 'status', 'created_at')
    list_filter = ('status', 'date', 'created_at')
    search_fields = ('number', 'event', 'location', 'client__name', 'studio__name')
    list_select_related = ('client', 'studio')
    autocomplete_fields = ('studio', 'client', 'enquiry', 'package', 'root')
    readonly_fields = ('created_at', 'subtotal', 'total', 'balance')
    date_hierarchy = 'created_at'
    inlines = (QuotationPackageInline,)

    @admin.display(description='Total')
    def total_display(self, obj):
        return obj.total


@admin.register(QuotationPackage)
class QuotationPackageAdmin(admin.ModelAdmin):
    list_display = ('title', 'quotation', 'price', 'count_in_total')
    list_filter = ('count_in_total',)
    search_fields = ('title', 'quotation__number')
    list_select_related = ('quotation',)
    autocomplete_fields = ('quotation', 'source')
