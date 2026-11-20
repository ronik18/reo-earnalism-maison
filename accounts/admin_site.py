"""Default Django administration with the approved password-purpose forms."""
from django.contrib.admin import AdminSite
from django.contrib.auth.views import PasswordChangeView
from django.urls import reverse
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from core.api import DomainError
from core.services import locked_actor
from .models import Device
from .admin_forms import PasswordPurposeAdminAuthenticationForm, PasswordPurposeAdminPasswordChangeForm


class BoundPasswordChangeView(PasswordChangeView):
    def form_valid(self,form):
        with transaction.atomic():
            try:user=locked_actor(self.request.user)
            except DomainError as error:raise PermissionDenied('Account authority changed.') from error
            if not user.check_password(form.cleaned_data['old_password']):
                form.add_error('old_password','Your old password was entered incorrectly. Please enter it again.')
                return self.form_invalid(form)
            user.session_epoch+=1
            form.user=user
            response=super().form_valid(form)
            Device.objects.filter(pk=self.request.session.get('device_id'),user=user,revoked_at=None).update(session_id=self.request.session.session_key)
            self.request.session['session_epoch']=user.session_epoch
            now=timezone.now();current=self.request.session.get('device_id')
            user.devices.exclude(pk=current).filter(revoked_at=None).update(revoked_at=now,version=F('version')+1)
            from reader.models import DownloadLicense
            DownloadLicense.objects.filter(user=user,revoked_at=None).exclude(device_id=current).update(revoked_at=now)
            return response


class PasswordPurposeAdminSite(AdminSite):
    login_form = PasswordPurposeAdminAuthenticationForm

    def password_change(self, request, extra_context=None):
        request.current_app = self.name
        options = {
            'form_class': PasswordPurposeAdminPasswordChangeForm,
            'success_url': reverse('admin:password_change_done', current_app=self.name),
            'extra_context': {**self.each_context(request), **(extra_context or {})},
        }
        if self.password_change_template is not None:
            options['template_name'] = self.password_change_template
        return BoundPasswordChangeView.as_view(**options)(request)
