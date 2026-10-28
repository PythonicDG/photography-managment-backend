from django.urls import path

from .views import LoginView, LogoutView, MeView, RegisterView, StartTrialView, StudioView, VerifyEmailView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('verify-email/', VerifyEmailView.as_view(), name='verify-email'),
    path('studio/', StudioView.as_view(), name='studio'),
    path('trial/start/', StartTrialView.as_view(), name='start-trial'),
    path('login/', LoginView.as_view(), name='login'),
    path('me/', MeView.as_view(), name='me'),
    path('logout/', LogoutView.as_view(), name='logout'),
]
