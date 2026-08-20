"""Helpers OTP (activation compte / reset password)."""
import random

from django.utils import timezone

from Userauths.models import PWD_FORGET
from Userauths.utils import send_account_activation_otp_email

OTP_EXPIRY_SECONDS = 300
PURPOSE_ACTIVATION = PWD_FORGET.PURPOSE_ACTIVATION


def generate_otp_code():
    return random.randint(100000, 999999)


def invalidate_active_otps(user, purpose=PURPOSE_ACTIVATION):
    PWD_FORGET.objects.filter(
        user_id=user, status='0', purpose=purpose,
    ).update(status='1')


def get_active_otp(user, purpose=PURPOSE_ACTIVATION):
    return PWD_FORGET.objects.filter(
        user_id=user, status='0', purpose=purpose,
    ).order_by('-creat_at').first()


def otp_remaining_seconds(otp_request):
    if not otp_request:
        return 0
    elapsed = (timezone.now() - otp_request.creat_at).total_seconds()
    return max(0, int(OTP_EXPIRY_SECONDS - elapsed))


def create_and_send_activation_otp(user):
    """Invalide les OTP activation actifs, en crée un nouveau et envoie l'email."""
    invalidate_active_otps(user, PURPOSE_ACTIVATION)
    otp = generate_otp_code()
    PWD_FORGET.objects.create(
        user_id=user,
        otp=otp,
        status='0',
        purpose=PURPOSE_ACTIVATION,
    )
    email_sent = send_account_activation_otp_email(user, otp)
    return email_sent, OTP_EXPIRY_SECONDS


def verify_activation_otp(user, otp_code):
    """
    Vérifie l'OTP d'activation.
    Retourne (ok: bool, error_code: str|None)
      error_code: 'invalid' | 'expired' | None
    """
    try:
        otp_int = int(str(otp_code).strip())
    except (TypeError, ValueError):
        return False, 'invalid'

    otp_request = PWD_FORGET.objects.filter(
        user_id=user,
        otp=otp_int,
        status='0',
        purpose=PURPOSE_ACTIVATION,
    ).order_by('-creat_at').first()

    if not otp_request:
        return False, 'invalid'

    if otp_remaining_seconds(otp_request) <= 0:
        otp_request.status = '1'
        otp_request.save(update_fields=['status'])
        return False, 'expired'

    otp_request.status = '1'
    otp_request.save(update_fields=['status'])
    invalidate_active_otps(user, PURPOSE_ACTIVATION)
    return True, None


def activation_otp_status(user):
    active = get_active_otp(user, PURPOSE_ACTIVATION)
    remaining = otp_remaining_seconds(active)
    return {
        'remaining_seconds': remaining,
        'otp_expired': active is None or remaining <= 0,
    }
