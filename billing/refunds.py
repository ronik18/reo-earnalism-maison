"""Approved mode-bound refunds with durable, non-repeating uncertain mutations."""
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from core.api import DomainError
from core.models import OutboxJob
from .models import Order,Payment,Refund,Entitlement,PaymentAllocation
from .checkout import qualified_mode
from .razorpay import RazorpayClient,provider_id


def _locked(refund_id):
    initial=Refund.objects.select_related('payment').get(pk=refund_id)
    order=Order.objects.select_for_update().get(pk=initial.payment.order_id)
    payment=Payment.objects.select_for_update().get(pk=initial.payment_id)
    return order,payment,Refund.objects.select_for_update().get(pk=refund_id)


def process_refund_job(job):
    refund_id=job.payload.get('refund_id')
    if not refund_id:
        raise DomainError('refund_review_required','A reviewed bounded refund proposal is required.',409)
    mode,_,_=qualified_mode()
    with transaction.atomic():
        order,payment,row=_locked(refund_id)
        if payment.provider!='razorpay' or payment.verification_source!='razorpay_api_'+mode or order.test_only!=(mode=='test'):
            raise DomainError('provider_not_enabled','Refund transport is qualified only for verified payments in the configured merchant mode.',409)
        if row.status in ['processed','failed','rejected']:
            return {'refund_id':str(row.id),'status':row.status}
        if row.status not in ['approved','submitted','pending'] or not row.approved_by_id or not row.approved_at or not row.amount_minor:
            raise DomainError('refund_review_required','An approved bounded refund is required.',409)
        current=OutboxJob.objects.select_for_update().get(pk=job.pk)
        attempted=bool(current.payload.get('provider_refund_create_attempted'))
        provider_refund_id=row.provider_refund_id
        # Persist before network I/O. A crash may require operator resolution, never
        # a blind second refund POST after an ambiguous result.
        if not attempted and not provider_refund_id:
            current.payload={**current.payload,'provider_refund_create_attempted':True}
            current.save(update_fields=['payload'])
    client=RazorpayClient()
    if provider_refund_id:
        facts=client.fetch_refund(provider_refund_id)
    elif attempted:
        facts=client.find_refund(row)
        if facts is None:raise DomainError('awaiting_resolution','Refund submission outcome requires reconciliation.',409)
    else:
        facts=client.create_refund(row)
    identity=provider_id(facts.get('id'),'rfnd')
    notes=facts.get('notes')
    if (facts.get('payment_id')!=payment.provider_payment_id or type(facts.get('amount')) is not int or facts['amount']!=row.amount_minor or facts.get('currency')!=row.currency or facts.get('receipt')!=str(row.id) or not isinstance(notes,dict) or notes.get('maison_refund_id')!=str(row.id) or (provider_refund_id and identity!=provider_refund_id)):
        raise DomainError('awaiting_resolution','Refund provider identity or amount does not match the approved proposal.',409)
    state=facts.get('status')
    if state not in ['pending','processed','failed']:
        raise DomainError('awaiting_resolution','Refund provider status is not recognized.',409)
    with transaction.atomic():
        order,payment,row=_locked(refund_id)
        if row.provider_refund_id and row.provider_refund_id!=identity:
            raise DomainError('awaiting_resolution','Refund identity changed.',409)
        if row.status=='processed':return {'refund_id':str(row.id),'status':row.status}
        if row.status not in ['approved','submitted','pending']:
            raise DomainError('awaiting_resolution','Refund state changed during reconciliation.',409)
        row.provider_refund_id=identity;row.status=state;row.version+=1
        if state=='processed':row.processed_at=timezone.now()
        row.save()
        if state=='processed':
            total=payment.refunds.filter(status='processed').aggregate(n=Sum('amount_minor'))['n'] or 0
            payment.status='refunded' if total==payment.amount_minor else 'partially_refunded';payment.version+=1;payment.save()
            if total==payment.amount_minor and PaymentAllocation.objects.filter(payment=payment,invoice__order=order).exists():
                Entitlement.objects.filter(order=order,revoked_at=None).update(revoked_at=timezone.now())
                order.fulfillment_status='refunded';order.version+=1;order.save()
    if state=='pending':raise DomainError('refund_pending','Provider refund processing is pending.',503)
    return {'refund_id':str(row.id),'status':state}
