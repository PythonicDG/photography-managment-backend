from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class AccountAdmin(UserAdmin):
    model = User
    list_display = ('email', 'full_name', 'phone', 'is_active', 'is_staff')
    search_fields = ('email', 'full_name', 'phone')
    ordering = ('email',)
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Account', {'fields': ('full_name', 'phone', 'is_active')}),
        ('Permissions', {'fields': ('is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {'fields': ('email', 'full_name', 'phone', 'password1', 'password2', 'is_active', 'is_staff')}),
    )
