import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import Studio, User

from .models import AccessState, Payment, Plan, Subscription
from .services import add_period, price_breakdown, start_trial

KEY_SECRET = 'test_secret'
WEBHOOK_SECRET = 'whsec_test'
PLATFORM_EMPTY = {key: [] for key in ('services', 'packages', 'clients', 'enquiries', 'quotes', 'team', 'bookings', 'payments', 'teamPayments', 'assists')}


def sign(message, secret=KEY_SECRET):
    return hmac.new(secret.encode(), message.encode() if isinstance(message, str) else message, hashlib.sha256).hexdigest()


def fake_order(order_id='order_TEST1'):
    return mock.Mock(ok=True, status_code=200, json=lambda: {'id': order_id, 'status': 'created'})


@override_settings(
    RAZORPAY_KEY_ID='rzp_test_key', RAZORPAY_KEY_SECRET=KEY_SECRET, RAZORPAY_WEBHOOK_SECRET=WEBHOOK_SECRET,
    BILLING_TRIAL_DAYS=15, BILLING_GRACE_DAYS=3, BILLING_GST_PERCENT=18,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
class BillingFlowTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user(email='owner@example.com', password='Testpass123!', full_name='Asha Rao', phone='9822041567', is_active=True)
        self.studio = Studio.objects.create(owner=self.owner, name='Lenscraft', trial_started_at=timezone.now())
        self.subscription = start_trial(self.studio)
        self.client.force_authenticate(self.owner)
        self.plan = Plan.objects.get(slug='studio')  # Seeded by the data migration.

    def expire_trial(self):
        Subscription.objects.filter(pk=self.subscription.pk).update(trial_ends_at=timezone.now() - timedelta(minutes=1))

    def checkout(self, plan='studio', cycle='monthly', order_id='order_TEST1'):
        with mock.patch('billing.razorpay_client.requests.post', return_value=fake_order(order_id)) as post:
            response = self.client.post(reverse('billing-checkout'), {'plan': plan, 'billing_cycle': cycle}, format='json')
        return response, post

    def verify(self, order_id='order_TEST1', payment_id='pay_TEST1', signature=None):
        return self.client.post(reverse('billing-verify'), {
            'razorpay_order_id': order_id, 'razorpay_payment_id': payment_id,
            'razorpay_signature': signature or sign(f'{order_id}|{payment_id}'),
        }, format='json')

    def webhook(self, event, order_id='order_TEST1', payment_id='pay_TEST1', amount=None, secret=WEBHOOK_SECRET):
        body = json.dumps({'event': event, 'payload': {'payment': {'entity': {
            'id': payment_id, 'order_id': order_id, 'amount': amount, 'error_description': 'Card declined'}}}}).encode()
        return self.client.generic('POST', reverse('billing-razorpay-webhook'), body, content_type='application/json',
                                   HTTP_X_RAZORPAY_SIGNATURE=sign(body, secret))

    # --- Trial and access -----------------------------------------------------------------

    def test_trial_lasts_configured_days_and_reports_state(self):
        days = (self.subscription.trial_ends_at - self.studio.trial_started_at).days
        self.assertEqual(days, 15)
        data = self.client.get(reverse('billing-subscription')).data
        self.assertEqual(data['state'], 'trialing')
        self.assertTrue(data['has_access'])
        self.assertEqual(data['days_left'], 15)

    def test_expired_trial_is_read_only(self):
        self.assertEqual(self.client.put(reverse('platform'), PLATFORM_EMPTY, format='json').status_code, 200)
        self.expire_trial()
        blocked = self.client.put(reverse('platform'), PLATFORM_EMPTY, format='json')
        self.assertEqual(blocked.status_code, 402)
        self.assertEqual(blocked.data['code'], 'subscription_required')
        self.assertEqual(blocked.data['state'], 'trial_expired')
        self.assertEqual(self.client.get(reverse('platform')).status_code, 200)  # Reads still work.
        self.assertEqual(self.client.get(reverse('billing-subscription')).data['state'], 'trial_expired')

    def test_suspended_account_is_read_only(self):
        Subscription.objects.filter(pk=self.subscription.pk).update(status=Subscription.Status.SUSPENDED)
        self.assertEqual(self.client.put(reverse('platform'), PLATFORM_EMPTY, format='json').status_code, 402)
        response, _ = self.checkout()
        self.assertEqual(response.status_code, 403)

    # --- Plans ----------------------------------------------------------------------------

    def test_plan_list_is_public_and_hides_inactive_plans(self):
        Plan.objects.filter(slug='collective').update(is_active=False)
        self.client.force_authenticate(None)
        data = self.client.get(reverse('billing-plans')).data
        self.assertEqual(data['trial_days'], 15)
        self.assertEqual([p['slug'] for p in data['plans']], ['solo', 'studio'])
        self.assertIn('Everything in Solo', data['plans'][1]['features'])
        response, post = self.checkout(plan='collective')
        self.assertEqual(response.status_code, 401)
        post.assert_not_called()

    def test_inactive_plan_and_unoffered_cycle_cannot_be_bought(self):
        Plan.objects.filter(slug='collective').update(is_active=False)
        response, post = self.checkout(plan='collective')
        self.assertEqual(response.status_code, 400)
        post.assert_not_called()
        Plan.objects.filter(slug='studio').update(price_yearly=None)
        response, post = self.checkout(cycle='yearly')
        self.assertEqual(response.status_code, 400)
        post.assert_not_called()

    def test_price_includes_gst_in_paise(self):
        self.assertEqual(price_breakdown(self.plan, 'monthly'), (249900, 44982, 294882))

    # --- Checkout and activation ------------------------------------------------------------

    def test_checkout_creates_razorpay_order_and_pending_payment(self):
        response, post = self.checkout()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['order_id'], 'order_TEST1')
        self.assertEqual(response.data['key_id'], 'rzp_test_key')
        self.assertEqual(response.data['amount'], 294882)
        self.assertNotIn(KEY_SECRET, json.dumps(response.data))
        sent = post.call_args.kwargs
        self.assertEqual(sent['json']['amount'], 294882)
        self.assertEqual(sent['auth'], ('rzp_test_key', KEY_SECRET))
        payment = Payment.objects.get()
        self.assertEqual(payment.status, Payment.Status.CREATED)
        self.assertEqual(payment.plan_name, 'Studio')

    @override_settings(RAZORPAY_KEY_ID='', RAZORPAY_KEY_SECRET='')
    def test_checkout_without_keys_reports_503(self):
        self.assertEqual(self.checkout()[0].status_code, 503)

    def test_paying_during_trial_starts_after_trial(self):
        self.checkout()
        response = self.verify()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['state'], 'active')
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, Subscription.Status.ACTIVE)
        self.assertEqual(self.subscription.current_period_start, self.subscription.trial_ends_at)
        self.assertEqual(self.subscription.current_period_end, add_period(self.subscription.trial_ends_at, 'monthly'))

    def test_paying_after_expiry_restores_write_access(self):
        self.expire_trial()
        self.checkout()
        self.assertEqual(self.verify().status_code, 200)
        self.assertEqual(self.client.put(reverse('platform'), PLATFORM_EMPTY, format='json').status_code, 200)

    def test_bad_signature_is_rejected(self):
        self.checkout()
        self.assertEqual(self.verify(signature='0' * 64).status_code, 400)
        self.assertEqual(Payment.objects.get().status, Payment.Status.CREATED)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, Subscription.Status.TRIALING)

    def test_cannot_verify_another_studios_order(self):
        self.checkout()
        other = User.objects.create_user(email='other@example.com', password='Testpass123!', full_name='Other', phone='9822041568', is_active=True)
        Studio.objects.create(owner=other, name='Other', trial_started_at=timezone.now())
        self.client.force_authenticate(other)
        self.assertEqual(self.verify().status_code, 404)

    def test_browser_and_webhook_activate_only_once(self):
        self.expire_trial()
        self.checkout()
        self.assertEqual(self.verify().status_code, 200)
        self.subscription.refresh_from_db()
        end = self.subscription.current_period_end
        self.assertEqual(self.webhook('payment.captured', amount=294882).status_code, 200)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.current_period_end, end)

    def test_webhook_alone_activates_payment(self):
        self.expire_trial()
        self.checkout()
        self.assertEqual(self.webhook('payment.captured', amount=294882).data['status'], 'ok')
        self.assertEqual(Payment.objects.get().status, Payment.Status.PAID)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.access_state(), AccessState.ACTIVE)

    def test_webhook_rejects_bad_signature_and_wrong_amount(self):
        self.checkout()
        self.assertEqual(self.webhook('payment.captured', amount=294882, secret='wrong').status_code, 400)
        self.assertEqual(self.webhook('payment.captured', amount=100).data['status'], 'rejected')
        self.assertEqual(Payment.objects.get().status, Payment.Status.CREATED)

    def test_failed_attempt_is_recorded_and_retry_can_still_succeed(self):
        self.checkout()
        self.webhook('payment.failed', payment_id='pay_FAIL')
        payment = Payment.objects.get()
        self.assertEqual(payment.status, Payment.Status.FAILED)
        self.assertEqual(payment.failure_reason, 'Card declined')
        self.assertEqual(self.verify(payment_id='pay_OK').status_code, 200)
        self.assertEqual(Payment.objects.get().status, Payment.Status.PAID)
        history = self.client.get(reverse('billing-payments')).data
        self.assertEqual(history[0]['status'], 'paid')

    def test_early_renewal_of_same_plan_stacks_and_switch_starts_now(self):
        self.expire_trial()
        self.checkout(order_id='order_A')
        self.verify(order_id='order_A', payment_id='pay_A')
        self.subscription.refresh_from_db()
        first_end = self.subscription.current_period_end
        self.checkout(order_id='order_B')
        self.verify(order_id='order_B', payment_id='pay_B')
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.current_period_start, first_end)
        self.checkout(plan='solo', cycle='yearly', order_id='order_C')
        self.verify(order_id='order_C', payment_id='pay_C')
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan.slug, 'solo')
        self.assertLess(self.subscription.current_period_start, first_end)

    def test_grace_period_then_expiry(self):
        now = timezone.now()
        Subscription.objects.filter(pk=self.subscription.pk).update(
            status=Subscription.Status.ACTIVE, plan=self.plan, billing_cycle='monthly',
            current_period_start=now - timedelta(days=31), current_period_end=now - timedelta(days=1))
        self.assertEqual(self.client.put(reverse('platform'), PLATFORM_EMPTY, format='json').status_code, 200)
        Subscription.objects.filter(pk=self.subscription.pk).update(current_period_end=now - timedelta(days=4))
        self.assertEqual(self.client.put(reverse('platform'), PLATFORM_EMPTY, format='json').data['state'], 'expired')

    def test_plan_with_payments_cannot_be_deleted(self):
        from django.db.models import ProtectedError
        self.checkout()
        with self.assertRaises(ProtectedError):
            self.plan.delete()

    # --- Reminders --------------------------------------------------------------------------

    def test_reminders_are_sent_once(self):
        Subscription.objects.filter(pk=self.subscription.pk).update(trial_ends_at=timezone.now() + timedelta(days=2))
        call_command('send_billing_reminders', stdout=StringIO())
        call_command('send_billing_reminders', stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('trial ends in 2 days', mail.outbox[0].subject)
        self.assertIn('/app/settings?tab=subscription', mail.outbox[0].body)


class PeriodMathTests(TestCase):
    def test_month_end_is_clamped(self):
        start = datetime(2026, 1, 31, 10, tzinfo=dt_timezone.utc)
        self.assertEqual(add_period(start, 'monthly'), datetime(2026, 2, 28, 10, tzinfo=dt_timezone.utc))
        self.assertEqual(add_period(datetime(2028, 2, 29, tzinfo=dt_timezone.utc), 'yearly'), datetime(2029, 2, 28, tzinfo=dt_timezone.utc))
        self.assertEqual(add_period(datetime(2026, 12, 15, tzinfo=dt_timezone.utc), 'monthly'), datetime(2027, 1, 15, tzinfo=dt_timezone.utc))
