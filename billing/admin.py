from datetime import timedelta

from django.contrib import admin, messages
from django.db.models import Count
from django.utils import timezone

from .models import Payment, Plan, PlanFeature, Subscription


def rupees(paise):
    return f'₹{paise / 100:,.2f}'


class PlanFeatureInline(admin.TabularInline):
    model = PlanFeature
    extra = 1
    fields = ('text', 'sort_order')


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'price_monthly', 'price_yearly', 'is_active', 'is_featured', 'sort_order', 'subscriber_count')
    list_editable = ('is_active', 'is_featured', 'sort_order')
    list_filter = ('is_active', 'is_featured')
    search_fields = ('name', 'slug', 'tagline')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('created_at', 'updated_at')
    inlines = (PlanFeatureInline,)
    actions = ('activate', 'deactivate')
    fieldsets = (
        (None, {'fields': ('name', 'slug', 'tagline')}),
        ('Pricing (₹, before GST)', {'fields': ('price_monthly', 'price_yearly')}),
        ('Visibility', {
            'fields': ('is_active', 'is_featured', 'sort_order'),
            'description': 'Deactivate a plan to stop selling it. A plan that has subscribers or payments '
                           'cannot be deleted; deactivate it instead.',
        }),
        ('Dates', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_subscribers=Count('subscriptions', distinct=True))

    @admin.display(description='Subscribers', ordering='_subscribers')
    def subscriber_count(self, plan):
        return plan._subscribers

    @admin.action(description='Activate selected plans')
    def activate(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} plan(s) activated.', messages.SUCCESS)

    @admin.action(description='Deactivate selected plans (hide from customers)')
    def deactivate(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} plan(s) deactivated.', messages.SUCCESS)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('studio', 'owner_email', 'plan', 'billing_cycle', 'access', 'trial_ends_at', 'current_period_end')
    list_filter = ('status', 'plan', 'billing_cycle')
    search_fields = ('studio__name', 'studio__owner__email')
    list_select_related = ('studio__owner', 'plan')
    autocomplete_fields = ('studio',)
    readonly_fields = ('access', 'last_reminder', 'created_at', 'updated_at')
    actions = ('extend_trial', 'add_free_month', 'suspend', 'unsuspend')
    fieldsets = (
        (None, {'fields': ('studio', 'access', 'status')}),
        ('Plan', {'fields': ('plan', 'billing_cycle', 'current_period_start', 'current_period_end')}),
        ('Trial', {'fields': ('trial_ends_at',)}),
        ('System', {'fields': ('last_reminder', 'created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    @admin.display(description='Owner', ordering='studio__owner__email')
    def owner_email(self, subscription):
        return subscription.studio.owner.email

    @admin.display(description='Access now')
    def access(self, subscription):
        return subscription.access_state().label if subscription.pk else '-'

    @admin.action(description='Extend trial by 7 days')
    def extend_trial(self, request, queryset):
        now = timezone.now()
        count = 0
        for subscription in queryset.filter(status=Subscription.Status.TRIALING):
            subscription.trial_ends_at = max(subscription.trial_ends_at, now) + timedelta(days=7)
            subscription.last_reminder = ''
            subscription.save(update_fields=['trial_ends_at', 'last_reminder', 'updated_at'])
            count += 1
        self.message_user(request, f'Extended {count} trial(s). Paid or suspended subscriptions were skipped.', messages.SUCCESS)

    @admin.action(description='Add a free month to the paid period')
    def add_free_month(self, request, queryset):
        now = timezone.now()
        count = 0
        for subscription in queryset.filter(status=Subscription.Status.ACTIVE, plan__isnull=False):
            start = max(subscription.current_period_end or now, now)
            subscription.current_period_end = start + timedelta(days=30)
            subscription.last_reminder = ''
            subscription.save(update_fields=['current_period_end', 'last_reminder', 'updated_at'])
            count += 1
        self.message_user(request, f'Added 30 days to {count} paid subscription(s). Trials were skipped.', messages.SUCCESS)

    @admin.action(description='Suspend (read-only access)')
    def suspend(self, request, queryset):
        updated = queryset.update(status=Subscription.Status.SUSPENDED)
        self.message_user(request, f'{updated} subscription(s) suspended.', messages.WARNING)

    @admin.action(description='Lift suspension')
    def unsuspend(self, request, queryset):
        count = 0
        for subscription in queryset.filter(status=Subscription.Status.SUSPENDED):
            subscription.status = Subscription.Status.ACTIVE if subscription.current_period_end else Subscription.Status.TRIALING
            subscription.save(update_fields=['status', 'updated_at'])
            count += 1
        self.message_user(request, f'{count} subscription(s) restored.', messages.SUCCESS)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('receipt', 'studio_name', 'customer_email', 'plan_name', 'billing_cycle', 'total', 'status', 'created_at', 'paid_at')
    list_filter = ('status', 'billing_cycle', 'plan')
    search_fields = ('receipt', 'studio_name', 'customer_email', 'razorpay_order_id', 'razorpay_payment_id')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    @admin.display(description='Total', ordering='total_amount')
    def total(self, payment):
        return rupees(payment.total_amount)

    # Payments are a ledger written only by Razorpay callbacks: view-only in the admin.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
