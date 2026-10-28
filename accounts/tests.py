from urllib.parse import parse_qs, urlparse

from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from .models import Studio, User


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
