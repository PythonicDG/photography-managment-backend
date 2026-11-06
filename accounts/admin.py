from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import SharedQuote, Studio, User

admin.site.site_header = 'Lens Ledger Administration'
admin.site.site_title = 'Lens Ledger Admin'
admin.site.index_title = 'Studio management'


class StudioInline(admin.StackedInline):
    model = Studio
    extra = 0
    can_delete = False
    exclude = ('logo',)


@admin.register(User)
class AccountAdmin(UserAdmin):
    model = User
    list_display = ('email', 'full_name', 'phone', 'is_active', 'is_staff', 'date_joined')
    list_filter = ('is_active', 'is_staff', 'is_superuser', 'date_joined')
    search_fields = ('email', 'full_name', 'phone')
    ordering = ('email',)
    readonly_fields = ('last_login', 'date_joined')
    filter_horizontal = ('groups', 'user_permissions')
    inlines = (StudioInline,)
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Account', {'fields': ('full_name', 'phone', 'is_active')}),
        ('Permissions', {'fields': ('is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'full_name', 'phone', 'password1', 'password2', 'is_active', 'is_staff'),
        }),
    )


@admin.register(Studio)
class StudioAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'city', 'state', 'business_type', 'gstin', 'trial_started_at')
    list_filter = ('state', 'business_type')
    search_fields = ('name', 'owner__email', 'owner__full_name', 'city', 'gstin')
    list_select_related = ('owner',)
    autocomplete_fields = ('owner',)
    exclude = ('logo',)


@admin.register(SharedQuote)
class SharedQuoteAdmin(admin.ModelAdmin):
    list_display = ('id', 'studio', 'local_id', 'version', 'status', 'updated_at')
    list_filter = ('status', 'updated_at')
    search_fields = ('local_id', 'root_local_id', 'studio__name', 'studio__owner__email')
    list_select_related = ('studio',)
    readonly_fields = ('id', 'updated_at', 'snapshot')
    date_hierarchy = 'updated_at'
    ordering = ('-updated_at',)
