from django.contrib import admin

from .models import Package, Service


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'studio', 'category', 'price', 'active')
    list_filter = ('active', 'category')
    list_editable = ('active',)
    search_fields = ('name', 'description', 'studio__name')
    list_select_related = ('studio',)
    autocomplete_fields = ('studio',)


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ('name', 'studio', 'category', 'price', 'active')
    list_filter = ('active', 'category')
    list_editable = ('active',)
    search_fields = ('name', 'description', 'studio__name')
    list_select_related = ('studio',)
    autocomplete_fields = ('studio',)
    filter_horizontal = ('services',)
