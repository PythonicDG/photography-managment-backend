"""Business rules for trials, checkout and activating paid periods.

Views and the webhook call into here so the rules live in one place and every path is idempotent.
"""
import calendar
import logging
import uuid
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import razorpay_client
from .models import BillingCycle, Payment, Plan, Subscription

logger = logging.getLogger(__name__)


class BillingError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# --- Trial -------------------------------------------------------------------------------

def start_trial(studio):
    """Create the studio's subscription in the trial state. Safe to call repeatedly."""
    if studio.trial_started_at is None:
        raise ValueError('studio.trial_started_at must be set before the trial subscription is created')
    subscription, _ = Subscription.objects.get_or_create(
        studio=studio,
        defaults={'trial_ends_at': studio.trial_started_at + timedelta(days=settings.BILLING_TRIAL_DAYS)},
    )
    return subscription


def get_subscription(studio):
    """The studio's subscription, or None if the trial was never started."""
    subscription = Subscription.objects.select_related('plan').filter(studio=studio).first()
    if subscription is None and studio.trial_started_at is not None:
        # Studios that started a trial before billing existed (the data migration covers these, this is a safety net).
        subscription = start_trial(studio)
    return subscription


# --- Pricing -----------------------------------------------------------------------------

def price_breakdown(plan, cycle):
    """(base, gst, total) in paise for `plan` on `cycle`."""
    rupees = plan.price_for(cycle)
    if rupees is None:
        raise BillingError(f'{plan.name} is not available with {cycle} billing.')
    base = rupees * 100
    gst = int((Decimal(base) * Decimal(settings.BILLING_GST_PERCENT) / 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    return base, gst, base + gst


def add_period(start, cycle):
    """`start` plus one calendar month or year, clamping the day (31 Jan + 1 month = 28/29 Feb)."""
    months = 1 if cycle == BillingCycle.MONTHLY else 12
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def next_period_start(subscription, plan, cycle, now):
    """Where a newly paid period begins.

    - Renewing the same plan early stacks on the current period, so no paid days are lost.
    - Paying during the trial starts the plan when the trial ends, so no trial days are lost.
    - Anything else (first payment after expiry, or switching plan) starts now.
    """
    paid_until = subscription.current_period_end
    if (subscription.status == Subscription.Status.ACTIVE and paid_until and paid_until > now
            and subscription.plan_id == plan.pk and subscription.billing_cycle == cycle):
        return paid_until
    if subscription.status == Subscription.Status.TRIALING and subscription.trial_ends_at > now:
        return subscription.trial_ends_at
    return now


# --- Checkout ----------------------------------------------------------------------------

def create_checkout(studio, plan, cycle):
    """Create a Razorpay order and the matching pending Payment. Returns the Payment."""
    subscription = get_subscription(studio)
    if subscription is None:
        raise BillingError('Start your free trial before choosing a plan.')
    if subscription.status == Subscription.Status.SUSPENDED:
        raise BillingError('This account is suspended. Please contact support.', 403)
    if not plan.is_active:
        raise BillingError('This plan is no longer available.')
    base, gst, total = price_breakdown(plan, cycle)
    receipt = f'ff_{uuid.uuid4().hex[:24]}'
    order = razorpay_client.create_order(total, receipt, {
        'studio_id': str(studio.pk),
        'plan': plan.slug,
        'billing_cycle': cycle,
    })
    return Payment.objects.create(
        studio=studio,
        studio_name=studio.name,
        customer_email=studio.owner.email,
        plan=plan,
        plan_name=plan.name,
        billing_cycle=cycle,
        base_amount=base,
        gst_amount=gst,
        total_amount=total,
        currency=settings.BILLING_CURRENCY,
        receipt=receipt,
        razorpay_order_id=order['id'],
    )


def mark_paid(order_id, payment_id, amount=None):
    """Record a successful payment and extend the subscription. Idempotent: the browser callback and
    the webhook both call this, in either order, and only the first one changes anything."""
    now = timezone.now()
    with transaction.atomic():
        payment = Payment.objects.select_for_update().select_related('plan').filter(razorpay_order_id=order_id).first()
        if payment is None:
            raise BillingError('Unknown order.', 404)
        if payment.status == Payment.Status.PAID:
            return payment
        if amount is not None and int(amount) != payment.total_amount:
            logger.error('Razorpay amount mismatch on %s: expected %s, got %s', order_id, payment.total_amount, amount)
            raise BillingError('Payment amount does not match the order.', 409)
        if payment.studio_id is None:
            raise BillingError('The studio for this payment no longer exists.', 409)

        subscription = Subscription.objects.select_for_update().get(studio_id=payment.studio_id)
        start = next_period_start(subscription, payment.plan, payment.billing_cycle, now)
        end = add_period(start, payment.billing_cycle)

        payment.status = Payment.Status.PAID
        payment.razorpay_payment_id = payment_id
        payment.failure_reason = ''
        payment.paid_at = now
        payment.period_start, payment.period_end = start, end
        payment.save()

        subscription.plan = payment.plan
        subscription.billing_cycle = payment.billing_cycle
        subscription.status = Subscription.Status.ACTIVE
        subscription.current_period_start, subscription.current_period_end = start, end
        subscription.last_reminder = ''
        subscription.save()
    logger.info('Payment %s activated %s until %s', payment.receipt, payment.studio_name, end.isoformat())
    return payment


def mark_failed(order_id, payment_id, reason):
    """Note a failed attempt. A later successful attempt on the same order still activates it."""
    Payment.objects.filter(razorpay_order_id=order_id, status=Payment.Status.CREATED).update(
        status=Payment.Status.FAILED,
        razorpay_payment_id=None,
        failure_reason=(reason or 'Payment failed')[:255],
    )
    logger.info('Payment attempt %s failed on order %s: %s', payment_id, order_id, reason)


def active_plans():
    return Plan.objects.filter(is_active=True).prefetch_related('features')
