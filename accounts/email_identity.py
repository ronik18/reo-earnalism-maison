"""Framework EmailAddress authority; User.is_verified is its delivery cache."""
from django.apps import apps


def ensure_email_address(user,verified=None):
    if not apps.is_installed('allauth.account'):return None
    from allauth.account.models import EmailAddress
    defaults={'primary':True,'verified':user.is_verified if verified is None else verified}
    row,_=EmailAddress.objects.get_or_create(user=user,email=user.email,defaults=defaults)
    if verified is not None and row.verified!=verified:
        row.verified=verified;row.save(update_fields=['verified'])
    return row
