"""Durable authenticated webhook receipts; no raw provider payload retention."""
from django.db import transaction
from django.conf import settings
from django.utils import timezone
from core.api import DomainError
from core.models import OutboxJob
from .models import PaymentEvent
from .razorpay import provider_id


@transaction.atomic
def receive_event(data,event_id,body_sha256):
    if not isinstance(data,dict):raise DomainError('invalid_webhook','An event object is required.',400)
    event,_=PaymentEvent.objects.get_or_create(provider='razorpay',provider_event_id=event_id,defaults={'body_sha256':body_sha256,'status':'received'})
    event=PaymentEvent.objects.select_for_update().get(pk=event.pk)
    if event.body_sha256!=body_sha256:raise DomainError('event_payload_mismatch','An event ID was reused with different content.',409)
    if event.status=='applied':return {'received':True}
    name=data.get('event');name=name if isinstance(name,str) and len(name)<=80 else 'unknown'
    payload={'event_id':str(event.id),'body_sha256':body_sha256,'event_name':name}
    error='event_not_supported'
    if name in {'payment.captured','order.paid'}:
        try:
            payment=data['payload']['payment']['entity']
            payload.update(payment_id=provider_id(payment['id'],'pay'),provider_order_id=provider_id(payment['order_id'],'order'))
            error=''
        except (KeyError,TypeError,DomainError):error='event_incomplete'
    if name=='token.cancelled':
        try:
            token=data['payload']['token']['entity']
            payload.update(provider_token_id=provider_id(token['id'],'token'),provider_customer_id=provider_id(token['customer_id'],'cust'),provider_mode=settings.RAZORPAY_MODE)
            error=''
        except (KeyError,TypeError,DomainError):error='event_incomplete'
    OutboxJob.objects.get_or_create(dedupe_key=f'payment-event:{event.id}',defaults={'kind':'payment_event_reconcile','payload':payload,
        'status':'blocked' if error else 'pending','error_code':error,'not_before':timezone.now()})
    return {'received':True}
