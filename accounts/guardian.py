"""Policy-gated operational guardian workflow, not a legal VPC certification.

National methods, subject verification, collection grounds, retention and regional
placement require actual acceptance evidence. An audit digest verifies neither
parental relationship nor the identity associated with a future account email.
Production settings remain disabled with no public methods configured.

Schema dependency: accounts migrations 0004 and 0005 must precede deploying this
model code. Even with the feature off, User reverse relations are traversed by
account cleanup and personal-data exports. Apply only against an approved exact
isolated target; never turn on a synthetic test policy in a real environment.
"""
import hashlib
import json
import re
import secrets
import hmac
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from core.api import DomainError,public_uuid
from core.models import OperationReceipt
from core.services import locked_actor,apply_operation,audit
from .models import User,GuardianAuthorization

PURPOSES={'account_processing','privacy_access','privacy_delete'}


def _policy(jurisdiction,purpose,notice,method):
    if not getattr(settings,'GUARDIAN_AUTHORIZATION_ENABLED',False):
        raise DomainError('feature_disabled','Guardian authority is not enabled.',409)
    if (not isinstance(jurisdiction,str) or jurisdiction not in settings.MAISON_PUBLICATION_TERRITORIES or not isinstance(purpose,str) or purpose not in PURPOSES
        or any(not isinstance(v,str) or not re.fullmatch(r'[a-zA-Z0-9._-]{1,64}',v) for v in (notice,method))):
        raise DomainError('guardian_policy_unavailable','No qualified operational policy matches this request.',409)
    key=f'{jurisdiction}:{purpose}:{notice}:{method}'
    policy=getattr(settings,'GUARDIAN_AUTHORIZATION_POLICIES',{}).get(key)
    if not isinstance(policy,dict) or policy.get('enabled') is not True or type(policy.get('max_lifetime_seconds')) is not int or not 60<=policy['max_lifetime_seconds']<=2592000:
        raise DomainError('guardian_policy_unavailable','No qualified operational policy matches this request.',409)
    digest=hashlib.sha256(json.dumps([key,policy],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return policy,digest


def _locks(request,child_id,guardian_id,review=False):
    # Every lifecycle path uses the same User-before-authorization lock order.
    ids=sorted({v for v in (request.user.pk,child_id,guardian_id) if v is not None})
    users={u.pk:u for u in User.objects.select_for_update().filter(pk__in=ids).order_by('pk')}
    actor=locked_actor(request.user)
    if not getattr(request.user,'_maison_operation_authority',None):
        raise DomainError('authentication_required','A current bound session is required.',401)
    if len(users)!=len(ids) or any(not u.is_active for u in users.values()) or not actor.is_verified:
        raise DomainError('guardian_authority_unavailable','Active verified accounts are required.',403)
    if review:
        from .mfa import verified_device
        if (actor.pk in (child_id,guardian_id) or not actor.is_staff
            or not actor.has_perm('accounts.review_guardian_authorization') or not verified_device(request)):
            raise DomainError('permission_denied','Independent authorized staff MFA review is required.',403)
    return actor


def _current(row):
    _,digest=_policy(row.jurisdiction,row.purpose,row.notice_version,row.method)
    if row.status=='authorized' and (not row.reviewer_id or not User.objects.filter(pk=row.reviewer_id,is_active=True).exists()):
        raise DomainError('guardian_authority_unavailable','Review authority is unavailable.',403)
    if digest!=row.policy_sha256 or row.status in ('withdrawn','rejected') or row.expires_at<=timezone.now():
        raise DomainError('guardian_authority_unavailable','Authority is expired, withdrawn or superseded.',403)


def _data(row):
    return {'authorization_id':str(row.pk),'status':'expired' if row.expires_at<=timezone.now() and row.status not in ('withdrawn','rejected') else row.status,'purpose':row.purpose,
        'notice_version':row.notice_version,'jurisdiction':row.jurisdiction,'method':row.method,'version':row.version,
        'prospective_subject_id':str(row.prospective_subject_id),'child_bound':bool(row.child_id and row.child.is_verified),'claim_submitted':row.claimed_at is not None,
        'expires_at':row.expires_at.isoformat(),'operational_only':True}


def _row(value):
    row=GuardianAuthorization.objects.filter(pk=public_uuid(value)).first()
    if not row:raise DomainError('not_found','Authorization not found.',404)
    return row


@transaction.atomic
def prepare(request,child_id,guardian_id,*,jurisdiction,purpose,notice_version,method,operation_id):
    policy,digest=_policy(jurisdiction,purpose,notice_version,method)
    _locks(request,child_id,guardian_id,review=True)
    if child_id==guardian_id:raise DomainError('validation_error','Separate subjects are required.',422)
    old=OperationReceipt.objects.filter(actor=request.user,operation_id=operation_id).first()
    if old and old.kind=='guardian.prepare':
        previous=GuardianAuthorization.objects.select_for_update().filter(pk=old.response['authorization_id']).first()
        if previous is None:raise DomainError('guardian_authority_unavailable','Authority is no longer available.',403)
        _current(previous)
    payload={'child_id':child_id,'guardian_id':guardian_id,'jurisdiction':jurisdiction,'purpose':purpose,'notice_version':notice_version,'method':method}
    def mutate():
        row=GuardianAuthorization.objects.create(child_id=child_id,guardian_id=guardian_id,reviewer=request.user,
            jurisdiction=jurisdiction,purpose=purpose,notice_version=notice_version,method=method,policy_sha256=digest,
            expires_at=timezone.now()+timedelta(seconds=policy['max_lifetime_seconds']))
        audit(request.user,'guardian.prepared',row)
        return 201,_data(row),row.version
    return apply_operation(request.user,operation_id,'guardian.prepare',payload,mutate)


def _review_eligible(request):
    # Check current reviewer eligibility without taking an early actor row lock.
    # The existing sorted household locks recheck this before any mutation.
    from .mfa import verified_device
    from .models import Device
    actor=User.objects.filter(pk=request.user.pk,is_active=True,is_verified=True,is_staff=True).first()
    authority=getattr(request.user,'_maison_operation_authority',None)
    valid=False
    if actor is not None and isinstance(authority,tuple) and len(authority)==4:
        epoch,device_id,session_id,binding=authority
        valid=(actor.session_epoch==epoch and Device.objects.filter(pk=device_id,user=actor,session_id=session_id,token_binding_sha256=binding,revoked_at__isnull=True,expires_at__gt=timezone.now()).exists())
    if not valid or not actor.has_perm('accounts.review_guardian_authorization') or not verified_device(request):
        raise DomainError('permission_denied','Independent authorized staff MFA review is required.',403)


@transaction.atomic
def review(request,authorization_id,*,evidence_sha256,approve,expected_version,operation_id):
    _review_eligible(request)
    row=_row(authorization_id)
    _locks(request,row.child_id,row.guardian_id,review=True)
    row=GuardianAuthorization.objects.select_for_update().get(pk=row.pk);_current(row)
    if row.reviewer_id not in (None,request.user.pk):raise DomainError('permission_denied','The assigned reviewer is required.',403)
    if type(approve) is not bool or not isinstance(evidence_sha256,str) or not re.fullmatch('[0-9a-f]{64}',evidence_sha256):
        raise DomainError('validation_error','An exact private evidence digest and decision are required.',422)
    payload={'authorization_id':str(row.pk),'evidence_sha256':evidence_sha256,'approve':approve,'expected_version':expected_version}
    def mutate():
        if row.version!=expected_version:raise DomainError('version_conflict','Authorization changed.',412)
        if row.status!='pending':raise DomainError('guardian_authority_unavailable','Review already completed.',409)
        row.reviewer=request.user;row.status='authorized' if approve else 'rejected';row.evidence_sha256=evidence_sha256;row.reviewed_at=timezone.now();row.version+=1;row.save()
        audit(request.user,'guardian.reviewed',row,{'outcome':row.status})
        return 200,_data(row),row.version
    return apply_operation(request.user,operation_id,'guardian.review',payload,mutate)


@transaction.atomic
def withdraw(request,authorization_id,*,expected_version,operation_id):
    row=_own_locked(request,authorization_id);actor=request.user
    def mutate():
        if row.version!=expected_version:raise DomainError('version_conflict','Authorization changed.',412)
        row.claim_sha256='';row.claim_expires_at=None;row.status='withdrawn';row.withdrawn_at=timezone.now();row.version+=1;row.save()
        if row.purpose=='account_processing' and row.child_id:
            _revoke_child_sessions(row.child_id)
        audit(actor,'guardian.withdrawn',row)
        return 200,_data(row),row.version
    return apply_operation(request.user,operation_id,'guardian.withdraw',{'authorization_id':str(row.pk),'expected_version':expected_version},mutate)


@transaction.atomic
def require_authority(request,authorization_id,*,child_id,jurisdiction,purpose,notice_version):
    row=_row(authorization_id);actor=_locks(request,row.child_id,row.guardian_id)
    row=GuardianAuthorization.objects.select_for_update().get(pk=row.pk);_current(row)
    if (actor.pk!=row.guardian_id or row.child_id!=child_id or row.jurisdiction!=jurisdiction
        or row.purpose!=purpose or row.notice_version!=notice_version or row.status!='authorized'):
        raise DomainError('guardian_authority_unavailable','No exact current authority exists.',403)
    # Reviewer active state is checked at this decision point, not a continuing
    # permission grant: this returns metadata only. Future data-action integration
    # must lock/revalidate all relevant authority through that action's commit.
    # Caller must separately qualify the specific rights action/data scope. Never
    # return child data or automatically dispatch an export/deletion from here.
    return _data(row)


def enabled():
    if not getattr(settings,'GUARDIAN_AUTHORIZATION_ENABLED',False):
        raise DomainError('not_found','Not found.',404)


def _public_policy(jurisdiction,purpose,notice,method):
    policy,digest=_policy(jurisdiction,purpose,notice,method)
    # Operational toggles cannot qualify a legal method, collection route or
    # country. The configured references must point to actual accepted evidence.
    if (type(policy.get('record_retention_seconds')) is not int or not 0<=policy['record_retention_seconds']<=31536000
        or policy.get('public_enabled') is not True or any(not isinstance(policy.get(k),str) or not 1<=len(policy[k])<=160 for k in ('legal_review_ref','collection_route_ref'))):
        raise DomainError('guardian_policy_unavailable','This authorization route is not available.',409)
    return policy,digest


def policies():
    enabled();items=[]
    for key in getattr(settings,'GUARDIAN_AUTHORIZATION_POLICIES',{}):
        try:
            jurisdiction,purpose,notice,method=key.split(':')
            policy,_=_public_policy(jurisdiction,purpose,notice,method)
        except (ValueError,AttributeError,DomainError):continue
        items.append({'jurisdiction':jurisdiction,'purpose':purpose,'notice_version':notice,'method':method,'max_lifetime_seconds':policy['max_lifetime_seconds']})
    return items


def _own_row(request,authorization_id):
    # A member must not inspect or lock another household before ownership is
    # established: foreign active/inactive/revoked records all remain not-found.
    row=GuardianAuthorization.objects.filter(pk=public_uuid(authorization_id),guardian_id=request.user.pk).first()
    if not row:raise DomainError('not_found','Authorization not found.',404)
    return row


def _own_locked(request,authorization_id):
    row=_own_row(request,authorization_id)
    _locks(request,row.child_id,row.guardian_id)
    row=GuardianAuthorization.objects.select_for_update().filter(pk=row.pk,guardian_id=request.user.pk).first()
    if not row:raise DomainError('not_found','Authorization not found.',404)
    return row


@transaction.atomic
def request_authorization(request,*,jurisdiction,purpose,notice_version,method,operation_id,source_authorization_id=None):
    enabled()
    from .views import require_fresh
    require_fresh(request)
    policy,digest=_public_policy(jurisdiction,purpose,notice_version,method)
    _locks(request,None,request.user.pk)
    child_id=None
    if purpose!='account_processing':
        source=_own_locked(request,source_authorization_id)
        if source.purpose!='account_processing' or not source.child_id or not source.child.is_verified or source.jurisdiction!=jurisdiction:
            raise DomainError('guardian_authority_unavailable','A current bound account authorization is required.',403)
        child_id=source.child_id
    elif source_authorization_id is not None:
        # A historical opaque relation only routes a fresh independent review;
        # expired/withdrawn authority itself grants no renewed processing.
        source=_own_locked(request,source_authorization_id)
        if source.purpose!='account_processing' or source.jurisdiction!=jurisdiction or not source.child_id or not source.child.is_verified:
            raise DomainError('guardian_authority_unavailable','A bound account relation is required.',403)
        child_id=source.child_id
    old=OperationReceipt.objects.filter(actor=request.user,operation_id=operation_id,kind='guardian.request').first()
    if old:
        previous=GuardianAuthorization.objects.select_for_update().filter(pk=old.response['authorization_id']).first()
        if not previous:raise DomainError('guardian_authority_unavailable','Authorization no longer exists.',403)
        _current(previous)
    payload={'jurisdiction':jurisdiction,'purpose':purpose,'notice_version':notice_version,'method':method,'source_authorization_id':source_authorization_id}
    def mutate():
        row=GuardianAuthorization.objects.create(guardian=request.user,child_id=child_id,jurisdiction=jurisdiction,purpose=purpose,notice_version=notice_version,method=method,policy_sha256=digest,expires_at=timezone.now()+timedelta(seconds=policy['max_lifetime_seconds']),retain_until=timezone.now()+timedelta(seconds=policy['max_lifetime_seconds']+policy['record_retention_seconds']))
        audit(request.user,'guardian.requested',row)
        return 201,_data(row),row.version
    return apply_operation(request.user,operation_id,'guardian.request',payload,mutate)


@transaction.atomic
def list_authorizations(request):
    enabled();_locks(request,None,request.user.pk)
    from core.pagination import keyset_page
    return keyset_page(GuardianAuthorization.objects.filter(guardian=request.user).select_related('child'),request.GET,f'guardian:{request.user.pk}','created_at',_data)


@transaction.atomic
def authorization_detail(request,authorization_id):
    enabled();return _data(_own_locked(request,authorization_id))


@transaction.atomic
def issue_claim(request,authorization_id):
    enabled()
    from .views import require_fresh
    require_fresh(request)
    row=_own_locked(request,authorization_id);_current(row)
    _public_policy(row.jurisdiction,row.purpose,row.notice_version,row.method)
    if row.status!='authorized' or row.purpose!='account_processing' or row.child_id or row.claimed_at:
        raise DomainError('guardian_claim_unavailable','This authorization cannot create an account.',409)
    token=secrets.token_urlsafe(32)
    row.claim_sha256=hashlib.sha256(token.encode()).hexdigest();row.claim_expires_at=min(row.expires_at,timezone.now()+timedelta(minutes=5));row.save(update_fields=['claim_sha256','claim_expires_at'])
    # Raw capability exists only in this no-store response; no receipt or log.
    return {'capability':token,'expires_at':row.claim_expires_at.isoformat()}


def _claim_preflight(request,row):
    _current(row);_public_policy(row.jurisdiction,row.purpose,row.notice_version,row.method)
    token=request.headers.get('X-Guardian-Claim','')
    if (row.status!='authorized' or row.purpose!='account_processing' or row.child_id or row.claimed_at
        or not isinstance(token,str) or not 32<=len(token)<=128 or not row.claim_sha256 or not row.claim_expires_at
        or row.claim_expires_at<=timezone.now() or not hmac.compare_digest(row.claim_sha256,hashlib.sha256(token.encode()).hexdigest())):
        raise DomainError('guardian_claim_unavailable','A current one-time account authorization is required.',403)


@transaction.atomic
def claim_account(request,authorization_id):
    enabled()
    from .views import require_fresh
    from .password_consent import PASSWORD_PURPOSE_FIELDS,validate_password_purpose_consent
    from core.api import json_body
    from .services import register_member
    require_fresh(request)
    row=_own_locked(request,authorization_id)
    # This precedes application body parsing/persistence, not network intake.
    _claim_preflight(request,row)
    d=json_body(request,{'email','password','display_name','locale','return_path'}|PASSWORD_PURPOSE_FIELDS,['email','password','display_name'])
    consent=validate_password_purpose_consent(d)
    user=register_member(**{k:v for k,v in d.items() if k not in PASSWORD_PURPOSE_FIELDS},password_consent=consent,_return_created_user=True)
    if user is not None:
        user.guardian_managed=True;user.save(update_fields=['guardian_managed'])
    row.child=user;row.claimed_at=timezone.now();row.claim_sha256='';row.claim_expires_at=None;row.version+=1;row.save()
    audit(request.user,'guardian.account_claim_submitted',row)
    return {'status':'delivery_pending'}


EXPORT_SECTIONS={'profile','preferences','consents','progress','completion','annotations','saved_items','lists','list_items','devices','downloads','learning_completion','quiz_attempts','email_addresses','linked_identities'}


def _rights_policy(row):
    _current(row)
    policy,_=_public_policy(row.jurisdiction,row.purpose,row.notice_version,row.method)
    if row.status!='authorized' or not row.child_id:raise DomainError('guardian_authority_unavailable','An exact reviewed child authority is required.',403)
    if row.purpose=='privacy_access':
        sections=policy.get('allowed_export_sections')
        if not isinstance(sections,list) or not sections or any(not isinstance(v,str) or v not in EXPORT_SECTIONS for v in sections):
            raise DomainError('guardian_policy_unavailable','A qualified export scope is required.',409)
    elif row.purpose=='privacy_delete':
        if policy.get('allow_delete') is not True:raise DomainError('guardian_policy_unavailable','A qualified deletion scope is required.',409)
    else:raise DomainError('guardian_authority_unavailable','A separate rights authorization is required.',403)
    return policy


@transaction.atomic
def request_privacy(request,authorization_id,*,kind,confirm,operation_id):
    enabled()
    from .views import require_fresh,privacy_data
    from core.models import OutboxJob
    require_fresh(request);row=_own_locked(request,authorization_id);policy=_rights_policy(row)
    if confirm is not True or kind not in ('export','delete') or row.purpose!=('privacy_access' if kind=='export' else 'privacy_delete'):
        raise DomainError('validation_error','Confirm the exact authorized rights action.',422)
    def mutate():
        payload={'session_epoch':row.child.session_epoch,'guardian_authorization_id':str(row.pk),'guardian_requester_id':request.user.pk}
        if kind=='export':payload['guardian_export_sections']=policy['allowed_export_sections']
        job=OutboxJob.objects.create(kind='privacy_'+kind,actor=row.child,dedupe_key=f'guardian-privacy:{row.pk}:{operation_id}',payload=payload,not_before=timezone.now())
        audit(request.user,'guardian.privacy_requested',job,{'kind':kind,'authorization_id':str(row.pk)})
        return 202,privacy_data(job),1
    return apply_operation(request.user,operation_id,'guardian.privacy_request',{'authorization_id':str(row.pk),'kind':kind,'confirm':confirm},mutate)


def _job_authority(job):
    row=_row(job.payload['guardian_authorization_id'])
    ids=sorted({v for v in (row.child_id,row.guardian_id,row.reviewer_id) if v is not None})
    users=list(User.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
    row=GuardianAuthorization.objects.select_for_update().get(pk=row.pk)
    if len(users)!=len(ids) or any(not u.is_active for u in users):raise DomainError('guardian_authority_unavailable','Current account authority is required.',403)
    policy=_rights_policy(row)
    if (row.child_id!=job.actor_id or row.guardian_id!=job.payload.get('guardian_requester_id')
        or row.purpose!=('privacy_access' if job.kind=='privacy_export' else 'privacy_delete')):
        raise DomainError('guardian_authority_unavailable','The job does not match its reviewed authority.',403)
    if job.kind=='privacy_export' and job.payload.get('guardian_export_sections')!=policy['allowed_export_sections']:
        raise DomainError('guardian_authority_unavailable','The export scope changed.',403)
    return row


def process_privacy_job(job,max_seconds=45):
    # Revalidate at dispatch and inside privacy commit boundaries. Existing hold/financial,
    # deletion reconciliation, export expiry and private storage rules still run.
    if job.kind=='privacy_delete' and 'delete_export_keys' in job.payload:
        # Erasure already committed atomically with this cleanup marker. A
        # withdrawn/deleted authority must not strand its private export objects.
        if not User.objects.filter(pk=job.actor_id,is_active=False,email__endswith='@invalid.local').exists():
            raise DomainError('guardian_authority_unavailable','Deletion cleanup is not confirmed.',403)
        from library import storage
        for key in job.payload['delete_export_keys']:storage.delete_private(key)
        return {'status':'anonymised','retained_categories':job.payload.get('delete_retained_categories',['account_security_records'])}
    with transaction.atomic():_job_authority(job)
    from .privacy import create_export,delete_account
    return create_export(job,max_seconds=max_seconds) if job.kind=='privacy_export' else delete_account(job)


@transaction.atomic
def privacy_job(request,authorization_id,job_id):
    enabled()
    from core.models import OutboxJob
    row=_own_row(request,authorization_id)
    _locks(request,None,row.guardian_id)
    job=OutboxJob.objects.filter(pk=public_uuid(job_id),actor_id=row.child_id,kind__in=['privacy_export','privacy_delete'],payload__guardian_authorization_id=str(row.pk)).first()
    if not job:raise DomainError('not_found','Request not found.',404)
    if job.kind=='privacy_delete' and job.status=='done' and job.result.get('status') in ('anonymised','anonymised_financial_records_retained','already_removed'):
        return job  # Minimal completion status only; no export or child data.
    _job_authority(job)
    return job


def account_available(user):
    if not getattr(user,'guardian_managed',False):return True
    if not getattr(settings,'GUARDIAN_AUTHORIZATION_ENABLED',False):return False
    for row in GuardianAuthorization.objects.filter(child=user,purpose='account_processing',status='authorized',expires_at__gt=timezone.now()):
        try:
            _current(row);_public_policy(row.jurisdiction,row.purpose,row.notice_version,row.method)
            if User.objects.filter(pk=row.guardian_id,is_active=True,is_verified=True).exists():return True
        except DomainError:continue
    return False


def _revoke_child_sessions(child_id):
    from django.contrib.sessions.models import Session
    from django.db.models import F
    from .models import Device
    from reader.models import DownloadLicense
    now=timezone.now()
    User.objects.filter(pk=child_id).update(session_epoch=F('session_epoch')+1)
    devices=Device.objects.filter(user_id=child_id)
    Session.objects.filter(session_key__in=devices.exclude(session_id=None).values_list('session_id',flat=True)).delete()
    devices.filter(revoked_at=None).update(revoked_at=now,version=F('version')+1)
    DownloadLicense.objects.filter(user_id=child_id,revoked_at=None).update(revoked_at=now)
