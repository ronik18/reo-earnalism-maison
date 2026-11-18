"""Existing agreement management: durable intent never pretends provider confirmation."""
from django.utils import timezone
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
    # No qualified recurring transport exists. Keep an explicit blocked durable intent
    # rather than invoke a fake adapter or allow a generic worker to claim delivery.
    OutboxJob.objects.get_or_create(dedupe_key=f'{action}:{row.pk}',defaults={'kind':'subscription_reconcile','actor':user,'payload':{'action':action,'resource_id':str(row.pk)},'not_before':timezone.now(),'status':'blocked','error_code':'provider_not_qualified'})

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
