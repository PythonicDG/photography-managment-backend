from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.models import Studio

from .models import FULL_ACCESS_STATES, AccessState
from .services import get_subscription

MESSAGES = {
    AccessState.TRIAL_EXPIRED: 'Your free trial has ended. Choose a plan in Settings → Subscription to keep making changes.',
    AccessState.EXPIRED: 'Your subscription has expired. Renew it in Settings → Subscription to keep making changes.',
    AccessState.SUSPENDED: 'This account is suspended. Please contact support.',
}


class SubscriptionRequired(APIException):
    """HTTP 402 Payment Required. The frontend switches to read-only mode when it sees `code`."""
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = 'subscription_required'

    def __init__(self, state):
        message = MESSAGES.get(state, 'An active subscription is required.')
        super().__init__({'detail': message, 'code': self.default_code, 'state': state})


class HasActiveSubscription(BasePermission):
    """Reads are always allowed so studios can see and export their own data.
    Writes need a running trial, a paid period, or a paid period still inside its grace days."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if not (request.user and request.user.is_authenticated):
            return False
        studio = Studio.objects.filter(owner=request.user).first()
        if studio is None:
            return True  # The view itself answers "set up your studio first".
        subscription = get_subscription(studio)
        if subscription is None:
            raise SubscriptionRequired(AccessState.TRIAL_EXPIRED)
        state = subscription.access_state()
        if state in FULL_ACCESS_STATES:
            return True
        raise SubscriptionRequired(state)
