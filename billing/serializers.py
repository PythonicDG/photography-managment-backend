import math

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from .models import BillingCycle, Payment, Plan, Subscription


class PlanSerializer(serializers.ModelSerializer):
    features = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = ('slug', 'name', 'tagline', 'price_monthly', 'price_yearly', 'is_featured', 'features')

    def get_features(self, plan):
        return [feature.text for feature in plan.features.all()]


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    state = serializers.SerializerMethodField()
    state_label = serializers.SerializerMethodField()
    has_access = serializers.SerializerMethodField()
    access_ends_at = serializers.SerializerMethodField()
    days_left = serializers.SerializerMethodField()
    grace_days = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = (
            'state', 'state_label', 'has_access', 'access_ends_at', 'days_left', 'grace_days',
            'plan', 'billing_cycle', 'trial_ends_at', 'current_period_start', 'current_period_end',
        )

    def _now(self):
        # One timestamp per response so every field agrees.
        if not hasattr(self, '_now_cache'):
            self._now_cache = timezone.now()
        return self._now_cache

    def get_state(self, subscription):
        return subscription.access_state(self._now())

    def get_state_label(self, subscription):
        return subscription.access_state(self._now()).label

    def get_has_access(self, subscription):
        return subscription.has_full_access(self._now())

    def get_access_ends_at(self, subscription):
        ends = subscription.access_ends_at(self._now())
        return serializers.DateTimeField().to_representation(ends) if ends else None

    def get_days_left(self, subscription):
        ends = subscription.access_ends_at(self._now())
        if ends is None:
            return 0
        return max(0, math.ceil((ends - self._now()).total_seconds() / 86400))

    def get_grace_days(self, subscription):
        return settings.BILLING_GRACE_DAYS


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = (
            'receipt', 'plan_name', 'billing_cycle', 'base_amount', 'gst_amount', 'total_amount', 'currency',
            'status', 'failure_reason', 'period_start', 'period_end', 'created_at', 'paid_at', 'razorpay_payment_id',
        )


class CheckoutSerializer(serializers.Serializer):
    plan = serializers.SlugField()
    billing_cycle = serializers.ChoiceField(choices=BillingCycle.choices)

    def validate_plan(self, slug):
        plan = Plan.objects.filter(slug=slug, is_active=True).first()
        if plan is None:
            raise serializers.ValidationError('This plan is not available.')
        return plan


class VerifyPaymentSerializer(serializers.Serializer):
    razorpay_order_id = serializers.CharField(max_length=64)
    razorpay_payment_id = serializers.CharField(max_length=64)
    razorpay_signature = serializers.CharField(max_length=128)
