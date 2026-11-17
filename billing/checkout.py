"""Hosted sandbox checkout and durable unknown-outcome reconciliation.

Live activation remains unavailable until issuer/tax/invoice qualification exists.
"""
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from core.api import DomainError
from core.models import OutboxJob
from core.services import apply_operation,payload_hash
from .models import Offer,Order
from .razorpay import RazorpayClient,configuration,provider_id,evidence_hash


def qualified_mode():
    mode,key,secret=configuration()
    if mode!='test':raise DomainError('provider_not_enabled','Live financial issuer and invoice policy is not qualified.',503)
    return mode,key,secret


def eligible(user,offer,territory):
    qualified_mode()
    if territory!='IN' or offer.currency!='INR':raise DomainError('region_unavailable','This merchant offer is not qualified for this region.',403)
    if not user.is_active or not user.is_verified:raise DomainError('verification_required','An active verified member is required.',403)
    if not offer.test_only or not offer.active or not offer.approved or offer.kind!='edition_purchase':raise DomainError('offer_unavailable','This offer is not qualified.',409)
    if offer.expires_at and offer.expires_at<=timezone.now():raise DomainError('offer_expired','This offer expired.',409)
    from library.services import authorize_purchase
    if not offer.edition_id or not offer.edition.live_revision_id:raise DomainError('offer_unavailable','No published edition supports this offer.',409)
    for format in offer.formats:authorize_purchase(user,offer.edition.live_revision,format,territory)


def offer_data(offer):
    return {'offer_id':str(offer.id),'version':offer.version,'name':offer.name,'kind':offer.kind,'availability':'available',
        'price':{'amount_minor':offer.price_minor,'currency':offer.currency},'access_duration_seconds':offer.duration_seconds,
        'edition_id':str(offer.edition_id) if offer.edition_id else None,'track_id':str(offer.track_id) if offer.track_id else None,
        'formats':offer.formats,'terms_version':offer.terms_version,'terms_summary':offer.terms_summary,
        'expires_at':offer.expires_at.isoformat().replace('+00:00','Z') if offer.expires_at else None,'auto_renews':False}


def create_order(user,data,operation_id,territory):
    from accounts.services import safe_return_path
    from .services import order_data
    offer=Offer.objects.select_related('edition__live_revision').filter(pk=data['offer_id']).first()
    if not offer:raise DomainError('not_found','Offer not found.',404)
    eligible(user,offer,territory)
    if data['offer_version']!=offer.version or data['terms_version']!=offer.terms_version:raise DomainError('reconfirm_required','Offer terms changed.',422)
    payload={**data,'return_path':safe_return_path(data['return_path'])}
    def mutate():
        old=Order.objects.filter(user=user,operation_id=operation_id).first()
        if old:
            if old.request_sha256!=payload_hash('order.create',payload):raise DomainError('idempotency_key_reused','Order input changed.',409)
            return 202,order_data(old),old.version
        row=Order.objects.create(user=user,offer=offer,operation_id=operation_id,request_sha256=payload_hash('order.create',payload),
            total_minor=offer.price_minor,currency=offer.currency,provider='razorpay',test_only=True,status='creating',return_path=payload['return_path'],
            expires_at=timezone.now()+timedelta(minutes=30),offer_snapshot={'edition_id':str(offer.edition_id),'formats':offer.formats,
                'duration_seconds':offer.duration_seconds,'terms_version':offer.terms_version,'offer_version':offer.version,'test_only':True,
                'merchant_config':settings.MERCHANT_ENTITY_CONFIG_VERSION,'territory':territory})
        OutboxJob.objects.create(kind='checkout_reconcile',dedupe_key=f'checkout:{row.id}',actor=user,payload={'order_id':str(row.id)},not_before=timezone.now())
        return 202,order_data(row),row.version
    return apply_operation(user,operation_id,'order.create',payload,mutate)


def process_checkout(job):
    qualified_mode();client=RazorpayClient()
    # Mark attempt BEFORE network I/O. An unknown result is reconciled, never blindly retried.
    with transaction.atomic():
        current=OutboxJob.objects.select_for_update().get(pk=job.pk)
        order=Order.objects.select_for_update(of=('self',)).select_related('offer','user','offer__edition__live_revision').get(pk=current.payload['order_id'])
        if order.provider_order_id:return {'order_id':str(order.id)}
        eligible(order.user,order.offer,order.offer_snapshot['territory'])
        if order.expires_at<=timezone.now():order.status='expired';order.version+=1;order.save();return {'expired':True}
        attempted=current.payload.get('provider_create_attempted',False)
        if not attempted:
            current.payload={**current.payload,'provider_create_attempted':True};current.save(update_fields=['payload'])
    response=client.find_order(order) if attempted else client.create_order(order)
    if not response:raise DomainError('awaiting_resolution','Merchant creation outcome requires reconciliation; no repeated order was created.',409)
    identity=provider_id(response.get('id'),'order')
    if response.get('amount')!=order.total_minor or response.get('currency')!=order.currency or response.get('receipt')!=str(order.id):raise DomainError('provider_identity_mismatch','Merchant order does not match the immutable local order.',409)
    with transaction.atomic():
        row=Order.objects.select_for_update().get(pk=order.pk)
        if row.provider_order_id and row.provider_order_id!=identity:raise DomainError('provider_identity_mismatch','Merchant order identity changed.',409)
        row.provider_order_id=identity;row.status='created';row.version+=1;row.save()
    return {'order_id':str(order.id)}


def reconcile_payment(order,payment_id,event_id=None,event_hash=None):
    qualified_mode()
    row=RazorpayClient().fetch_payment(payment_id)
    if row.get('id')!=payment_id or row.get('order_id')!=order.provider_order_id:raise DomainError('payment_identity_mismatch','Merchant payment belongs to another order.',409)
    if row.get('status')!='captured' or row.get('captured') is not True:raise DomainError('payment_pending','Payment has not been captured.',409)
    if type(row.get('amount'))!=int or row.get('amount')<=0 or not isinstance(row.get('currency'),str):raise DomainError('provider_response_invalid','Merchant payment facts are invalid.',503)
    from .services import CaptureFacts,apply_capture
    facts=CaptureFacts('razorpay',payment_id,row['order_id'],row['amount'],row['currency'],event_hash or evidence_hash(row),'razorpay_api_test')
    return apply_capture(order.id,facts,event_id=event_id,territory=order.offer_snapshot.get('territory','IN'))
