import hmac
from django.conf import settings
from django.contrib.auth import logout
from django.utils import timezone
from .models import Device
from .services import _digest


class DeviceSessionMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        request.device=None
        if request.user.is_authenticated:
            device=Device.objects.filter(pk=request.session.get('device_id'),user=request.user,revoked_at__isnull=True).first()
            cookie=request.COOKIES.get(getattr(settings,'DEVICE_COOKIE_NAME','__Host-earnalism_device'),'')
            invalid=(not device or device.expires_at<=timezone.now() or request.session.get('session_epoch')!=request.user.session_epoch or not cookie or not hmac.compare_digest(device.token_binding_sha256,_digest(cookie)))
            if request.user.is_staff:
                from django.utils.dateparse import parse_datetime
                seen=parse_datetime(request.session.get('staff_last_seen',''))
                if not seen or (timezone.now()-seen).total_seconds()>1800:invalid=True
                else:request.session['staff_last_seen']=timezone.now().isoformat()
            if invalid:logout(request)
            else:
                request.device=device
                if (timezone.now()-device.last_seen_at).total_seconds()>1800:
                    Device.objects.filter(pk=device.pk).update(last_seen_at=timezone.now())
        response=self.get_response(request)
        cookie_name=getattr(settings,'DEVICE_COOKIE_NAME','__Host-earnalism_device')
        if hasattr(request,'_maison_device_cookie'):
            response.set_cookie(cookie_name,request._maison_device_cookie,secure=settings.SESSION_COOKIE_SECURE,httponly=True,samesite='Lax',path='/',max_age=28800 if request.user.is_staff else 1209600)
        if getattr(request,'_maison_clear_device_cookie',False):response.delete_cookie(cookie_name,path='/',samesite='Lax')
        return response


class StaffMFAMiddleware:
    """Protect privileged entrypoints without overwriting the email-verification field."""
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        required=getattr(settings,'STAFF_MFA_REQUIRED',not settings.LOCAL)
        staff=request.user.is_authenticated and request.user.is_staff
        if staff:
            if required:
                from .mfa import verified_device
                request.user.staff_mfa_verified=bool(verified_device(request))
            else:request.user.staff_mfa_verified=False
        privileged=request.path.startswith('/api/v1/staff/') or request.path.startswith('/admin/')
        if (required and privileged and request.path not in ['/admin/login/','/admin/logout/']
            and staff and not request.user.staff_mfa_verified):
            if request.path.startswith('/admin/'):
                from django.shortcuts import redirect
                return redirect('/en/settings/?mfa=required')
            from core.api import problem,DomainError
            return problem(DomainError('mfa_required','Verify your authenticator before privileged operations.',403),request)
        return self.get_response(request)
