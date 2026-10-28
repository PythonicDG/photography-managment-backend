import re

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Studio, User


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    class Meta:
        model = User
        fields = ('full_name', 'email', 'phone', 'password')

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def validate_phone(self, value):
        digits = re.sub(r'\D', '', value)
        if len(digits) == 12 and digits.startswith('91'):
            digits = digits[2:]
        if not re.fullmatch(r'[6-9]\d{9}', digits):
            raise serializers.ValidationError('Enter a valid 10-digit Indian mobile number.')
        return digits

    def validate_full_name(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError('Please enter your full name.')
        return value

    def validate(self, attrs):
        if len(attrs['password']) < 8:
            raise serializers.ValidationError({'password': ['Password must contain at least 8 characters.']})
        try:
            validate_password(attrs['password'], user=User(email=attrs['email'], full_name=attrs['full_name']))
        except DjangoValidationError as error:
            raise serializers.ValidationError({'password': error.messages}) from error
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(is_active=False, **validated_data)


class StudioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Studio
        fields = ('name', 'logo', 'city', 'state', 'business_type', 'gstin', 'trial_started_at')
        read_only_fields = ('trial_started_at',)

    def validate_name(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError('Please enter your studio name.')
        return value

    def validate_logo(self, value):
        if value and (not value.startswith('data:image/') or len(value) > 2_800_000):
            raise serializers.ValidationError('Choose an image under 2 MB.')
        return value

    def validate_gstin(self, value):
        value = value.strip().upper()
        if value and not re.fullmatch(r'\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]', value):
            raise serializers.ValidationError('Enter a valid GSTIN.')
        return value


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'full_name', 'email', 'phone')
