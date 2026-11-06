"""WhatsApp Business Cloud API (Meta) client used to send quotation PDFs to clients.

Flow: upload the PDF to /{phone_number_id}/media, then send an approved template message whose
header is that document. Templates are required because the client has not messaged the studio
first (free-form messages only work inside a 24-hour customer-service window).
"""
import re

import requests
from django.conf import settings

GRAPH_URL = 'https://graph.facebook.com'
TIMEOUT = 20


class WhatsAppError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def is_configured():
    return bool(settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID and settings.WHATSAPP_QUOTE_TEMPLATE)


def normalize_phone(raw):
    """Return the number in WhatsApp's international format (digits only, no +), or None if invalid."""
    digits = re.sub(r'\D', '', str(raw or ''))
    digits = digits.lstrip('0') if len(digits) == 11 and digits.startswith('0') else digits
    if len(digits) == 10:
        digits = settings.WHATSAPP_DEFAULT_COUNTRY_CODE + digits
    return digits if 11 <= len(digits) <= 15 else None


def clean_param(value, limit=60):
    """Template parameters cannot hold newlines, tabs or runs of 4+ spaces, and must not be empty."""
    text = re.sub(r'\s+', ' ', str(value or '')).strip()[:limit]
    return text or '-'


def _call(method, path, **kwargs):
    url = f'{GRAPH_URL}/{settings.WHATSAPP_API_VERSION}/{path}'
    headers = {'Authorization': f'Bearer {settings.WHATSAPP_ACCESS_TOKEN}'}
    try:
        response = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as error:
        raise WhatsAppError('Could not reach WhatsApp. Please try again.') from error
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok:
        detail = (body.get('error') or {}) if isinstance(body, dict) else {}
        raise WhatsAppError(detail.get('error_user_msg') or detail.get('message') or 'WhatsApp rejected the message.', 502)
    return body


def send_quotation(phone, pdf_bytes, filename, params):
    """Send `pdf_bytes` to `phone` using the configured quotation template.

    `params` are the body variables in the order {{1}}, {{2}}, ... of the template.
    Returns the WhatsApp message id.
    """
    if not is_configured():
        raise WhatsAppError('WhatsApp is not configured on the server.', 503)
    media = _call(
        'POST',
        f'{settings.WHATSAPP_PHONE_NUMBER_ID}/media',
        data={'messaging_product': 'whatsapp', 'type': 'application/pdf'},
        files={'file': (filename, pdf_bytes, 'application/pdf')},
    )
    media_id = media.get('id')
    if not media_id:
        raise WhatsAppError('WhatsApp did not accept the PDF.')
    result = _call(
        'POST',
        f'{settings.WHATSAPP_PHONE_NUMBER_ID}/messages',
        json={
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': phone,
            'type': 'template',
            'template': {
                'name': settings.WHATSAPP_QUOTE_TEMPLATE,
                'language': {'code': settings.WHATSAPP_TEMPLATE_LANGUAGE},
                'components': [
                    {'type': 'header', 'parameters': [{'type': 'document', 'document': {'id': media_id, 'filename': filename}}]},
                    {'type': 'body', 'parameters': [{'type': 'text', 'text': clean_param(p)} for p in params]},
                ],
            },
        },
    )
    messages = result.get('messages') or []
    return messages[0].get('id', '') if messages else ''
