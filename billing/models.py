"""Subscription plans, each studio's subscription, and the payments that pay for it.

Money is stored in paise (integer) on payments so totals never suffer from float rounding.
Plan prices are whole rupees because that is how they are entered in the admin.
"""
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class BillingCycle(models.TextChoices):
    MONTHLY = 'monthly', 'Monthly'
    YEARLY = 'yearly', 'Yearly'


class Plan(models.Model):
    name = models.CharField(max_length=60)
    slug = models.SlugField(max_length=60, unique=True, help_text='Stable identifier used by the app, e.g. "studio".')
    tagline = models.CharField(max_length=150, blank=True)
    price_monthly = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Price per month in ₹, before GST. Leave empty to not offer monthly billing.',
    )
    price_yearly = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Price for the whole year in ₹, before GST. Leave empty to not offer yearly billing.',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Inactive plans are hidden and cannot be bought. Existing subscribers keep them until renewal.',
    )
    is_featured = models.BooleanField(default=False, help_text='Highlight this plan as the recommended choice.')
    sort_order = models.PositiveSmallIntegerField(default=0, help_text='Lower numbers are shown first.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('sort_order', 'name')

    def __str__(self):
        return self.name

    def clean(self):
        if not self.price_monthly and not self.price_yearly:
            raise ValidationError('Set a monthly price, a yearly price, or both.')

    def price_for(self, cycle):
        """Price in rupees for `cycle`, or None when that cycle is not offered."""
        price = self.price_monthly if cycle == BillingCycle.MONTHLY else self.price_yearly
        return price or None


class PlanFeature(models.Model):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='features')
    text = models.CharField(max_length=200)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ('sort_order', 'id')

    def __str__(self):
        return self.text


class AccessState(models.TextChoices):
    """What a subscription allows right now. Derived from dates, never stored."""
    TRIALING = 'trialing', 'Free trial'
    TRIAL_EXPIRED = 'trial_expired', 'Trial ended'
    ACTIVE = 'active', 'Active'
    GRACE = 'grace', 'Payment due (grace period)'
    EXPIRED = 'expired', 'Expired'
    SUSPENDED = 'suspended', 'Suspended'


FULL_ACCESS_STATES = {AccessState.TRIALING, AccessState.ACTIVE, AccessState.GRACE}


class Subscription(models.Model):
    class Status(models.TextChoices):
        TRIALING = 'trialing', 'Trialing'
        ACTIVE = 'active', 'Active (paid)'
        SUSPENDED = 'suspended', 'Suspended by admin'

    studio = models.OneToOneField('accounts.Studio', on_delete=models.CASCADE, related_name='subscription')
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, null=True, blank=True, related_name='subscriptions')
    billing_cycle = models.CharField(max_length=10, choices=BillingCycle.choices, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.TRIALING)
    trial_ends_at = models.DateTimeField()
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    # Last reminder email sent, e.g. "trial-3:20261121". Stops the daily job from repeating itself.
    last_reminder = models.CharField(max_length=64, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.studio} · {self.get_status_display()}'

    @staticmethod
    def grace_period():
        return timedelta(days=settings.BILLING_GRACE_DAYS)

    def access_state(self, now=None):
        now = now or timezone.now()
        if self.status == self.Status.SUSPENDED:
            return AccessState.SUSPENDED
        if self.status == self.Status.ACTIVE and self.current_period_end:
            if now < self.current_period_end:
                return AccessState.ACTIVE
            if now < self.current_period_end + self.grace_period():
                return AccessState.GRACE
            return AccessState.EXPIRED
        return AccessState.TRIALING if now < self.trial_ends_at else AccessState.TRIAL_EXPIRED

    def has_full_access(self, now=None):
        return self.access_state(now) in FULL_ACCESS_STATES

    def access_ends_at(self, now=None):
        """When full access stops if nothing is paid, or None if it already has."""
        state = self.access_state(now)
        if state == AccessState.TRIALING:
            return self.trial_ends_at
        if state == AccessState.ACTIVE:
            return self.current_period_end
        if state == AccessState.GRACE:
            return self.current_period_end + self.grace_period()
        return None


class Payment(models.Model):
    class Status(models.TextChoices):
        CREATED = 'created', 'Awaiting payment'
        PAID = 'paid', 'Paid'
        FAILED = 'failed', 'Failed'

    # Payments are financial records: they outlive a deleted studio and block deleting their plan.
    studio = models.ForeignKey('accounts.Studio', on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    studio_name = models.CharField(max_length=150)
    customer_email = models.EmailField()
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='payments')
    plan_name = models.CharField(max_length=60)
    billing_cycle = models.CharField(max_length=10, choices=BillingCycle.choices)
    base_amount = models.PositiveIntegerField(help_text='Paise, before GST.')
    gst_amount = models.PositiveIntegerField(help_text='Paise.')
    total_amount = models.PositiveIntegerField(help_text='Paise charged to the customer.')
    currency = models.CharField(max_length=3, default='INR')
    receipt = models.CharField(max_length=40, unique=True)
    razorpay_order_id = models.CharField(max_length=64, unique=True)
    razorpay_payment_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CREATED)
    failure_reason = models.CharField(max_length=255, blank=True)
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [models.Index(fields=['studio', 'status'])]

    def __str__(self):
        return f'{self.receipt} · {self.get_status_display()}'
