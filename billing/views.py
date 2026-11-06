import json
import logging

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.models import Studio

from . import razorpay_client, services
from .models import Payment
from .serializers import CheckoutSerializer, PaymentSerializer, PlanSerializer, SubscriptionSerializer, VerifyPaymentSerializer

logger = logging.getLogger(__name__)


def studio_for(request):
    return Studio.objects.select_related('owner').filter(owner=request.user).first()


def error(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({'detail': message}, status=code)


class PlanListView(APIView):
    """Public price list for the pricing page and the in-app plan picker."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({
            'trial_days': settings.BILLING_TRIAL_DAYS,
            'gst_percent': settings.BILLING_GST_PERCENT,
            'currency': settings.BILLING_CURRENCY,
            'plans': PlanSerializer(services.active_plans(), many=True).data,
        })


class SubscriptionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        studio = studio_for(request)
        subscription = services.get_subscription(studio) if studio else None
        if subscription is None:
            return error('Start your free trial first.', status.HTTP_404_NOT_FOUND)
        return Response(SubscriptionSerializer(subscription).data)


class CheckoutView(APIView):
    """Step 1 of a payment: create a Razorpay order the browser opens in Razorpay Checkout."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'billing_checkout'

    def post(self, request):
        studio = studio_for(request)
        if studio is None:
            return error('Set up your studio first.')
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan, cycle = serializer.validated_data['plan'], serializer.validated_data['billing_cycle']
        try:
            payment = services.create_checkout(studio, plan, cycle)
        except services.BillingError as exc:
            return error(str(exc), exc.status)
        except razorpay_client.RazorpayError as exc:
            return error(str(exc), exc.status)
        return Response({
            'key_id': settings.RAZORPAY_KEY_ID,
            'order_id': payment.razorpay_order_id,
            'amount': payment.total_amount,
            'currency': payment.currency,
            'name': settings.BILLING_BRAND_NAME,
            'description': f'{plan.name} plan · {payment.get_billing_cycle_display()}',
            'prefill': {'name': studio.owner.full_name, 'email': studio.owner.email, 'contact': studio.owner.phone},
            'breakdown': {'base': payment.base_amount, 'gst': payment.gst_amount, 'total': payment.total_amount, 'gst_percent': settings.BILLING_GST_PERCENT},
        }, status=status.HTTP_201_CREATED)


class VerifyPaymentView(APIView):
    """Step 2: the browser hands back Razorpay's signed result; the signature proves it is genuine."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        studio = studio_for(request)
        serializer = VerifyPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if studio is None or not Payment.objects.filter(studio=studio, razorpay_order_id=data['razorpay_order_id']).exists():
            return error('Payment not found.', status.HTTP_404_NOT_FOUND)
        if not razorpay_client.verify_payment_signature(data['razorpay_order_id'], data['razorpay_payment_id'], data['razorpay_signature']):
            logger.warning('Invalid Razorpay signature for order %s', data['razorpay_order_id'])
            return error('Payment could not be verified. If money was deducted it will be confirmed automatically or refunded.')
        try:
            services.mark_paid(data['razorpay_order_id'], data['razorpay_payment_id'])
        except services.BillingError as exc:
            return error(str(exc), exc.status)
        return Response(SubscriptionSerializer(services.get_subscription(studio)).data)


class PaymentHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        studio = studio_for(request)
        payments = Payment.objects.filter(studio=studio).exclude(status=Payment.Status.CREATED)[:50] if studio else []
        return Response(PaymentSerializer(payments, many=True).data)


class RazorpayWebhookView(APIView):
    """Server-to-server confirmation from Razorpay. Activates payments even if the customer closed
    the browser before step 2 finished. Configure it in Razorpay Dashboard → Webhooks."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        body = request.body  # Must be read before request.data: the signature covers the raw bytes.
        if not razorpay_client.verify_webhook_signature(body, request.headers.get('X-Razorpay-Signature', '')):
            logger.warning('Rejected Razorpay webhook with an invalid signature')
            return error('Invalid signature.')
        try:
            event = json.loads(body)
            entity = event['payload']['payment']['entity']
            order_id, payment_id = entity.get('order_id'), entity['id']
        except (ValueError, KeyError, TypeError):
            return Response({'status': 'ignored'})
        if not order_id or not Payment.objects.filter(razorpay_order_id=order_id).exists():
            return Response({'status': 'ignored'})  # Not one of our subscription orders.

        name = event.get('event')
        if name in ('payment.captured', 'order.paid'):
            try:
                services.mark_paid(order_id, payment_id, amount=entity.get('amount'))
            except services.BillingError as exc:
                # Acknowledge so Razorpay stops retrying; the mismatch is logged for manual review.
                logger.error('Webhook %s for %s not applied: %s', name, order_id, exc)
                return Response({'status': 'rejected'})
        elif name == 'payment.failed':
            services.mark_failed(order_id, payment_id, entity.get('error_description'))
        return Response({'status': 'ok'})
