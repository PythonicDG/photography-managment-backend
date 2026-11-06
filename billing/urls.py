from django.urls import path

from .views import CheckoutView, PaymentHistoryView, PlanListView, RazorpayWebhookView, SubscriptionView, VerifyPaymentView

urlpatterns = [
    path('plans/', PlanListView.as_view(), name='billing-plans'),
    path('subscription/', SubscriptionView.as_view(), name='billing-subscription'),
    path('checkout/', CheckoutView.as_view(), name='billing-checkout'),
    path('verify/', VerifyPaymentView.as_view(), name='billing-verify'),
    path('payments/', PaymentHistoryView.as_view(), name='billing-payments'),
    path('webhooks/razorpay/', RazorpayWebhookView.as_view(), name='billing-razorpay-webhook'),
]
