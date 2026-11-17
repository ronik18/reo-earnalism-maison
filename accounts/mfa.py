"""Staff TOTP uses django-otp; recovery codes are hashed and single use."""
import secrets
import re
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from core.api import DomainError
from core.services import audit
from .models import MFARecoveryCode,User
from .services import _digest,check_rate


def _staff(request):
    if not request.user.is_staff or not request.user.is_active:raise DomainError('permission_denied','Staff access is required.',403)


def _fresh(request):
    stamp=parse_datetime(request.session.get('reauthenticated_at',''))
    if not stamp or timezone.is_naive(stamp) or not timedelta(0)<=timezone.now()-stamp<=timedelta(minutes=5):
        raise DomainError('reauthentication_required','Confirm your password before changing MFA.',403)


def _token(value):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9]{6}',value):raise DomainError('invalid_mfa_code','Enter the six-digit authenticator code.',403)
    return value


def verified_device(request):
    from django_otp.models import Device
    identifier=request.session.get('otp_device_id')
    if not identifier:return None
    device=Device.from_persistent_id(identifier)
    return device if device and device.user_id==request.user.pk and device.confirmed else None


def status(request):
    _staff(request)
    from django_otp.plugins.otp_totp.models import TOTPDevice
    return {'configured':TOTPDevice.objects.filter(user=request.user,confirmed=True).exists(),
        'session_verified':bool(verified_device(request)),
        'recovery_codes_remaining':MFARecoveryCode.objects.filter(user=request.user,used_at=None).count()}


def enroll(request):
    _staff(request);_fresh(request);check_rate('mfa_enroll',str(request.user.public_id),5,3600)
    from django_otp.plugins.otp_totp.models import TOTPDevice
    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk)
        if TOTPDevice.objects.filter(user=request.user,confirmed=True).exists():raise DomainError('mfa_already_configured','Use your existing authenticator or a recovery code.',409)
        TOTPDevice.objects.filter(user=request.user,confirmed=False).delete()
        device=TOTPDevice.objects.create(user=request.user,name='Earnalism staff',confirmed=False)
    # Secret is returned only for fresh enrollment, never status/list/audit/log output.
    return {'device_id':str(device.pk),'configuration_uri':device.config_url}


def confirm(request,token):
    _staff(request);_fresh(request);token=_token(token);check_rate('mfa_confirm',str(request.user.public_id),10,600)
    import django_otp
    from django_otp.plugins.otp_totp.models import TOTPDevice
    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk)
        device=TOTPDevice.objects.select_for_update().filter(user=request.user,confirmed=False).first()
        valid=bool(device and device.verify_token(str(token)))
        if valid:
            device.confirmed=True;device.save(update_fields=['confirmed'])
            MFARecoveryCode.objects.filter(user=request.user).delete()
            codes=[secrets.token_hex(8) for _ in range(10)]
            MFARecoveryCode.objects.bulk_create([MFARecoveryCode(user=request.user,code_sha256=_digest('mfa-recovery:'+code)) for code in codes])
            audit(request.user,'staff.mfa_enrolled',request.user)
    if not valid:raise DomainError('invalid_mfa_code','Authenticator code is invalid or expired.',403)
    django_otp.login(request,device)
    return {'configured':True,'session_verified':True,'recovery_codes':codes}


def verify(request,token):
    _staff(request);token=_token(token);check_rate('mfa_verify',str(request.user.public_id),10,600)
    import django_otp
    from django_otp.plugins.otp_totp.models import TOTPDevice
    # django-otp persists its own throttling and replay counter under the row lock.
    with transaction.atomic():
        device=TOTPDevice.objects.select_for_update().filter(user=request.user,confirmed=True).first()
        valid=bool(device and device.verify_token(str(token)))
    if not valid:raise DomainError('invalid_mfa_code','Authenticator code is invalid or expired.',403)
    django_otp.login(request,device)
    return {'session_verified':True}


def recover(request,code):
    _staff(request);_fresh(request);check_rate('mfa_recovery',str(request.user.public_id),5,600)
    if not isinstance(code,str) or len(code)>100:raise DomainError('invalid_mfa_code','Recovery code is invalid or already used.',403)
    import django_otp
    from django_otp.plugins.otp_totp.models import TOTPDevice
    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk)
        row=MFARecoveryCode.objects.select_for_update().filter(user=request.user,code_sha256=_digest('mfa-recovery:'+code.strip().lower()),used_at=None).first()
        device=TOTPDevice.objects.filter(user=request.user,confirmed=True).first()
        if not row or not device:raise DomainError('invalid_mfa_code','Recovery code is invalid or already used.',403)
        row.used_at=timezone.now();row.save(update_fields=['used_at']);audit(request.user,'staff.mfa_recovery_used',request.user)
    django_otp.login(request,device)
    return {'session_verified':True,'recovery_codes_remaining':MFARecoveryCode.objects.filter(user=request.user,used_at=None).count()}
