"""India's direct electronic account declarations, without an identity vendor.

These records establish what the account holder declared and permitted, not an
independent proof of age, identity or legal parenthood.
"""
from django.conf import settings
from core.api import DomainError
from core.services import audit

ACCOUNT_NOTICE_VERSION='india-account-v1'
PARENT_NOTICE_VERSION='india-parent-v1'
DIRECT_PARENT_METHOD='india-parent-electronic-v1'
ACCOUNT_FIELDS={'account_capacity','account_notice_version','account_terms_consent'}
PARENT_FIELDS={'parent_declared_adult','guardian_permission','account_notice_version','account_terms_consent'}


def enabled():
    return getattr(settings,'INDIA_FIRST_LAUNCH_ENABLED',False) is True


def account_mode(territory):
    """'open' asks no age question; anything unconfigured fails closed to 'adult_only'."""
    return getattr(settings,'MAISON_ACCOUNT_MODES',{}).get(territory,'adult_only')


def adult_declaration(data,territory=None):
    """Account notice consent everywhere; an 18+ declaration only in adult_only territories."""
    if not enabled():return None
    if data.get('account_notice_version')!=ACCOUNT_NOTICE_VERSION or data.get('account_terms_consent') is not True:
        raise DomainError('account_permission_required','Agree to the service terms and account notice to continue.',422)
    if account_mode(territory)=='open':
        return {'account_capacity':'not_asked','account_notice_version':ACCOUNT_NOTICE_VERSION,'account_terms_consent':True}
    if data.get('account_capacity')!='adult':
        raise DomainError('adult_declaration_required','Confirm that you are 18 or older to create an account here.',422)
    return {'account_capacity':'adult','account_notice_version':ACCOUNT_NOTICE_VERSION,'account_terms_consent':True}


def record_adult(user,declaration,purpose):
    if declaration is not None:
        audit(user,'account.capacity_declared',user,{'purpose':purpose,**declaration,'assurance':'self_declaration'})


def parent_declaration(data):
    if (not enabled() or data.get('parent_declared_adult') is not True
        or data.get('guardian_permission') is not True
        or data.get('account_notice_version')!=ACCOUNT_NOTICE_VERSION
        or data.get('account_terms_consent') is not True):
        raise DomainError('guardian_permission_required','Confirm that you are18 or older, are this reader’s parent or legal guardian, and permit the stated account purposes.',422)
    return {'parent_declared_adult':True,'guardian_permission':True,'account_notice_version':ACCOUNT_NOTICE_VERSION,'account_terms_consent':True}


def become_independent_with_password(request,email,password,*,password_consent=None,account_capacity=None,account_notice_version=None,account_terms_consent=None):
    """Keep the same account; expired guardian authority cannot block this route.

    Current password and verified mailbox bind the declaration to the account.
    The declaration itself is not independently verified age evidence.
    """
    from django.contrib.auth import authenticate
    from django.db import transaction
    from django.db.models import F
    from django.utils import timezone
    from . import services
    from .guardian import _revoke_child_sessions
    from .models import User,GuardianAuthorization,EmailActionToken
    from datetime import timedelta
    from .password_consent import record_password_purpose_consent
    if not enabled():raise DomainError('not_found','Not found.',404)
    declaration=adult_declaration({'account_capacity':account_capacity,'account_notice_version':account_notice_version,'account_terms_consent':account_terms_consent})
    email=services._email(email);services.check_rate('independent_account',email,5,900)
    user=authenticate(request,email=email,password=password)
    if user is None or not user.is_verified:raise DomainError('invalid_credentials','Your account identity could not be confirmed.',403)
    with transaction.atomic():
        # Renewal locks the existing household before its grant. Acquire those
        # same User rows first: deferred grant FK checks can otherwise request a
        # parent KEY SHARE at commit while renewal waits for our child row.
        household=set(GuardianAuthorization.objects.filter(child_id=user.pk).values_list('guardian_id',flat=True))|{user.pk}
        locked={row.pk:row for row in User.objects.select_for_update().filter(pk__in=household).order_by('pk')}
        user=locked.get(user.pk)
        if user is None or not user.is_active or not user.is_verified or not user.check_password(password):
            raise DomainError('invalid_credentials','Your account identity could not be confirmed.',403)
        if user.guardian_managed:
            rows=GuardianAuthorization.objects.select_for_update().filter(child=user,status__in=['pending','authorized'])
            rows.update(status='withdrawn',withdrawn_at=timezone.now(),claim_sha256='',claim_expires_at=None,version=F('version')+1)
            for row in GuardianAuthorization.objects.filter(child=user,jurisdiction='IN',method=DIRECT_PARENT_METHOD,status='withdrawn'):
                policy=getattr(settings,'GUARDIAN_AUTHORIZATION_POLICIES',{}).get(f'IN:{row.purpose}:{row.notice_version}:{row.method}',{})
                row.expires_at=timezone.now();row.retain_until=row.expires_at+timedelta(seconds=policy.get('record_retention_seconds',604800));row.save(update_fields=['expires_at','retain_until'])
            user.guardian_managed=False;user.version+=1;user.save(update_fields=['guardian_managed','version'])
            _revoke_child_sessions(user.pk)
            EmailActionToken.objects.filter(user=user,consumed_at=None).update(consumed_at=timezone.now())
            audit(user,'account.independent_capacity',user,{'notice_version':declaration['account_notice_version'],'assurance':'self_declaration'})
        record_password_purpose_consent(user,'reauthentication',password_consent)
        record_adult(user,declaration,'independent_capacity')
    if request.user.is_authenticated and request.user.pk==user.pk:services.logout_member(request)
    return {'status':'delivery_pending'}
