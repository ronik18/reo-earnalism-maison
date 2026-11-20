"""Affirmative password-purpose gates for Django's staff password forms."""
from django import forms
from django.contrib.admin.forms import AdminAuthenticationForm, AdminPasswordChangeForm
from django.db import transaction
from core.api import DomainError
from .password_consent import PASSWORD_PURPOSE_VERSION, validate_password_purpose_consent, record_password_purpose_consent

PASSWORD_PURPOSE_LABEL = 'I consent to this use of my password for account access and security.'


class PasswordPurposeAdminAuthenticationForm(AdminAuthenticationForm):
    password_purpose_consent = forms.BooleanField(required=True, label=PASSWORD_PURPOSE_LABEL)
    password_purpose_version = forms.CharField(required=True, initial=PASSWORD_PURPOSE_VERSION, widget=forms.HiddenInput)

    def clean(self):
        try:
            evidence = validate_password_purpose_consent(self.cleaned_data)
        except DomainError as error:
            raise forms.ValidationError(error.message, code=error.code)
        result = super().clean()
        self.request._maison_admin_password_consent = evidence
        return result


class PasswordPurposeAdminPasswordChangeForm(AdminPasswordChangeForm):
    password_purpose_consent = forms.BooleanField(required=True, label=PASSWORD_PURPOSE_LABEL)
    password_purpose_version = forms.CharField(required=True, initial=PASSWORD_PURPOSE_VERSION, widget=forms.HiddenInput)

    def clean_old_password(self):
        # Django validates old_password before Form.clean; gate first here so
        # an absent/stale purpose choice never invokes password verification.
        try:
            self.password_purpose_evidence = validate_password_purpose_consent({
                'password_purpose_consent': self.fields['password_purpose_consent'].clean(self.data.get('password_purpose_consent')),
                'password_purpose_version': self.data.get('password_purpose_version'),
            })
        except DomainError as error:
            raise forms.ValidationError(error.message, code=error.code)
        return super().clean_old_password()

    def save(self, commit=True):
        with transaction.atomic():
            user = super().save(commit=commit)
            if commit:
                record_password_purpose_consent(user, 'password_change', self.password_purpose_evidence)
            return user
