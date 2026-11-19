"""Existing cycle-end cancellation only; no subscription signup or charges."""
from django.db import transaction
from core.api import DomainError
from core.models import OutboxJob
from .subscription_models import Subscription,Mandate
from .checkout import qualified_mode
from .razorpay import RazorpayClient,provider_id


def process_subscription_job(job):
    if job.payload.get('action')=='mandate.revoke':
        raise DomainError('provider_token_identity_missing','A verified provider customer/token association is required for mandate revocation.',409)
    if job.payload.get('action')!='subscription.cancel':
        raise DomainError('provider_not_qualified','Unsupported existing-agreement operation.',409)
    mode,_,_=qualified_mode()
    if job.payload.get('provider_mode') not in ['test','live'] or job.payload['provider_mode']!=mode:
        raise DomainError('provider_not_qualified','Queued agreement mode does not match the configured merchant mode.',409)
    with transaction.atomic():
        sub=Subscription.objects.select_for_update().select_related('plan__offer').get(pk=job.payload['resource_id'])
        if sub.user_id!=job.actor_id or not sub.cancel_at_period_end:
            raise DomainError('awaiting_resolution','Cancellation intent does not match the owned agreement.',409)
        if sub.provider!='razorpay' or not sub.provider_subscription_id or sub.plan.offer.test_only!=(mode=='test'):
            raise DomainError('provider_not_qualified','Agreement is not bound to the configured merchant mode.',409)
        if job.payload.get('provider')!=sub.provider or job.payload.get('provider_resource_id')!=sub.provider_subscription_id:
            raise DomainError('provider_not_qualified','Queued provider agreement identity is missing or changed.',409)
        identity=provider_id(sub.provider_subscription_id,'sub')
        current=OutboxJob.objects.select_for_update().get(pk=job.pk)
        if current.payload.get('provider_cancel_accepted'):
            return {'subscription_id':str(sub.pk),'status':sub.status,'cycle_end_request_accepted':True,'provider_status':sub.provider_status}
        attempted=bool(current.payload.get('provider_cancel_attempted'))
    client=RazorpayClient()
    facts=client.fetch_subscription(identity)
    def validate(value):
        if not isinstance(value,dict) or value.get('id')!=identity or (sub.plan.provider_plan_id and value.get('plan_id')!=sub.plan.provider_plan_id):
            raise DomainError('awaiting_resolution','Provider subscription identity does not match the owned agreement.',409)
        if value.get('status') not in ['created','authenticated','active','pending','halted','paused','cancelled','completed','expired']:
            raise DomainError('awaiting_resolution','Provider subscription state is not recognized.',409)
    validate(facts)
    terminal=facts['status'] in ['cancelled','completed','expired']
    accepted=False
    if not terminal:
        if attempted:
            # Active status cannot prove a prior cycle-end request was accepted.
            raise DomainError('awaiting_resolution','Cancellation submission outcome remains unknown; no repeated POST is allowed.',409)
        with transaction.atomic():
            current=OutboxJob.objects.select_for_update().get(pk=job.pk)
            if current.payload.get('provider_cancel_attempted'):
                raise DomainError('awaiting_resolution','Cancellation submission already attempted.',409)
            current.payload={**current.payload,'provider_cancel_attempted':True};current.save(update_fields=['payload'])
        facts=client.cancel_subscription(identity);validate(facts);accepted=True
    with transaction.atomic():
        row=Subscription.objects.select_for_update().get(pk=sub.pk)
        if row.mandate_id:Mandate.objects.select_for_update().get(pk=row.mandate_id)
        if row.provider_subscription_id!=identity or row.user_id!=job.actor_id:
            raise DomainError('awaiting_resolution','Subscription ownership or provider identity changed.',409)
        # Never modify earned periods, entitlements, or mandate authority here.
        row.provider_status=facts['status']
        if facts['status'] in ['cancelled','completed','expired']:
            row.status=facts['status'];row.next_charge_at=None
        row.version+=1;row.save(update_fields=['provider_status','status','next_charge_at','version'])
        if accepted:
            current=OutboxJob.objects.select_for_update().get(pk=job.pk)
            current.payload={**current.payload,'provider_cancel_accepted':True};current.save(update_fields=['payload'])
    return {'subscription_id':str(row.pk),'status':row.status,'cycle_end_request_accepted':accepted,'provider_status':facts['status']}
