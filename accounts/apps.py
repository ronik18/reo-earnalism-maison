from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'
    def ready(self):
        from . import signals  # noqa: F401


from django.contrib.admin import apps as admin_apps


class PasswordPurposeAdminConfig(admin_apps.AdminConfig):
    default = False
    default_site = 'accounts.admin_site.PasswordPurposeAdminSite'
