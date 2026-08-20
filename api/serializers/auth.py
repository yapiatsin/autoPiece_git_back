from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from Userauths.models import CustomUser, ProfilUser

from api.services.otp import (
    activation_otp_status,
    create_and_send_activation_otp,
    verify_activation_otp,
)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(label=_('Email'))
    password = serializers.CharField(
        write_only=True, style={'input_type': 'password'}, label=_('Mot de passe'),
    )

    def validate(self, attrs):
        email = attrs.get('email', '').strip().lower()
        password = attrs.get('password')
        user = CustomUser.objects.filter(email__iexact=email).first()
        if user and not user.is_active:
            # Distinguer compte non activé vs désactivé (vérifie le mot de passe)
            if user.check_password(password):
                raise serializers.ValidationError(
                    _('Compte non activé. Vérifiez votre email pour le code OTP.'),
                    code='authorization',
                )
            raise serializers.ValidationError(
                _('Email ou mot de passe incorrect.'), code='authorization',
            )
        if user:
            user = authenticate(
                request=self.context.get('request'),
                username=user.username,
                password=password,
            )
        if not user:
            raise serializers.ValidationError(
                _('Email ou mot de passe incorrect.'), code='authorization',
            )
        attrs['user'] = user
        return attrs


class PasswordChangeSerializer(serializers.Serializer):
    ancien_password = serializers.CharField(write_only=True)
    nouveau_password = serializers.CharField(write_only=True, min_length=8)

    def validate_nouveau_password(self, value):
        try:
            validate_password(value, user=self.context.get('request').user)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value


class ClientUserSerializer(serializers.ModelSerializer):
    local_entrepot_nom = serializers.CharField(source='local_entrepot.nom', read_only=True)
    local_entrepot_code = serializers.CharField(source='local_entrepot.code', read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'contact', 'role', 'genre',
            'local_entrepot', 'local_entrepot_nom', 'local_entrepot_code',
            'is_active', 'date_joined',
        ]
        read_only_fields = ['id', 'role', 'date_joined', 'is_active']


class ClientRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    password2 = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = CustomUser
        fields = [
            'username', 'email', 'password', 'password2',
            'first_name', 'last_name', 'contact', 'genre',
        ]

    def validate_email(self, value):
        value = value.strip().lower()
        existing = CustomUser.objects.filter(email__iexact=value).first()
        if existing:
            # Compte client inactif : autoriser le renvoi d'OTP (géré dans create)
            if existing.role == 'client' and not existing.is_active:
                return value
            raise serializers.ValidationError(_('Cet email est déjà utilisé.'))
        return value

    def validate_username(self, value):
        value = value.strip()
        email = (self.initial_data.get('email') or '').strip().lower()
        existing_email_user = (
            CustomUser.objects.filter(email__iexact=email).first() if email else None
        )
        taken = CustomUser.objects.filter(username__iexact=value).first()
        if taken and taken != existing_email_user:
            raise serializers.ValidationError(_("Ce nom d'utilisateur est déjà pris."))
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs.pop('password2'):
            raise serializers.ValidationError({'password2': _('Les mots de passe ne correspondent pas.')})
        try:
            validate_password(attrs['password'])
        except DjangoValidationError as e:
            raise serializers.ValidationError({'password': list(e.messages)})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password')
        email = validated_data['email'].strip().lower()
        existing = CustomUser.objects.filter(
            email__iexact=email, role='client', is_active=False,
        ).first()

        if existing:
            # Mise à jour du compte en attente d'activation + nouvel OTP
            for field in ('username', 'first_name', 'last_name', 'contact', 'genre'):
                if field in validated_data:
                    setattr(existing, field, validated_data[field])
            existing.username = existing.username.strip()
            existing.set_password(password)
            existing.save()
            ProfilUser.objects.get_or_create(user=existing)
            email_sent, expires_in = create_and_send_activation_otp(existing)
            existing._otp_email_sent = email_sent
            existing._otp_expires_in = expires_in
            return existing

        user = CustomUser(**validated_data)
        user.email = email
        user.username = user.username.strip()
        user.role = 'client'
        user.is_active = False
        user.set_password(password)
        user.save()
        ProfilUser.objects.get_or_create(user=user)
        email_sent, expires_in = create_and_send_activation_otp(user)
        user._otp_email_sent = email_sent
        user._otp_expires_in = expires_in
        return user


class RegisterOtpVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6, min_length=6)

    def validate(self, attrs):
        email = attrs['email'].strip().lower()
        user = CustomUser.objects.filter(
            email__iexact=email, role='client',
        ).first()
        if not user:
            raise serializers.ValidationError(
                {'email': _('Aucun compte en attente pour cet email.')},
            )
        if user.is_active:
            raise serializers.ValidationError(
                {'email': _('Ce compte est déjà activé. Connectez-vous.')},
            )
        ok, error = verify_activation_otp(user, attrs['otp'])
        if not ok:
            if error == 'expired':
                raise serializers.ValidationError(
                    {'otp': _('Code OTP expiré. Demandez un nouveau code.')},
                )
            raise serializers.ValidationError({'otp': _('Code OTP invalide.')})
        attrs['user'] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data['user']
        user.is_active = True
        user.save(update_fields=['is_active'])
        return user


class RegisterOtpResendSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate(self, attrs):
        email = attrs['email'].strip().lower()
        user = CustomUser.objects.filter(
            email__iexact=email, role='client', is_active=False,
        ).first()
        if not user:
            raise serializers.ValidationError(
                {'email': _("Aucun compte en attente d'activation pour cet email.")},
            )
        attrs['email'] = email
        attrs['user'] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data['user']
        email_sent, expires_in = create_and_send_activation_otp(user)
        return {
            'email': user.email,
            'email_sent': email_sent,
            'otp_expires_in': expires_in,
            **activation_otp_status(user),
        }


class ProfilClientSerializer(serializers.ModelSerializer):
    nom_complet = serializers.CharField(read_only=True)
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = ProfilUser
        fields = [
            'pid', 'nom_complet', 'photo', 'photo_url',
            'date_naissance', 'adresse', 'ville', 'pays', 'code_postal', 'bio',
            'date_creation', 'date_modification',
        ]
        read_only_fields = ['pid', 'date_creation', 'date_modification']

    def get_photo_url(self, obj):
        if not obj.photo:
            return None
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.photo.url)
        return obj.photo.url


class ProfilClientWriteSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    contact = serializers.CharField(required=False, allow_blank=True, max_length=15)

    class Meta:
        model = ProfilUser
        fields = [
            'first_name', 'last_name', 'contact',
            'date_naissance', 'bio', 'photo',
        ]

    def update(self, instance, validated_data):
        user = instance.user
        user_update_fields = []
        for field in ('first_name', 'last_name', 'contact'):
            if field in validated_data:
                setattr(user, field, validated_data.pop(field))
                user_update_fields.append(field)
        if user_update_fields:
            user.save(update_fields=user_update_fields)
        return super().update(instance, validated_data)
