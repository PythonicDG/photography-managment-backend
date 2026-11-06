"""Minimal Razorpay REST client: create orders and verify signatures.

Only the two calls this app needs are wrapped, using `requests` (already a dependency), so there is
no extra SDK to keep up to date. Docs: https://razorpay.com/docs/api/orders/
"""
import hashlib
import hmac
import logging

import requests
from django.conf import settings

API_BASE = 'https://api.razorpay.com/v1'
TIMEOUT = 15

logger = logging.getLogger(__name__)


class RazorpayError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def is_configured():
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def create_order(amount, receipt, notes):
    """Create an order for `amount` paise. Returns Razorpay's order object (its `id` starts with "order_")."""
    if not is_configured():
        raise RazorpayError('Online payments are not configured yet. Please contact support.', 503)
    try:
        response = requests.post(
            f'{API_BASE}/orders',
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
            json={'amount': amount, 'currency': settings.BILLING_CURRENCY, 'receipt': receipt, 'notes': notes},
            timeout=TIMEOUT,
        )
    except requests.RequestException as error:
        logger.warning('Razorpay order request failed: %s', error)
        raise RazorpayError('Could not reach the payment gateway. Please try again.') from error
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok or not body.get('id'):
        logger.error('Razorpay rejected order %s: HTTP %s %s', receipt, response.status_code, body)
        raise RazorpayError('The payment gateway could not start this payment. Please try again.')
    return body


def _signature_matches(secret, message, signature):
    if not secret or not isinstance(signature, str) or not signature:
        return False
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_payment_signature(order_id, payment_id, signature):
    """Checkout returns this signature after a successful payment; it proves the result came from Razorpay."""
    return _signature_matches(settings.RAZORPAY_KEY_SECRET, f'{order_id}|{payment_id}'.encode(), signature)


def verify_webhook_signature(body, signature):
    """Webhooks are signed with the webhook secret set in the Razorpay dashboard, over the raw request body."""
    return _signature_matches(settings.RAZORPAY_WEBHOOK_SECRET, body, signature)
