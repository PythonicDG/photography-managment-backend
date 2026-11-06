"""Seed the launch price list (edit it afterwards in Django admin) and give every studio that already
started a trial a subscription, so existing users keep the same trial end date."""
from datetime import timedelta

from django.conf import settings
from django.db import migrations

PLANS = [
    {
        'slug': 'solo', 'name': 'Solo', 'tagline': 'For freelance photographers', 'sort_order': 10,
        'price_monthly': 999, 'price_yearly': 799 * 12, 'is_featured': False,
        'features': ['1 user', 'Client records from quotations', 'Quotations & invoices with GST', '50 bookings / month', 'WhatsApp reminders'],
    },
    {
        'slug': 'studio', 'name': 'Studio', 'tagline': 'For growing wedding studios', 'sort_order': 20,
        'price_monthly': 2499, 'price_yearly': 1999 * 12, 'is_featured': True,
        'features': ['Up to 8 team members', 'Everything in Solo', 'Shoot calendar & crew assignment', 'Profit per project'],
    },
    {
        'slug': 'collective', 'name': 'Collective', 'tagline': 'For multi-city production houses', 'sort_order': 30,
        'price_monthly': 5999, 'price_yearly': 4799 * 12, 'is_featured': False,
        'features': ['Unlimited team', 'Everything in Studio', 'Multiple branches', 'Freelancer payouts', 'Custom roles & approvals', 'Priority onboarding'],
    },
]


def seed(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    PlanFeature = apps.get_model('billing', 'PlanFeature')
    Studio = apps.get_model('accounts', 'Studio')
    Subscription = apps.get_model('billing', 'Subscription')

    for data in PLANS:
        data = dict(data)
        features = data.pop('features')
        plan, created = Plan.objects.get_or_create(slug=data['slug'], defaults=data)
        if created:
            PlanFeature.objects.bulk_create(PlanFeature(plan=plan, text=text, sort_order=i) for i, text in enumerate(features))

    trial = timedelta(days=settings.BILLING_TRIAL_DAYS)
    for studio in Studio.objects.filter(trial_started_at__isnull=False, subscription__isnull=True):
        Subscription.objects.create(studio=studio, trial_ends_at=studio.trial_started_at + trial)


class Migration(migrations.Migration):
    dependencies = [
        ('billing', '0001_initial'),
        ('accounts', '0007_studio_platform_settings_studio_platform_synced_at'),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
