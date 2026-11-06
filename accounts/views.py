import re
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import authenticate
from django.core import signing
from django.core.mail import EmailMessage, send_mail
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
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

from .models import SharedQuote, Studio, User
from .platform_sync import export_platform, import_platform
from .quote_calc import QuoteError, recalculate
from .whatsapp import WhatsAppError, clean_param, normalize_phone, send_quotation
from .serializers import LoginSerializer, RegisterSerializer, StudioSerializer, UserSerializer


def valid_package_details(details):
    """package_details is optional; when present it must be a bounded name/category/team/deliverables/notes object."""
    if details is None:
        return True
    if not isinstance(details, dict):
        return False
    for key, limit in (('name', 150), ('category', 100), ('notes', 2000)):
        if not isinstance(details.get(key, ''), str) or len(details.get(key, '')) > limit:
            return False
    for key in ('team', 'deliverables'):
        lines = details.get(key, [])
        if not isinstance(lines, list) or len(lines) > 50 or any(not isinstance(line, str) or len(line) > 300 for line in lines):
            return False
    return True


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


class SharedQuoteListView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(list(SharedQuote.objects.filter(studio__owner=request.user).values('id', 'local_id', 'status', 'version', 'root_local_id', 'feedback')))

    def post(self, request):
        studio = Studio.objects.filter(owner=request.user).first()
        if studio is None:
            return Response({'detail': 'Studio setup is required.'}, status=status.HTTP_400_BAD_REQUEST)
        local_id = request.data.get('local_id')
        root_local_id = request.data.get('root_local_id') or local_id
        snapshot = request.data.get('snapshot')
        if not isinstance(local_id, str) or not 1 <= len(local_id) <= 100 or not isinstance(root_local_id, str) or not 1 <= len(root_local_id) <= 100 or not isinstance(snapshot, dict):
            return Response({'detail': 'Invalid quotation.'}, status=status.HTTP_400_BAD_REQUEST)
        required = ('number', 'event', 'client_name', 'items', 'subtotal', 'total')
        if any(key not in snapshot for key in required) or not isinstance(snapshot['items'], list):
            return Response({'detail': 'Quotation is incomplete.'}, status=status.HTTP_400_BAD_REQUEST)
        if not valid_package_details(snapshot.get('package_details')):
            return Response({'detail': 'Package details are invalid.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            snapshot = recalculate(snapshot)
        except QuoteError as error:
            return Response({'detail': str(error)}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            root = SharedQuote.objects.select_for_update().filter(studio=studio, local_id=root_local_id).first()
            existing = SharedQuote.objects.filter(studio=studio, local_id=local_id).first()
            if existing:
                if existing.root_local_id != root_local_id or existing.snapshot != snapshot:
                    return Response({'detail': 'Sent quotations are frozen. Revise as a new version.'}, status=status.HTTP_409_CONFLICT)
                return Response({'id': root.id if root else existing.id, 'status': existing.status, 'version': existing.version})
            if root_local_id != local_id and root is None:
                return Response({'detail': 'Original quotation was not sent.'}, status=status.HTTP_400_BAD_REQUEST)
            if root and root.status == 'Accepted':
                return Response({'detail': 'Accepted quotations cannot be revised.'}, status=status.HTTP_409_CONFLICT)
            latest = SharedQuote.objects.filter(studio=studio, root_local_id=root_local_id).order_by('-version').first() if root else None
            if latest and latest.status == 'Accepted':
                return Response({'detail': 'Accepted quotations cannot be revised.'}, status=status.HTTP_409_CONFLICT)
            version = latest.version + 1 if latest else 1
            shared = SharedQuote.objects.create(studio=studio, local_id=local_id, root_local_id=root_local_id, version=version, snapshot=snapshot)
            if latest and latest.status in ('Pending', 'Changes requested'):
                latest.status = 'Superseded'
                latest.save(update_fields=['status', 'updated_at'])
        return Response({'id': root.id if root else shared.id, 'status': shared.status, 'version': version}, status=status.HTTP_201_CREATED)


class PublicQuoteView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def latest(self, quote_id):
        root = SharedQuote.objects.filter(pk=quote_id).first()
        if root is None:
            return None
        return SharedQuote.objects.filter(studio=root.studio, root_local_id=root.root_local_id).order_by('-version').first() or root

    def get(self, request, quote_id):
        shared = self.latest(quote_id)
        if shared is None:
            return Response({'detail': 'Quotation unavailable.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'id': shared.id, 'studio_name': shared.studio.name, 'studio_city': shared.studio.city, 'status': shared.status, 'version': shared.version, 'snapshot': shared.snapshot})

    def post(self, request, quote_id):
        decision = request.data.get('status')
        feedback = request.data.get('feedback', '')
        if decision not in ('Accepted', 'Rejected', 'Changes requested') or not isinstance(feedback, str) or len(feedback) > 2000 or (decision == 'Changes requested' and not feedback.strip()):
            return Response({'detail': 'Choose a decision and include a note or target price for changes.'}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            shared = self.latest(quote_id)
            if shared is None:
                return Response({'detail': 'Quotation unavailable.'}, status=status.HTTP_404_NOT_FOUND)
            shared = SharedQuote.objects.select_for_update().get(pk=shared.pk)
            if shared.status != 'Pending':
                return Response({'detail': 'A decision has already been recorded.', 'status': shared.status}, status=status.HTTP_409_CONFLICT)
            shared.status = decision
            shared.feedback = feedback.strip() if decision == 'Changes requested' else ''
            shared.save(update_fields=['status', 'feedback', 'updated_at'])
        return Response({'status': shared.status})


class SendDocumentView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'document_email'

    def post(self, request):
        studio = Studio.objects.filter(owner=request.user).first()
        if studio is None:
            return Response({'detail': 'Studio setup is required.'}, status=status.HTTP_400_BAD_REQUEST)
        recipient = str(request.data.get('recipient', '')).strip()
        kind = request.data.get('kind')
        document = request.FILES.get('document')
        try:
            validate_email(recipient)
        except ValidationError:
            return Response({'detail': 'Enter a valid client email.'}, status=status.HTTP_400_BAD_REQUEST)
        if kind not in ('invoice', 'receipt') or document is None or document.size > 2_000_000 or document.size < 100:
            return Response({'detail': 'A valid invoice or receipt PDF under 2 MB is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if document.read(4) != b'%PDF':
            return Response({'detail': 'Upload a PDF document.'}, status=status.HTTP_400_BAD_REQUEST)
        document.seek(0)
        message = EmailMessage(
            subject=f'{studio.name} — Your {kind}',
            body=f'Hello,\n\nPlease find your {kind} from {studio.name} attached.\n\nThank you,\n{studio.name}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
        )
        message.attach(f'{kind}.pdf', document.read(), 'application/pdf')
        message.send(fail_silently=False)
        return Response({'detail': f'{kind.capitalize()} sent.'})


class SendQuotationWhatsAppView(APIView):
    """Sends a quotation PDF to a client on WhatsApp using the approved Meta template."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'document_whatsapp'

    def post(self, request):
        studio = Studio.objects.filter(owner=request.user).first()
        if studio is None:
            return Response({'detail': 'Studio setup is required.'}, status=status.HTTP_400_BAD_REQUEST)
        phone = normalize_phone(request.data.get('phone'))
        if phone is None:
            return Response({'detail': 'Enter a valid client WhatsApp number.'}, status=status.HTTP_400_BAD_REQUEST)
        document = request.FILES.get('document')
        if document is None or document.size > 5_000_000 or document.size < 100:
            return Response({'detail': 'A valid quotation PDF under 5 MB is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if document.read(4) != b'%PDF':
            return Response({'detail': 'Upload a PDF document.'}, status=status.HTTP_400_BAD_REQUEST)
        document.seek(0)
        number = clean_param(request.data.get('number'), 40)
        filename = 'Quotation-' + (re.sub(r'[^A-Za-z0-9_-]', '', number) or 'quote') + '.pdf'
        # Body variables of the template, in order: {{1}} client, {{2}} studio, {{3}} event, {{4}} quotation no., {{5}} total.
        params = [request.data.get('client_name'), studio.name, request.data.get('event'), number, request.data.get('total')]
        try:
            message_id = send_quotation(phone, document.read(), filename, params)
        except WhatsAppError as error:
            return Response({'detail': str(error)}, status=error.status)
        return Response({'detail': 'Quotation sent on WhatsApp.', 'message_id': message_id})


class PlatformView(APIView):
    """Whole-studio data (services, packages, clients, quotes, bookings, payments...) for the frontend."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        studio = Studio.objects.filter(owner=request.user).first()
        if studio is None:
            return Response({'detail': 'Studio setup is required.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'initialized': studio.platform_synced_at is not None, 'data': export_platform(studio)})

    def put(self, request):
        studio = Studio.objects.filter(owner=request.user).first()
        if studio is None:
            return Response({'detail': 'Studio setup is required.'}, status=status.HTTP_400_BAD_REQUEST)
        lists = ('services', 'packages', 'clients', 'enquiries', 'quotes', 'team', 'bookings', 'payments', 'teamPayments', 'assists')
        if not isinstance(request.data, dict) or any(not isinstance(request.data.get(key), list) for key in lists):
            return Response({'detail': 'Invalid data.'}, status=status.HTTP_400_BAD_REQUEST)
        import_platform(studio, request.data)
        return Response({'initialized': True, 'data': export_platform(studio)})
