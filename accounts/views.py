from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import authenticate
from django.core import signing
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import Studio, User
from .serializers import LoginSerializer, RegisterSerializer, StudioSerializer, UserSerializer


class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'register'

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                user = serializer.save()
                code = signing.dumps({'id': user.pk, 'email': user.email}, salt='verify-email')
                verification_url = request.build_absolute_uri(reverse('verify-email') + '?' + urlencode({'token': code}))
                send_mail(
                    'Verify your FrameFlow email',
                    f'Hi {user.full_name},\n\nVerify your email by opening this link within 24 hours:\n{verification_url}\n',
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                )
        except IntegrityError:
            return Response({'email': ['An account with this email already exists.']}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'detail': 'Account created. Check your email to verify it before logging in.'}, status=status.HTTP_201_CREATED)


class VerifyEmailView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        try:
            data = signing.loads(request.query_params.get('token', ''), salt='verify-email', max_age=86400)
            user = User.objects.get(pk=data['id'], email=data['email'])
        except (signing.BadSignature, KeyError, User.DoesNotExist):
            return HttpResponseRedirect(settings.FRONTEND_URL + '/login?' + urlencode({'verification': 'invalid'}))
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=['is_active'])
        return HttpResponseRedirect(settings.FRONTEND_URL + '/login?' + urlencode({'verification': 'success'}))


class StudioView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        studio = Studio.objects.filter(owner=request.user).first()
        if studio is None:
            return Response({'detail': 'Studio setup is required.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(StudioSerializer(studio).data)

    def post(self, request):
        if Studio.objects.filter(owner=request.user).exists():
            return Response({'detail': 'Studio already exists.'}, status=status.HTTP_409_CONFLICT)
        serializer = StudioSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(owner=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def patch(self, request):
        studio = Studio.objects.filter(owner=request.user).first()
        if studio is None:
            return Response({'detail': 'Studio setup is required.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = StudioSerializer(studio, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class StartTrialView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        studio = Studio.objects.filter(owner=request.user).first()
        if studio is None:
            return Response({'detail': 'Create your studio before starting the trial.'}, status=status.HTTP_400_BAD_REQUEST)
        if studio.trial_started_at is None:
            studio.trial_started_at = timezone.now()
            studio.save(update_fields=['trial_started_at'])
        return Response(StudioSerializer(studio).data)


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].strip().lower()
        password = serializer.validated_data['password']
        user = authenticate(request, email=email, password=password)
        if user is None:
            return Response({'detail': 'Invalid email or password, or email not verified.'}, status=status.HTTP_400_BAD_REQUEST)
        token, _ = Token.objects.get_or_create(user=user)
        return Response({'token': token.key, 'user': UserSerializer(user).data})


class MeView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class LogoutView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        request.auth.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
