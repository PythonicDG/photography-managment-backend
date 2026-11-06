from urllib.parse import parse_qs, urlparse

from unittest import mock

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from django.utils import timezone

from billing.services import start_trial

from .models import SharedQuote, Studio, User


def make_studio(owner, name='Lenscraft Studio'):
    """A studio inside its free trial, i.e. allowed to write."""
    studio = Studio.objects.create(owner=owner, name=name, trial_started_at=timezone.now())
    start_trial(studio)
    return studio


class SharedQuoteTests(APITestCase):
    def test_revisions_keep_sent_totals_and_original_link_opens_latest(self):
        owner = User.objects.create_user(email='revisions@example.com', password='Testpass123!', full_name='Owner', phone='9822041567', is_active=True)
        studio = make_studio(owner)
        self.client.force_authenticate(user=owner)
        original = {'number': 'FF-Q-0001', 'event': 'Wedding', 'client_name': 'Sneha', 'items': [{'name': 'Photos', 'price': 100000}], 'subtotal': 100000, 'discount': 0, 'gst': 0, 'total': 100000, 'advance': 0, 'terms': ''}
        first = self.client.post(reverse('shared-quotes'), {'local_id': 'quote-1', 'snapshot': original}, format='json')
        self.assertEqual(first.status_code, 201)
        public_url = reverse('public-quote', kwargs={'quote_id': first.data['id']})
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.post(public_url, {'status': 'Changes requested', 'feedback': 'Target ₹90,000'}, format='json').status_code, 200)
        self.client.force_authenticate(user=owner)
        statuses = self.client.get(reverse('shared-quotes')).data
        self.assertEqual(statuses[0]['feedback'], 'Target ₹90,000')
        revised = {**original, 'items': [{'name': 'Photos', 'price': 90000}], 'subtotal': 90000, 'total': 90000}
        second = self.client.post(reverse('shared-quotes'), {'local_id': 'quote-2', 'root_local_id': 'quote-1', 'snapshot': revised}, format='json')
        self.assertEqual(second.status_code, 201)
        self.assertEqual(str(second.data['id']), str(first.data['id']))
        self.assertEqual(second.data['version'], 2)
        self.assertEqual(SharedQuote.objects.get(studio=studio, local_id='quote-1').status, 'Superseded')
        self.assertEqual(SharedQuote.objects.get(studio=studio, local_id='quote-1').snapshot['total'], 100000)
        self.assertEqual(self.client.post(reverse('shared-quotes'), {'local_id': 'quote-1', 'snapshot': revised}, format='json').status_code, 409)
        self.client.force_authenticate(user=None)
        latest = self.client.get(public_url).data
        self.assertEqual(latest['version'], 2)
        self.assertEqual(latest['snapshot']['total'], 90000)
        self.assertEqual(self.client.post(public_url, {'status': 'Accepted'}, format='json').status_code, 200)
        self.assertEqual(SharedQuote.objects.get(studio=studio, local_id='quote-2').status, 'Accepted')

    def test_rejected_version_can_be_revised_without_changing_rejection(self):
        owner = User.objects.create_user(email='rejected@example.com', password='Testpass123!', full_name='Owner', phone='9822041567', is_active=True)
        make_studio(owner)
        self.client.force_authenticate(user=owner)
        snapshot = {'number': 'Q-1', 'event': 'Wedding', 'client_name': 'Sneha', 'items': [], 'subtotal': 100, 'total': 100}
        first = self.client.post(reverse('shared-quotes'), {'local_id': 'first', 'snapshot': snapshot}, format='json')
        url = reverse('public-quote', kwargs={'quote_id': first.data['id']})
        self.client.force_authenticate(user=None)
        self.client.post(url, {'status': 'Rejected'}, format='json')
        self.client.force_authenticate(user=owner)
        second = self.client.post(reverse('shared-quotes'), {'local_id': 'second', 'root_local_id': 'first', 'snapshot': {**snapshot, 'total': 80}}, format='json')
        self.assertEqual(second.status_code, 201)
        self.assertEqual(SharedQuote.objects.get(local_id='first').status, 'Rejected')
        self.assertEqual(self.client.get(url).data['snapshot']['total'], 80)

    def test_package_details_are_stored_and_validated(self):
        owner = User.objects.create_user(email='pkg@example.com', password='Testpass123!', full_name='Owner', phone='9822041567', is_active=True)
        make_studio(owner)
        self.client.force_authenticate(user=owner)
        details = {'name': 'Wedding Silver', 'category': 'Wedding', 'team': ['1 Candid Photographer'], 'deliverables': ['25 page album'], 'notes': 'Drone pilot: Rs. 5,000'}
        snapshot = {'number': 'FF-Q-0001', 'event': 'Wedding', 'client_name': 'Sneha', 'items': [{'name': 'Wedding Silver package', 'price': 50000}], 'subtotal': 50000, 'discount': 0, 'total': 50000, 'advance': 0, 'terms': '', 'package_details': details}
        created = self.client.post(reverse('shared-quotes'), {'local_id': 'pkg-1', 'snapshot': snapshot}, format='json')
        self.assertEqual(created.status_code, 201)
        public = self.client.get(reverse('public-quote', kwargs={'quote_id': created.data['id']}))
        self.assertEqual(public.data['snapshot']['package_details'], details)
        for bad in ('text', {**details, 'team': 'not a list'}, {**details, 'deliverables': [1]}, {**details, 'notes': 'x' * 2001}):
            rejected = self.client.post(reverse('shared-quotes'), {'local_id': 'pkg-bad', 'snapshot': {**snapshot, 'package_details': bad}}, format='json')
            self.assertEqual(rejected.status_code, 400)

    def test_client_decision_updates_shared_quote_once(self):
        owner = User.objects.create_user(email='owner@example.com', password='Testpass123!', full_name='Owner', phone='9822041567', is_active=True)
        studio = make_studio(owner)
        self.client.force_authenticate(user=owner)
        snapshot = {
            'number': 'FF-Q-0001', 'event': 'Wedding', 'client_name': 'Sneha',
            'date': '2026-12-12', 'location': 'Pune',
            'items': [{'name': 'Standard package', 'price': 95000}],
            'subtotal': 95000, 'discount': 0, 'gst': 18, 'total': 112100,
            'advance': 25000, 'terms': 'Advance confirms the booking.',
        }
        created = self.client.post(reverse('shared-quotes'), {'local_id': 'local-1', 'snapshot': snapshot}, format='json')
        self.assertEqual(created.status_code, 201)
        shared = SharedQuote.objects.get(studio=studio, local_id='local-1')
        self.assertEqual(str(shared.id), str(created.data['id']))
        self.client.force_authenticate(user=None)
        url = reverse('public-quote', kwargs={'quote_id': shared.id})
        self.assertEqual(self.client.get(url).data['snapshot']['client_name'], 'Sneha')
        accepted = self.client.post(url, {'status': 'Accepted'}, format='json')
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(self.client.post(url, {'status': 'Rejected'}, format='json').status_code, 409)
        self.client.force_authenticate(user=owner)
        statuses = self.client.get(reverse('shared-quotes')).data
        self.assertEqual(statuses[0]['status'], 'Accepted')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_invoice_pdf_can_be_emailed(self):
        owner = User.objects.create_user(email='billing@example.com', password='Testpass123!', full_name='Owner', phone='9822041567', is_active=True)
        make_studio(owner)
        self.client.force_authenticate(user=owner)
        pdf = SimpleUploadedFile('invoice.pdf', b'%PDF-1.4\n' + b'0' * 150, content_type='application/pdf')
        response = self.client.post(reverse('send-document'), {'recipient': 'client@example.com', 'kind': 'invoice', 'document': pdf}, format='multipart')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['client@example.com'])
        self.assertEqual(mail.outbox[0].attachments[0][0], 'invoice.pdf')


@override_settings(WHATSAPP_ACCESS_TOKEN='tok', WHATSAPP_PHONE_NUMBER_ID='123', WHATSAPP_QUOTE_TEMPLATE='quotation_document')
class WhatsAppQuotationTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user(email='wa@example.com', password='Testpass123!', full_name='Owner', phone='9822041567', is_active=True)
        make_studio(self.owner)
        self.client.force_authenticate(user=self.owner)

    def post(self, phone='98220 41567'):
        pdf = SimpleUploadedFile('q.pdf', b'%PDF-1.4\n' + b'0' * 150, content_type='application/pdf')
        return self.client.post(reverse('send-quotation-whatsapp'), {'phone': phone, 'client_name': 'Sneha', 'event': 'Wedding', 'number': 'FF-Q-0001', 'total': '₹1,00,000', 'document': pdf}, format='multipart')

    def test_pdf_is_uploaded_then_sent_with_template(self):
        calls = []

        def fake(method, url, **kwargs):
            calls.append((url, kwargs))
            body = {'id': 'media-1'} if url.endswith('/media') else {'messages': [{'id': 'wamid.1'}]}
            return mock.Mock(ok=True, json=lambda: body)

        with mock.patch('accounts.whatsapp.requests.request', side_effect=fake):
            response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['message_id'], 'wamid.1')
        self.assertTrue(calls[0][0].endswith('/123/media'))
        sent = calls[1][1]['json']
        self.assertEqual(sent['to'], '919822041567')
        self.assertEqual(sent['template']['name'], 'quotation_document')
        self.assertEqual(sent['template']['components'][0]['parameters'][0]['document']['id'], 'media-1')
        self.assertEqual([p['text'] for p in sent['template']['components'][1]['parameters']], ['Sneha', 'Lenscraft Studio', 'Wedding', 'FF-Q-0001', '₹1,00,000'])

    def test_invalid_phone_and_meta_errors(self):
        self.assertEqual(self.post(phone='123').status_code, 400)
        failure = mock.Mock(ok=False, json=lambda: {'error': {'message': 'Template not found'}})
        with mock.patch('accounts.whatsapp.requests.request', return_value=failure):
            response = self.post()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data['detail'], 'Template not found')

    @override_settings(WHATSAPP_ACCESS_TOKEN='')
    def test_unconfigured_server_reports_503(self):
        self.assertEqual(self.post().status_code, 503)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class OnboardingTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.account = {
            'full_name': 'Arjun Mehta',
            'email': 'arjun@example.com',
            'phone': '9822041567',
            'password': 'Strong!Photo2026',
        }

    def register_and_verify(self):
        registered = self.client.post(reverse('register'), self.account, format='json')
        self.assertEqual(registered.status_code, 201)
        self.assertNotIn('token', registered.data)
        user = User.objects.get(email=self.account['email'])
        self.assertFalse(user.is_active)
        self.assertFalse(Studio.objects.filter(owner=user).exists())
        self.assertEqual(len(mail.outbox), 1)
        blocked = self.client.post(reverse('login'), {'email': user.email, 'password': self.account['password']}, format='json')
        self.assertEqual(blocked.status_code, 400)
        link = mail.outbox[0].body.splitlines()[-1]
        token = parse_qs(urlparse(link).query)['token'][0]
        verified = self.client.get(reverse('verify-email'), {'token': token})
        self.assertEqual(verified.status_code, 302)
        self.assertIn('verification=success', verified['Location'])
        logged_in = self.client.post(reverse('login'), {'email': user.email, 'password': self.account['password']}, format='json')
        self.assertEqual(logged_in.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + logged_in.data['token'])
        return user

    def test_verification_setup_and_no_card_trial(self):
        user = self.register_and_verify()
        self.assertEqual(self.client.get(reverse('studio')).status_code, 404)
        self.assertEqual(self.client.post(reverse('start-trial'), {}, format='json').status_code, 400)
        setup = self.client.post(reverse('studio'), {
            'name': 'Lenscraft Studio', 'city': 'Pune', 'state': 'Maharashtra',
            'business_type': 'Wedding', 'gstin': '27AAPFL1234C1Z5',
        }, format='json')
        self.assertEqual(setup.status_code, 201)
        self.assertEqual(Studio.objects.get(owner=user).name, 'Lenscraft Studio')
        self.assertIsNone(user.studio.trial_started_at)
        trial = self.client.post(reverse('start-trial'), {}, format='json')
        self.assertEqual(trial.status_code, 200)
        self.assertIsNotNone(trial.data['trial_started_at'])
        self.assertEqual(self.client.post(reverse('start-trial'), {}, format='json').data['trial_started_at'], trial.data['trial_started_at'])

    def test_optional_setup_can_be_skipped_except_name(self):
        self.assertEqual(self.client.post(reverse('studio'), {'name': 'Test Studio'}, format='json').status_code, 401)
        self.register_and_verify()
        self.assertEqual(self.client.post(reverse('studio'), {}, format='json').status_code, 400)
        self.assertEqual(self.client.post(reverse('studio'), {'name': 'Test Studio'}, format='json').status_code, 201)
        self.assertEqual(self.client.post(reverse('start-trial'), {}, format='json').status_code, 200)

    def test_invalid_verification_and_gstin(self):
        registered = self.client.post(reverse('register'), self.account, format='json')
        self.assertEqual(registered.status_code, 201)
        invalid = self.client.get(reverse('verify-email'), {'token': 'invalid'})
        self.assertIn('verification=invalid', invalid['Location'])
        self.assertFalse(User.objects.get(email=self.account['email']).is_active)
        duplicate = self.client.post(reverse('register'), {**self.account, 'email': 'ARJUN@example.com'}, format='json')
        self.assertIn('email', duplicate.data)
        weak = self.client.post(reverse('register'), {**self.account, 'email': 'other@example.com', 'password': 'password'}, format='json')
        self.assertIn('password', weak.data)
        link = mail.outbox[0].body.splitlines()[-1]
        token = parse_qs(urlparse(link).query)['token'][0]
        self.client.get(reverse('verify-email'), {'token': token})
        login = self.client.post(reverse('login'), {'email': self.account['email'], 'password': self.account['password']}, format='json')
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + login.data['token'])
        invalid_gstin = self.client.post(reverse('studio'), {'name': 'Test Studio', 'gstin': 'bad'}, format='json')
        self.assertIn('gstin', invalid_gstin.data)


class PackageQuoteRecalculationTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email='calc@example.com', password='Testpass123!', full_name='Owner', phone='9822041567', is_active=True)
        make_studio(self.owner)
        self.client.force_authenticate(user=self.owner)

    def snapshot(self, **overrides):
        base = {
            'number': 'FF-Q-0001', 'event': 'Wedding', 'client_name': 'Sneha', 'items': [],
            # Deliberately wrong client-side amounts, plus leftover GST fields: the server must replace/drop them.
            'subtotal': 1, 'discount': 5000, 'total': 1, 'advance': 70000, 'gst_percent': 18, 'gst': 99, 'terms': '',
            'packages': [
                {'id': 'a', 'title': 'Silver', 'price': 50000, 'count_in_total': True, 'team': [{'qty': 2, 'role': 'Photographer'}], 'materials': ['Album'], 'gift': 'Frame'},
                {'id': 'b', 'title': 'Gold', 'price': 85000, 'count_in_total': False, 'team': [], 'materials': [], 'gift': ''},
                {'id': 'c', 'title': 'Video', 'price': 20000, 'count_in_total': True, 'team': [], 'materials': [], 'gift': ''},
            ],
        }
        return {**base, **overrides}

    def post(self, snapshot, local_id='q-1'):
        return self.client.post(reverse('shared-quotes'), {'local_id': local_id, 'snapshot': snapshot}, format='json')

    def test_amounts_are_recomputed_from_packages(self):
        self.assertEqual(self.post(self.snapshot()).status_code, 201)
        stored = SharedQuote.objects.get(local_id='q-1').snapshot
        # Silver + Video are counted (70000); Gold is only an option. Rs. 5000 off -> 65000.
        self.assertEqual((stored['subtotal'], stored['discount'], stored['total'], stored['balance']), (70000, 5000, 65000, -5000))
        self.assertEqual([i['name'] for i in stored['items']], ['Silver', 'Video'])
        self.assertNotIn('gst', stored)
        self.assertNotIn('gst_percent', stored)

    def test_validation(self):
        for bad in ({'discount': 80000}, {'discount': -1}, {'packages': []}, {'packages': [{'title': '', 'price': 1}]},
                    {'packages': [{'title': 'X', 'price': -5, 'count_in_total': True}]}):
            self.assertEqual(self.post(self.snapshot(**bad), local_id='bad').status_code, 400, bad)

    def test_nothing_counted_gives_zero_totals_and_resend_is_idempotent(self):
        packages = [{**p, 'count_in_total': False} for p in self.snapshot()['packages']]
        snap = self.snapshot(packages=packages, discount=0)
        self.assertEqual(self.post(snap).status_code, 201)
        self.assertEqual(SharedQuote.objects.get(local_id='q-1').snapshot['total'], 0)
        self.assertEqual(self.post(snap).status_code, 200)
