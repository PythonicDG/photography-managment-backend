"""Email trial-ending and renewal reminders. Run once a day (cron / Windows Task Scheduler):

    python manage.py send_billing_reminders

Each reminder is sent at most once per subscription and period, so running it more often is harmless.
"""
import logging
import math
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from billing.models import AccessState, Subscription

logger = logging.getLogger(__name__)

# Stop nagging accounts that lapsed a long time ago.
EXPIRED_REMINDER_WINDOW = timedelta(days=7)


def reminder_for(subscription, now):
    """(key, subject, body) for the reminder due now, or None."""
    state = subscription.access_state(now)
    brand = settings.BILLING_BRAND_NAME
    link = f'{settings.FRONTEND_URL}/app/settings?tab=subscription'

    if state == AccessState.TRIALING:
        days = math.ceil((subscription.trial_ends_at - now).total_seconds() / 86400)
        stamp = subscription.trial_ends_at.strftime('%Y%m%d')
        if days <= 1:
            return (f'trial-1:{stamp}', f'Your {brand} trial ends tomorrow',
                    f'Your free trial ends within a day. Choose a plan to keep adding quotations, bookings and payments:\n{link}')
        if days <= 3:
            return (f'trial-3:{stamp}', f'Your {brand} trial ends in {days} days',
                    f'Your free trial ends in {days} days. Choose a plan any time; paid time starts after your trial ends:\n{link}')
    elif state == AccessState.TRIAL_EXPIRED and now - subscription.trial_ends_at < EXPIRED_REMINDER_WINDOW:
        return (f'trial-ended:{subscription.trial_ends_at:%Y%m%d}', f'Your {brand} trial has ended',
                f'Your free trial has ended and your workspace is now read-only. Your data is safe. Choose a plan to continue:\n{link}')
    elif state == AccessState.ACTIVE:
        days = math.ceil((subscription.current_period_end - now).total_seconds() / 86400)
        if days <= 3:
            return (f'renew-3:{subscription.current_period_end:%Y%m%d}', f'Your {brand} plan renews in {days} day(s)',
                    f'Your {subscription.plan} plan is paid until {subscription.current_period_end:%d %b %Y}. Renew now to avoid interruption:\n{link}')
    elif state == AccessState.GRACE:
        return (f'grace:{subscription.current_period_end:%Y%m%d}', f'Your {brand} plan has expired',
                f'Your {subscription.plan} plan expired on {subscription.current_period_end:%d %b %Y}. You have '
                f'{settings.BILLING_GRACE_DAYS} days before your workspace turns read-only. Renew here:\n{link}')
    elif state == AccessState.EXPIRED and now - subscription.current_period_end < EXPIRED_REMINDER_WINDOW + subscription.grace_period():
        return (f'expired:{subscription.current_period_end:%Y%m%d}', f'Your {brand} workspace is read-only',
                f'Your plan has expired and your workspace is now read-only. Your data is safe. Renew to continue:\n{link}')
    return None


class Command(BaseCommand):
    help = 'Email trial-ending and renewal reminders (run daily).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='List reminders without sending them.')

    def handle(self, *args, dry_run=False, **options):
        now = timezone.now()
        sent = 0
        subscriptions = Subscription.objects.select_related('studio__owner', 'plan').exclude(status=Subscription.Status.SUSPENDED)
        for subscription in subscriptions.iterator():
            reminder = reminder_for(subscription, now)
            if reminder is None or reminder[0] == subscription.last_reminder:
                continue
            key, subject, body = reminder
            owner = subscription.studio.owner
            if dry_run:
                self.stdout.write(f'{owner.email}: {subject}')
                continue
            try:
                send_mail(subject, f'Hi {owner.full_name},\n\n{body}\n\n- {settings.BILLING_BRAND_NAME}', settings.DEFAULT_FROM_EMAIL, [owner.email])
            except Exception:  # One bad address must not stop the rest of the batch.
                logger.exception('Could not send billing reminder to %s', owner.email)
                continue
            subscription.last_reminder = key
            subscription.save(update_fields=['last_reminder', 'updated_at'])
            sent += 1
        self.stdout.write(self.style.SUCCESS(f'Sent {sent} reminder(s).'))
