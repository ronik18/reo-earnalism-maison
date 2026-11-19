"""Hosted merchant checkout with mode-bound durable reconciliation."""
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
    return configuration()


def free_purchase_guard():
    if getattr(settings,'FREE_ACCESS_ENABLED',False):
        raise DomainError('free_access_enabled','Maison access is free; new purchases are disabled.',409)


def eligible(user,offer,territory,allow_existing=False):
    if not allow_existing:free_purchase_guard()
    mode,_,_=qualified_mode()
    if territory!='IN' or offer.currency!='INR':raise DomainError('region_unavailable','This merchant offer is not qualified for this region.',403)
    if not user.is_active or not user.is_verified:raise DomainError('verification_required','An active verified member is required.',403)
    if offer.test_only!=(mode=='test') or not offer.active or not offer.approved or offer.kind!='edition_purchase':raise DomainError('offer_unavailable','This offer is not qualified.',409)
    if offer.expires_at and offer.expires_at<=timezone.now():raise DomainError('offer_expired','This offer expired.',409)
    if mode=='live':
        from .finance import live_snapshot
        live_snapshot(offer,territory)
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
    free_purchase_guard()
    from accounts.services import safe_return_path
    from .services import order_data
    offer=Offer.objects.select_related('edition__live_revision').filter(pk=data['offer_id']).first()
    if not offer:raise DomainError('not_found','Offer not found.',404)
    eligible(user,offer,territory)
    if data['offer_version']!=offer.version or data['terms_version']!=offer.terms_version:raise DomainError('reconfirm_required','Offer terms changed.',422)
    mode,_,_=qualified_mode()
    from .finance import live_snapshot
    finance=live_snapshot(offer,territory) if mode=='live' else None
    payload={**data,'return_path':safe_return_path(data['return_path'])}
    def mutate():
        old=Order.objects.filter(user=user,operation_id=operation_id).first()
        if old:
            if old.request_sha256!=payload_hash('order.create',payload):raise DomainError('idempotency_key_reused','Order input changed.',409)
            return 202,order_data(old),old.version
        row=Order.objects.create(user=user,offer=offer,operation_id=operation_id,request_sha256=payload_hash('order.create',payload),
            total_minor=offer.price_minor,currency=offer.currency,provider='razorpay',test_only=(mode=='test'),status='creating',return_path=payload['return_path'],
            expires_at=timezone.now()+timedelta(minutes=30),offer_snapshot={'edition_id':str(offer.edition_id),'formats':offer.formats,
                'duration_seconds':offer.duration_seconds,'terms_version':offer.terms_version,'offer_version':offer.version,'test_only':(mode=='test'),
                'merchant_config':settings.MERCHANT_ENTITY_CONFIG_VERSION,'territory':territory,**({'finance':finance} if finance else {})})
        OutboxJob.objects.create(kind='checkout_reconcile',dedupe_key=f'checkout:{row.id}',actor=user,payload={'order_id':str(row.id)},not_before=timezone.now())
        return 202,order_data(row),row.version
    return apply_operation(user,operation_id,'order.create',payload,mutate)


def process_checkout(job):
    # Mark attempt BEFORE network I/O. An unknown result is reconciled, never blindly retried.
    with transaction.atomic():
        current=OutboxJob.objects.select_for_update().get(pk=job.pk)
        order=Order.objects.select_for_update(of=('self',)).select_related('offer','user','offer__edition__live_revision').get(pk=current.payload['order_id'])
        attempted=current.payload.get('provider_create_attempted',False)
        if not order.provider_order_id and not attempted:free_purchase_guard()
        mode,_,_=qualified_mode()
        if order.test_only!=(mode=='test'):raise DomainError('provider_mode_mismatch','Order belongs to another merchant mode.',409)
        if order.provider_order_id:return {'order_id':str(order.id)}
        eligible(order.user,order.offer,order.offer_snapshot['territory'],allow_existing=attempted)
        if order.expires_at<=timezone.now():order.status='expired';order.version+=1;order.save();return {'expired':True}
        if not attempted:
            current.payload={**current.payload,'provider_create_attempted':True};current.save(update_fields=['payload'])
    client=RazorpayClient()
    response=client.find_order(order) if attempted else client.create_order(order)
    if not response:raise DomainError('awaiting_resolution','Merchant creation outcome requires reconciliation; no repeated order was created.',409)
    identity=provider_id(response.get('id'),'order')
    if response.get('amount')!=order.total_minor or response.get('currency')!=order.currency or response.get('receipt')!=str(order.id):raise DomainError('provider_identity_mismatch','Merchant order does not match the immutable local order.',409)
    with transaction.atomic():
        row=Order.objects.select_for_update().get(pk=order.pk)
        if row.provider_order_id and row.provider_order_id!=identity:raise DomainError('provider_identity_mismatch','Merchant order identity changed.',409)
        row.provider_order_id=identity
        if row.status in {'creating','created','pending'}:row.status='created'
        row.version+=1;row.save()
    return {'order_id':str(order.id)}


def reconcile_payment(order,payment_id,event_id=None,event_hash=None):
    mode,_,_=qualified_mode()
    if order.test_only!=(mode=='test'):raise DomainError('provider_mode_mismatch','Order belongs to another merchant mode.',409)
    row=RazorpayClient().fetch_payment(payment_id)
    if row.get('id')!=payment_id or row.get('order_id')!=order.provider_order_id:raise DomainError('payment_identity_mismatch','Merchant payment belongs to another order.',409)
    if row.get('status')!='captured' or row.get('captured') is not True:raise DomainError('payment_pending','Payment has not been captured.',409)
    if type(row.get('amount'))!=int or row.get('amount')<=0 or not isinstance(row.get('currency'),str):raise DomainError('provider_response_invalid','Merchant payment facts are invalid.',503)
    from .services import CaptureFacts,apply_capture
    facts=CaptureFacts('razorpay',payment_id,row['order_id'],row['amount'],row['currency'],event_hash or evidence_hash(row),'razorpay_api_'+mode)
    return apply_capture(order.id,facts,event_id=event_id,territory=order.offer_snapshot.get('territory','IN'))


def process_payment_event(job):
    from .models import PaymentEvent
    event=PaymentEvent.objects.get(pk=job.payload['event_id'],provider='razorpay')
    if event.body_sha256!=job.payload.get('body_sha256'):
        raise DomainError('event_payload_mismatch','Event receipt identity changed.',409)
    if event.status=='applied':return {'event_id':str(event.id),'status':'applied'}
    if job.payload.get('event_name')=='token.cancelled':
        from .subscription_worker import process_token_cancelled_event
        return process_token_cancelled_event(event,job.payload)
    order=Order.objects.filter(provider='razorpay',provider_order_id=job.payload.get('provider_order_id')).select_related('offer').first()
    if not order:raise DomainError('payment_order_pending','The merchant order must be reconciled before its event.',503)
    reconcile_payment(order,job.payload['payment_id'],event_id=event.provider_event_id,event_hash=event.body_sha256)
    return {'event_id':str(event.id),'status':'applied'}


def request_order_reconciliation(actor,order_id,key,reason):
    from .services import order_data
    from core.services import audit
    if not actor.is_active or not actor.is_staff or not actor.has_perm('billing.reconcile_order'):
        raise DomainError('permission_denied','Billing reconciliation permission is required.',403)
    def execute():
        row=Order.objects.select_for_update().filter(pk=order_id).first()
        if not row:raise DomainError('not_found','Order not found.',404)
        payload={'order_id':str(row.id),'reason':reason}
        job,created=OutboxJob.objects.get_or_create(dedupe_key=f'order-reconcile:{actor.pk}:{row.id}:{key}',defaults={
            'kind':'order_payment_reconcile','actor':actor,'payload':payload,'not_before':timezone.now()})
        if job.kind!='order_payment_reconcile' or job.actor_id!=actor.pk or job.payload!=payload:
            raise DomainError('idempotency_key_reused','Reconciliation input changed.',409)
        if created:audit(actor,'order.reconcile_requested',row,{'reason':reason})
        return 200,order_data(row),row.version
    return apply_operation(actor,key,'order.reconcile',{'order_id':str(order_id),'reason':reason},execute)


def process_order_reconcile(job):
    mode,_,_=qualified_mode()
    row=Order.objects.filter(pk=job.payload['order_id'],provider='razorpay',test_only=(mode=='test')).select_related('offer').first()
    if not row:raise DomainError('order_reconciliation_unavailable','Only orders matching the configured merchant mode can be reconciled.',409)
    if not row.provider_order_id:
        original=OutboxJob.objects.filter(dedupe_key=f'checkout:{row.id}').first()
        if not original:raise DomainError('order_reconciliation_unavailable','The original checkout intent is required.',409)
        process_checkout(original);row.refresh_from_db()
    if not row.provider_order_id:return {'order_id':str(row.id),'status':row.status}
    response=RazorpayClient().order_payments(row.provider_order_id);items=response.get('items')
    if (not isinstance(items,list) or len(items)>3 or any(not isinstance(item,dict) for item in items)
        or ('count' in response and (type(response['count'])!=int or response['count']!=len(items)))):
        raise DomainError('provider_response_invalid','A complete bounded payment collection is required.',503)
    for payment in items:
        if payment.get('order_id')!=row.provider_order_id:
            raise DomainError('payment_identity_mismatch','Merchant collection contains another order.',409)
        if payment.get('status')=='captured' and payment.get('captured') is True:
            reconcile_payment(row,provider_id(payment.get('id'),'pay'))
    row.refresh_from_db()
    return {'order_id':str(row.id),'status':row.status,'fulfillment_status':row.fulfillment_status}
