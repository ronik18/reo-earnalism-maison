"""Existing agreement management: durable intent never pretends provider confirmation."""
from django.utils import timezone
from django.conf import settings
from core.api import json_endpoint,api_response,DomainError,operation_key,expected_version,json_body
from core.services import apply_operation,audit
from core.models import OutboxJob
from accounts.views import require_fresh
from library.validation import body
from .subscription_models import Subscription,Mandate


def iso(value):return value.isoformat().replace('+00:00','Z') if value else None

def subscription_data(row):
    return {'subscription_id':str(row.id),'plan_id':str(row.plan_id),'status':row.status,'provider_status':row.provider_status,'cancel_at_period_end':row.cancel_at_period_end,'current_period_start':iso(row.current_period_start),'current_period_end':iso(row.current_period_end),'paid_through':iso(row.paid_through),'next_charge_at':iso(row.next_charge_at),'mandate_id':str(row.mandate_id) if row.mandate_id else None,'version':row.version,'checkout':None}

def mandate_data(row):
    return {'mandate_id':str(row.id),'subscription_id':str(row.subscription.id),'status':row.status,'revocation_pending':row.revocation_pending,'method':row.method,'created_at':iso(row.created_at),'revoked_at':iso(row.revoked_at),'version':row.version}

def own_subscription(user,subscription_id,lock=False):
    query=Subscription.objects.select_for_update() if lock else Subscription.objects
    row=query.filter(pk=subscription_id,user=user).first()
    if not row:raise DomainError('not_found','Subscription not found.',404)
    return row

def queue_intent(user,row,action):
    status='blocked';error='provider_token_identity_missing' if action=='mandate.revoke' else 'provider_not_qualified'
    if action in ['subscription.cancel','mandate.revoke']:
        try:
            from .checkout import qualified_mode
            mode,_,_=qualified_mode()
            if action=='subscription.cancel' and row.provider=='razorpay' and row.provider_subscription_id and row.plan.offer.test_only==(mode=='test'):
                status='pending';error=''
            if action=='mandate.revoke' and row.provider=='razorpay' and row.identity_verified_at and row.provider_mode==mode and row.provider_customer_id and row.provider_token_id:
                status='pending';error=''
        except DomainError:pass
    job,created=OutboxJob.objects.get_or_create(dedupe_key=f'{action}:{row.pk}',defaults={'kind':'subscription_reconcile','actor':user,'payload':{'action':action,'resource_id':str(row.pk),'provider_mode':getattr(settings,'RAZORPAY_MODE','test'),'provider':row.provider,'provider_resource_id':row.provider_subscription_id if action=='subscription.cancel' else row.provider_mandate_id},'not_before':timezone.now(),'status':status,'error_code':error})
    if not created and action=='mandate.revoke' and status=='pending' and job.status=='blocked' and job.error_code=='provider_token_identity_missing' and not job.payload.get('provider_revoke_attempted'):
        job.status='pending';job.error_code='';job.not_before=timezone.now();job.save(update_fields=['status','error_code','not_before'])
    return job

def cancel_existing(user,subscription_id,data,base,key):
    if data.get('at_period_end') is not True:
        raise DomainError('validation_error','Cancellation must preserve the paid period.',422)
    def execute():
        row=own_subscription(user,subscription_id,True)
        if row.mandate_id:
            mandate=Mandate.objects.select_for_update().filter(pk=row.mandate_id,user=user).first()
            if not mandate:raise DomainError('not_found','Mandate not found.',404)
        if row.version!=base:raise DomainError('version_conflict','Subscription changed.',412,subscription_data(row))
        if row.status not in ['cancelled','completed','expired'] and not row.cancel_at_period_end:
            row.cancel_at_period_end=True;row.cancellation_requested_at=timezone.now();row.version+=1
            row.save(update_fields=['cancel_at_period_end','cancellation_requested_at','version'])
            queue_intent(user,row,'subscription.cancel')
            audit(user,'subscription.cancel_requested',row,{'at_period_end':True})
        if row.cancel_at_period_end and row.status not in ['cancelled','completed','expired']:queue_intent(user,row,'subscription.cancel')
        return 200,subscription_data(row),row.version
    return apply_operation(user,key,'subscription.cancel',{'subscription_id':str(subscription_id),'version':base,**data},execute)

def revoke_existing(user,mandate_id,key):
    def execute():
        # Discover the owned relationship without locking, then use the same
        # Subscription -> Mandate order as cancellation and its DB guard.
        subscription_id=Subscription.objects.filter(mandate_id=mandate_id,user=user,mandate__user=user).values_list('pk',flat=True).first()
        if not subscription_id:raise DomainError('not_found','Mandate not found.',404)
        sub=Subscription.objects.select_for_update().filter(pk=subscription_id,user=user,mandate_id=mandate_id).first()
        if not sub:raise DomainError('not_found','Mandate not found.',404)
        row=Mandate.objects.select_for_update().filter(pk=mandate_id,user=user).first()
        if not row:raise DomainError('not_found','Mandate not found.',404)
        if row.status not in ['cancelled','expired','failed'] and not row.revocation_pending:
            row.revocation_pending=True;row.version+=1;row.save(update_fields=['revocation_pending','version'])
            if not sub.cancel_at_period_end:
                sub.cancel_at_period_end=True;sub.cancellation_requested_at=timezone.now();sub.version+=1
                sub.save(update_fields=['cancel_at_period_end','cancellation_requested_at','version'])
            queue_intent(user,sub,'subscription.cancel')
            queue_intent(user,row,'mandate.revoke')
            audit(user,'mandate.revoke_requested',row)
        return 200,mandate_data(row),row.version
    return apply_operation(user,key,'mandate.revoke',{'mandate_id':str(mandate_id)},execute)

@json_endpoint(('GET','POST'))
def subscriptions(request):
    if request.method=='POST':raise DomainError('feature_disabled','New recurring agreements require separately qualified provider activation.',409)
    from core.pagination import paginate_queryset
    data=paginate_queryset(request,Subscription.objects.filter(user=request.user),'subscriptions')
    data['items']=[subscription_data(row) for row in data['items']]
    return api_response(data)

@json_endpoint(('GET',))
def subscription(request,subscription_id):
    row=own_subscription(request.user,subscription_id)
    return api_response(subscription_data(row),version=row.version)

@json_endpoint(('POST',))
def cancel(request,subscription_id):
    require_fresh(request)
    status,result=cancel_existing(request.user,subscription_id,body(request,'CancelSubscriptionInput'),expected_version(request),operation_key(request))
    return api_response(result,status,version=result['version'])

@json_endpoint(('GET',))
def mandates(request):
    from core.pagination import paginate_queryset
    data=paginate_queryset(request,Mandate.objects.filter(user=request.user,subscription__user=request.user).select_related('subscription'),'mandates')
    data['items']=[mandate_data(row) for row in data['items']]
    return api_response(data)

@json_endpoint(('DELETE',))
def revoke(request,mandate_id):
    require_fresh(request)
    if request.body:json_body(request,set())
    status,result=revoke_existing(request.user,mandate_id,operation_key(request))
    return api_response(result,status,version=result['version'])

@json_endpoint(('POST',))
def verify(request,subscription_id):
    own_subscription(request.user,subscription_id)
    raise DomainError('feature_disabled','Subscription provider verification is not qualified.',409)


def mandate_identity_data(row):
    job=OutboxJob.objects.filter(pk=row.identity_verification_job_id).first() if row.identity_verification_job_id else None
    return {'mandate_id':str(row.pk),'version':row.version,'verified':bool(row.identity_verified_at),
        'provider_customer_id':row.provider_customer_id or None,'provider_token_id':row.provider_token_id or None,
        'provider_payment_id':row.provider_payment_id or None,'provider_invoice_id':row.provider_invoice_id or None,
        'provider_mode':row.provider_mode or None,'identity_verified_at':iso(row.identity_verified_at),
        'evidence_ref':row.identity_evidence_ref or None,'pending_job_id':str(job.pk) if job else None,'pending':bool(job and job.status in ['pending','claimed'])}


def request_mandate_identity(actor,mandate_id,data,base,key):
    from .razorpay import provider_id
    from .checkout import qualified_mode
    from django.db import transaction
    from core.api import public_uuid
    if not actor.is_active or not actor.is_staff or not actor.has_perm('billing.change_mandate'):
        raise DomainError('permission_denied','Mandate administration permission is required.',403)
    for field,prefix in [('provider_customer_id','cust'),('provider_token_id','token'),('provider_payment_id','pay')]:provider_id(data.get(field),prefix)
    import re
    if not isinstance(data.get('evidence_ref'),str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:-]{0,159}',data['evidence_ref']):
        raise DomainError('validation_error','Use a bounded private evidence reference.',422)
    mode,_,_=qualified_mode()
    def execute():
        sub=Subscription.objects.select_for_update().select_related('plan__offer').filter(mandate_id=public_uuid(mandate_id)).first()
        if not sub:raise DomainError('not_found','Owned subscription association is required.',404)
        row=Mandate.objects.select_for_update().get(pk=sub.mandate_id)
        if row.version!=base:raise DomainError('version_conflict','Mandate identity changed.',412,mandate_identity_data(row))
        if row.provider!='razorpay' or sub.provider!='razorpay' or sub.plan.offer.test_only!=(mode=='test') or not sub.provider_subscription_id:
            raise DomainError('provider_not_qualified','The existing agreement must match the configured provider mode.',409)
        if row.identity_verified_at:
            if (row.provider_customer_id,row.provider_token_id,row.provider_payment_id,row.provider_mode)!=(data['provider_customer_id'],data['provider_token_id'],data['provider_payment_id'],mode):
                raise DomainError('provider_identity_immutable','A verified mandate identity cannot be reassigned.',409)
            return 202,mandate_identity_data(row),row.version
        job=OutboxJob.objects.create(kind='subscription_reconcile',actor=actor,dedupe_key=f'mandate.bind:{row.pk}:{key}',not_before=timezone.now(),payload={
            'action':'mandate.bind','resource_id':str(row.pk),'subscription_id':str(sub.pk),'member_id':str(row.user.public_id),
            'provider_subscription_id':sub.provider_subscription_id,'provider_mode':mode,**data})
        row.identity_verification_job_id=job.pk;row.version+=1;row.save(update_fields=['identity_verification_job_id','version'])
        audit(actor,'mandate.identity_verification_requested',row,{'job_id':str(job.pk),'evidence_ref':data['evidence_ref']})
        return 202,mandate_identity_data(row),row.version
    return apply_operation(actor,key,'mandate.identity_intake',{'mandate_id':str(mandate_id),'version':base,**data},execute)


@json_endpoint(('GET','POST'))
def provider_identity(request,mandate_id):
    require_fresh(request)
    if not request.user.is_staff or not request.user.has_perm('billing.change_mandate'):
        raise DomainError('permission_denied','Mandate administration permission is required.',403)
    if getattr(settings,'STAFF_MFA_REQUIRED',not settings.LOCAL) and not getattr(request.user,'staff_mfa_verified',False):
        raise DomainError('mfa_required','Verify staff MFA before viewing provider identities.',403)
    if request.method=='GET':
        row=Mandate.objects.filter(pk=mandate_id).first()
        if not row:raise DomainError('not_found','Mandate not found.',404)
        return api_response(mandate_identity_data(row),version=row.version)
    status,result=request_mandate_identity(request.user,mandate_id,body(request,'MandateProviderIdentityInput'),expected_version(request),operation_key(request))
    return api_response(result,status,version=result['version'])
