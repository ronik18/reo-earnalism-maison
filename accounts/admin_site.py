"""Default Django administration with the approved password-purpose forms."""
from django.contrib.admin import AdminSite
from django.contrib.auth.views import PasswordChangeView
from django.urls import reverse
from .admin_forms import PasswordPurposeAdminAuthenticationForm, PasswordPurposeAdminPasswordChangeForm


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
        return PasswordChangeView.as_view(**options)(request)
