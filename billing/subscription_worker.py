"""Existing cycle-end cancellation only; no subscription signup or charges."""
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from core.api import DomainError
from core.models import OutboxJob
from .subscription_models import Subscription,Mandate
from .checkout import qualified_mode
from .razorpay import RazorpayClient,provider_id


def process_subscription_job(job):
    if job.payload.get('action')=='mandate.bind':return bind_identity(job)
    if job.payload.get('action')=='mandate.revoke':return revoke_token(job)
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
        previously_accepted=bool(current.payload.get('provider_cancel_accepted'))
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
    accepted=previously_accepted
    if not terminal and not accepted:
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
        if row.provider_status!=sub.provider_status or row.status!=sub.status or row.next_charge_at!=sub.next_charge_at:
            row.version+=1;row.save(update_fields=['provider_status','status','next_charge_at','version'])
        if accepted:
            current=OutboxJob.objects.select_for_update().get(pk=job.pk)
            current.payload={**current.payload,'provider_cancel_accepted':True};current.save(update_fields=['payload'])
    result={'subscription_id':str(row.pk),'status':row.status,'cycle_end_request_accepted':accepted,'provider_status':facts['status']}
    if facts['status'] not in ['cancelled','completed','expired']:
        result.update(awaiting_provider_confirmation=True,confirmation_poll_seconds=300)
        if row.current_period_end and row.current_period_end>timezone.now():result['confirmation_not_before']=(row.current_period_end+timedelta(seconds=60)).isoformat()
    return result


def reject(message):raise DomainError('awaiting_resolution',message,409)


def bound_rows(job,mode,staff=False,allow_revoked=False):
    sub=Subscription.objects.select_for_update().select_related('plan__offer').get(mandate_id=job.payload['resource_id'])
    row=Mandate.objects.select_for_update().get(pk=sub.mandate_id)
    if row.user_id!=sub.user_id or sub.provider!='razorpay' or row.provider!='razorpay' or sub.plan.offer.test_only!=(mode=='test') or job.payload.get('provider_mode')!=mode:
        reject('Agreement ownership or provider mode does not match.')
    if staff:
        from django.contrib.auth import get_user_model
        actor=get_user_model().objects.get(pk=job.actor_id)
        if not actor.is_active or not actor.is_staff or not actor.has_perm('billing.change_mandate'):reject('Staff authority is no longer valid.')
        if row.identity_verification_job_id!=job.pk or str(sub.pk)!=job.payload.get('subscription_id') or sub.provider_subscription_id!=job.payload.get('provider_subscription_id'):reject('Verification was superseded or agreement changed.')
    elif row.user_id!=job.actor_id or (not row.revocation_pending and not (allow_revoked and row.status=='cancelled' and row.revoked_at)):reject('Owned revocation intent is missing.')
    return sub,row


def bind_identity(job):
    mode,_,_=qualified_mode()
    with transaction.atomic():
        sub,row=bound_rows(job,mode,staff=True)
        if row.identity_verified_at:return {'mandate_id':str(row.pk),'verified':True}
        method=row.method;currency=row.currency;plan=sub.plan.provider_plan_id
    p=job.payload;client=RazorpayClient()
    agreement=client.fetch_subscription(p['provider_subscription_id'])
    payment=client.fetch_payment(p['provider_payment_id'])
    invoice_id=provider_id(payment.get('invoice_id'),'inv')
    invoice=client.fetch_invoice(invoice_id)
    token=client.fetch_customer_token(p['provider_customer_id'],p['provider_token_id'])
    if (agreement.get('id')!=p['provider_subscription_id'] or agreement.get('customer_id')!=p['provider_customer_id'] or (plan and agreement.get('plan_id')!=plan)
        or payment.get('id')!=p['provider_payment_id'] or payment.get('customer_id')!=p['provider_customer_id'] or payment.get('token_id')!=p['provider_token_id'] or payment.get('status')!='captured'
        or payment.get('currency')!=currency or payment.get('method')!=method
        or invoice.get('id')!=invoice_id or invoice.get('subscription_id')!=p['provider_subscription_id'] or invoice.get('payment_id')!=p['provider_payment_id']
        or (invoice.get('customer_id') and invoice['customer_id']!=p['provider_customer_id'])
        or token.get('id')!=p['provider_token_id'] or token.get('method')!=method or token.get('recurring') is not True
        or not isinstance(token.get('recurring_details'),dict) or token['recurring_details'].get('status') not in ['confirmed','paused','cancellation_initiated','cancelled']):
        reject('Provider payment, invoice, agreement and token do not establish the exact owned identity.')
    from django.utils import timezone
    from .subscriptions import queue_intent
    with transaction.atomic():
        sub,row=bound_rows(job,mode,staff=True)
        if row.identity_verified_at:return {'mandate_id':str(row.pk),'verified':True}
        if row.method!=method or row.currency!=currency or sub.plan.provider_plan_id!=plan:reject('Agreement terms changed during verification.')
        row.provider_customer_id=p['provider_customer_id'];row.provider_token_id=p['provider_token_id'];row.provider_payment_id=p['provider_payment_id']
        row.provider_invoice_id=invoice_id;row.provider_mode=mode;row.identity_verified_at=timezone.now();row.identity_verified_by_id=job.actor_id;row.identity_evidence_ref=p['evidence_ref'];row.version+=1
        row.save()
        if row.revocation_pending:queue_intent(row.user,row,'mandate.revoke')
    return {'mandate_id':str(row.pk),'verified':True}


def finish_revocation(row):
    from django.utils import timezone
    row.status='cancelled';row.provider_status='cancelled';row.revoked_at=row.revoked_at or timezone.now();row.revocation_pending=False;row.version+=1
    row.save(update_fields=['status','provider_status','revoked_at','revocation_pending','version'])


def revoke_token(job):
    mode,_,_=qualified_mode()
    with transaction.atomic():
        # Confirmed retries are terminal even after the intent flag is cleared.
        existing=Mandate.objects.filter(pk=job.payload['resource_id'],user_id=job.actor_id).first()
        if existing and existing.status=='cancelled' and existing.revoked_at:return {'mandate_id':str(existing.pk),'revoked':True}
        sub,row=bound_rows(job,mode)
        if not row.identity_verified_at or row.provider_mode!=mode:raise DomainError('provider_token_identity_missing','Verified provider token identity is required.',409)
        identity=(row.provider_customer_id,row.provider_token_id,row.method)
        current=OutboxJob.objects.select_for_update().get(pk=job.pk);attempted=bool(current.payload.get('provider_revoke_attempted'));accepted=bool(current.payload.get('provider_revoke_accepted'))
    client=RazorpayClient()
    try:token=client.fetch_customer_token(identity[0],identity[1])
    except DomainError as error:
        if getattr(error,'provider_http_status',None)==404 and accepted and identity[2] in ['upi','emandate']:
            return {'mandate_id':str(row.pk),'revoked':False,'awaiting_provider_confirmation':True,'confirmation_poll_seconds':300,'provider_token_unavailable':True}
        raise
    if token.get('id')!=identity[1] or token.get('method')!=identity[2] or token.get('recurring') is not True:reject('Provider token identity changed.')
    details=token.get('recurring_details')
    if not isinstance(details,dict):reject('Provider recurring token status is missing.')
    state=details.get('status')
    confirmed=state=='cancelled'
    if not confirmed and state=='cancellation_initiated':
        accepted=True
    elif not confirmed:
        if attempted:
            if accepted:return {'mandate_id':str(row.pk),'revoked':False,'awaiting_provider_confirmation':True,'confirmation_poll_seconds':300}
            reject('Prior revocation outcome remains unknown; do not repeat the mutation.')
        if state not in ['confirmed','paused']:reject('Provider mandate is not eligible for cancellation.')
        with transaction.atomic():
            sub,row=bound_rows(job,mode)
            if (row.provider_customer_id,row.provider_token_id,row.method)!=identity:reject('Verified identity changed.')
            current=OutboxJob.objects.select_for_update().get(pk=job.pk)
            if current.payload.get('provider_revoke_attempted'):reject('Revocation already attempted.')
            current.payload={**current.payload,'provider_revoke_attempted':True};current.save(update_fields=['payload'])
        if identity[2]=='upi':
            result=client.cancel_customer_token(identity[0],identity[1])
            if result.get('status')!='cancellation_initiated':reject('UPI cancellation acknowledgment is invalid.')
        elif identity[2] in ['card','emandate']:
            result=client.delete_customer_token(identity[0],identity[1])
            if result.get('deleted') is not True:reject('Token deletion acknowledgment is invalid.')
            # Razorpay documents card token deletion as mandate cancellation;
            # eMandate must instead await NPCI token.cancelled acknowledgment.
            confirmed=identity[2]=='card'
        else:reject('Mandate method does not support this provider operation.')
        accepted=True
    with transaction.atomic():
        sub,row=bound_rows(job,mode,allow_revoked=True)
        if row.status=='cancelled' and row.revoked_at:return {'mandate_id':str(row.pk),'revoked':True}
        if (row.provider_customer_id,row.provider_token_id,row.method)!=identity:reject('Verified identity changed.')
        if confirmed:finish_revocation(row)
        else:
            if row.provider_status!='cancellation_initiated':
                row.provider_status='cancellation_initiated';row.version+=1;row.save(update_fields=['provider_status','version'])
            if accepted:
                current=OutboxJob.objects.select_for_update().get(pk=job.pk)
                current.payload={**current.payload,'provider_revoke_attempted':True,'provider_revoke_accepted':True};current.save(update_fields=['payload'])
    return {'mandate_id':str(row.pk),'revoked':confirmed,'awaiting_provider_confirmation':not confirmed,'confirmation_poll_seconds':300}


def process_token_cancelled_event(event,payload):
    mode,_,_=qualified_mode()
    if payload.get('provider_mode')!=mode or payload.get('event_name')!='token.cancelled' or payload.get('body_sha256',payload.get('body_sha'))!=event.body_sha256:
        reject('Cancellation event binding is invalid.')
    customer=provider_id(payload.get('provider_customer_id'),'cust');token=provider_id(payload.get('provider_token_id'),'token')
    identity=Mandate.objects.filter(provider='razorpay',provider_mode=mode,provider_customer_id=customer,provider_token_id=token,identity_verified_at__isnull=False).values_list('pk',flat=True).first()
    if not identity:reject('Cancellation event has no verified mandate identity.')
    from .models import PaymentEvent
    with transaction.atomic():
        sub=Subscription.objects.select_for_update().get(mandate_id=identity)
        row=Mandate.objects.select_for_update().get(pk=identity)
        locked=PaymentEvent.objects.select_for_update().get(pk=event.pk)
        if locked.provider!='razorpay' or locked.body_sha256!=event.body_sha256 or sub.user_id!=row.user_id or sub.plan.offer.test_only!=(mode=='test'):reject('Cancellation event owner or merchant mode changed.')
        if locked.status!='applied':
            finish_revocation(row);locked.status='applied';locked.save(update_fields=['status'])
    return {'received':True,'mandate_id':str(row.pk),'revoked':True}
