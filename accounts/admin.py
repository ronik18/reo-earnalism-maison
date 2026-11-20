"""The default staff login uses the same affirmative purpose form."""
from django.contrib import admin
from .admin_forms import PasswordPurposeAdminAuthenticationForm
admin.site.login_form = PasswordPurposeAdminAuthenticationForm
