"""Server-only operational foundation. No public collection or legal VPC claim.

No route calls these services. Exact national methods, collection timing, capacity,
retention and regional placement must be qualified before any public integration.
An evidence digest is an audit binding, never verification of the evidence itself.

SOURCE-ONLY ACCEPTANCE: do not deploy this model code against a database without
accounts migration 0004. Even while disabled, Django deletion collection traverses
User reverse relations and can query this table. Production migration is not
authorized; keep this foundation in the review branch, not the running service.
"""
import hashlib
import json
import re
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
    ids=sorted({request.user.pk,child_id,guardian_id})
    users={u.pk:u for u in User.objects.select_for_update().filter(pk__in=ids).order_by('pk')}
    actor=locked_actor(request.user)
    if not getattr(request.user,'_maison_operation_authority',None):
        raise DomainError('authentication_required','A current bound session is required.',401)
    if len(users)!=len(ids) or any(not u.is_active or not u.is_verified for u in users.values()):
        raise DomainError('guardian_authority_unavailable','Active verified accounts are required.',403)
    if review:
        from .mfa import verified_device
        if (actor.pk in (child_id,guardian_id) or not actor.is_staff
            or not actor.has_perm('accounts.review_guardian_authorization') or not verified_device(request)):
            raise DomainError('permission_denied','Independent authorized staff MFA review is required.',403)
    return actor


def _current(row):
    _,digest=_policy(row.jurisdiction,row.purpose,row.notice_version,row.method)
    if not row.reviewer_id or not User.objects.filter(pk=row.reviewer_id,is_active=True).exists():
        raise DomainError('guardian_authority_unavailable','Review authority is unavailable.',403)
    if digest!=row.policy_sha256 or row.status in ('withdrawn','rejected') or row.expires_at<=timezone.now():
        raise DomainError('guardian_authority_unavailable','Authority is expired, withdrawn or superseded.',403)


def _data(row):
    return {'authorization_id':str(row.pk),'status':row.status,'purpose':row.purpose,
        'notice_version':row.notice_version,'jurisdiction':row.jurisdiction,'version':row.version,
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


@transaction.atomic
def review(request,authorization_id,*,evidence_sha256,approve,expected_version,operation_id):
    row=_row(authorization_id)
    _locks(request,row.child_id,row.guardian_id,review=True)
    row=GuardianAuthorization.objects.select_for_update().get(pk=row.pk);_current(row)
    if row.reviewer_id!=request.user.pk:raise DomainError('permission_denied','The assigned reviewer is required.',403)
    if type(approve) is not bool or not isinstance(evidence_sha256,str) or not re.fullmatch('[0-9a-f]{64}',evidence_sha256):
        raise DomainError('validation_error','An exact private evidence digest and decision are required.',422)
    payload={'authorization_id':str(row.pk),'evidence_sha256':evidence_sha256,'approve':approve,'expected_version':expected_version}
    def mutate():
        if row.version!=expected_version:raise DomainError('version_conflict','Authorization changed.',412)
        if row.status!='pending':raise DomainError('guardian_authority_unavailable','Review already completed.',409)
        row.status='authorized' if approve else 'rejected';row.evidence_sha256=evidence_sha256;row.reviewed_at=timezone.now();row.version+=1;row.save()
        audit(request.user,'guardian.reviewed',row,{'outcome':row.status})
        return 200,_data(row),row.version
    return apply_operation(request.user,operation_id,'guardian.review',payload,mutate)


@transaction.atomic
def withdraw(request,authorization_id,*,expected_version,operation_id):
    row=_row(authorization_id);actor=_locks(request,row.child_id,row.guardian_id)
    if actor.pk!=row.guardian_id:raise DomainError('permission_denied','The bound guardian is required.',403)
    row=GuardianAuthorization.objects.select_for_update().get(pk=row.pk)
    def mutate():
        if row.version!=expected_version:raise DomainError('version_conflict','Authorization changed.',412)
        row.status='withdrawn';row.withdrawn_at=timezone.now();row.version+=1;row.save()
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
