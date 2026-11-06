from django.urls import path

from .views import LoginView, LogoutView, MeView, PlatformView, PublicQuoteView, RegisterView, SendDocumentView, SendQuotationWhatsAppView, SharedQuoteListView, StartTrialView, StudioView, VerifyEmailView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('verify-email/', VerifyEmailView.as_view(), name='verify-email'),
    path('studio/', StudioView.as_view(), name='studio'),
    path('trial/start/', StartTrialView.as_view(), name='start-trial'),
    path('login/', LoginView.as_view(), name='login'),
    path('me/', MeView.as_view(), name='me'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('quotes/', SharedQuoteListView.as_view(), name='shared-quotes'),
    path('quotes/<uuid:quote_id>/', PublicQuoteView.as_view(), name='public-quote'),
    path('platform/', PlatformView.as_view(), name='platform'),
    path('documents/email/', SendDocumentView.as_view(), name='send-document'),
    path('documents/whatsapp/', SendQuotationWhatsAppView.as_view(), name='send-quotation-whatsapp'),
]
