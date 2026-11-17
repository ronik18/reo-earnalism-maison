"""Local money state machines. No merchant HTTP client or browser-success shortcut."""
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.db.models import Q,Sum
from django.utils import timezone
from core.api import DomainError,public_uuid
from core.models import OutboxJob
from core.services import apply_operation,payload_hash,audit
from .models import Offer,Order,Payment,PaymentEvent,Refund,Entitlement,Invoice,PaymentAllocation


@dataclass(frozen=True)
class CaptureFacts:
    provider:str
    payment_id:str
    order_reference:str
    amount_minor:int
    currency:str
    evidence_sha256:str
    verification_source:str='synthetic_test'


def _eligible(user,revision,format,at):
    return Entitlement.objects.filter(user=user,status='active',revoked_at=None,valid_from__lte=at).filter(
        Q(valid_until__isnull=True)|Q(valid_until__gt=at)).filter(
        Q(scope='edition',edition_id=revision.edition_id)|Q(scope='platform')).filter(Q(revision__isnull=True)|Q(revision=revision))


def has_entitlement(user,revision,format='reader',at=None):
    if not getattr(user,'is_authenticated',False):return False
    return any(format in e.formats for e in _eligible(user,revision,format,at or timezone.now()))


def entitlement_expires_at(user,revision,format='reader',at=None):
    values=[e.valid_until for e in _eligible(user,revision,format,at or timezone.now()) if format in e.formats]
    return None if not values or None in values else max(values)


@transaction.atomic
def ensure_free_entitlement(user,revision,format='reader',territory='IN'):
    from library.services import authorize_revision
    revision=authorize_revision(user,revision,format,action='download',territory=territory)
    if revision.access_policy.get(format)!='free':raise DomainError('free_grant_not_permitted','This format is not explicitly free.',403)
    # Lock actor for two simultaneous first free grants. Durable key survives personal receipt expiry.
    from django.contrib.auth import get_user_model
    get_user_model().objects.select_for_update().get(pk=user.pk)
    row,created=Entitlement.objects.get_or_create(grant_key=f'free:{user.public_id}:{revision.id}',defaults={
        'user':user,'source':'free','scope':'edition','edition':revision.edition,'revision':revision,'formats':[format],
        'valid_from':timezone.now(),'valid_until':None})
    if row.revoked_at or row.status!='active':raise DomainError('entitlement_revoked','This free offline grant has been revoked.',403)
    if format not in row.formats:
        row.formats=[*row.formats,format];row.version+=1;row.save()
    return row


def entitlement_data(e):
    now=timezone.now()
    return {'entitlement_id':str(e.id),'source':e.source,'scope':e.scope,'edition_id':str(e.edition_id) if e.edition_id else None,
        'track_id':str(e.track_id) if e.track_id else None,'formats':e.formats,'valid_from':e.valid_from.isoformat().replace('+00:00','Z'),
        'valid_until':e.valid_until.isoformat().replace('+00:00','Z') if e.valid_until else None,
        'status':'revoked' if e.revoked_at or e.status=='revoked' else 'expired' if e.valid_until and e.valid_until<=now else 'active',
        'revoked_at':e.revoked_at.isoformat().replace('+00:00','Z') if e.revoked_at else None}


def order_data(row):
    refunded=row.payments.aggregate(n=Sum('refunds__amount_minor',filter=Q(refunds__status='processed')))['n'] or 0
    payment=row.payments.order_by('-captured_at').first()
    return {'order_id':str(row.id),'offer_id':str(row.offer_id),'offer_version':row.offer_snapshot.get('offer_version',row.offer.version),'status':row.status,'fulfillment_status':row.fulfillment_status,
        'amount':{'amount_minor':row.total_minor,'currency':row.currency},'refunded_amount_minor':refunded,'payment_status':payment.status if payment else 'not_started',
        'created_at':row.created_at.isoformat().replace('+00:00','Z'),'expires_at':row.expires_at.isoformat().replace('+00:00','Z'),'version':row.version,'checkout':checkout_data(row),'entitlement_ids':[str(x) for x in row.entitlements.values_list('id',flat=True)],'return_path':row.return_path}


def checkout_data(row):
    if not row.provider_order_id or row.status not in ['created','pending'] or row.expires_at<=timezone.now():return None
    if row.provider!='razorpay':return None
    from .checkout import qualified_mode
    try:mode,key,secret=qualified_mode()
    except DomainError:return None
    if not row.test_only:return None
    return {'provider':'razorpay','public_key_id':key,'provider_order_id':row.provider_order_id,
        'amount':{'amount_minor':row.total_minor,'currency':row.currency},'name':'Earnalism — Sandbox',
        'description':row.offer.name[:220]+' (test payment)'}


def create_local_order(user,offer,operation_id,return_path='/',offer_version=None,terms_version=None):
    """Test/local preparation only; never creates a provider order or claims checkout."""
    from accounts.services import safe_return_path
    if not getattr(settings,'MAISON_LOCAL_FIXTURES',False) or not offer.test_only:raise DomainError('provider_not_enabled','Merchant checkout is not configured.',409)
    if not offer.approved or not offer.active:raise DomainError('offer_unavailable','This offer is unavailable.',409)
    if offer.expires_at and offer.expires_at<=timezone.now():raise DomainError('offer_expired','This offer has expired.',409)
    if not user.is_active or not user.is_verified:raise DomainError('verification_required','An active verified member is required.',403)
    if offer_version not in (None,offer.version) or terms_version not in (None,offer.terms_version):raise DomainError('reconfirm_required','Offer terms changed.',422)
    payload={'offer_id':str(offer.id),'offer_version':offer.version,'terms_version':offer.terms_version,'return_path':safe_return_path(return_path)}
    def mutate():
        # Resource linkage preserves dedupe even after a personal receipt expires.
        old=Order.objects.filter(user=user,operation_id=operation_id).first();digest=payload_hash('order.create',payload)
        if old:
            if old.request_sha256!=digest:raise DomainError('idempotency_key_reused','Order action input changed.',409)
            return 201,order_data(old),old.version
        snapshot={'edition_id':str(offer.edition_id) if offer.edition_id else None,'formats':offer.formats,'duration_seconds':offer.duration_seconds,'terms_version':offer.terms_version,'offer_version':offer.version,'test_only':True}
        row=Order.objects.create(user=user,offer=offer,operation_id=operation_id,request_sha256=digest,status='creating',currency=offer.currency,total_minor=offer.price_minor,offer_snapshot=snapshot,
            test_only=True,return_path=payload['return_path'],expires_at=timezone.now()+timedelta(minutes=30))
        return 201,order_data(row),row.version
    return apply_operation(user,operation_id,'order.create',payload,mutate)


def _review_job(order,payment,reason):
    OutboxJob.objects.get_or_create(dedupe_key=f'refund-reconcile:{payment.id}',defaults={'kind':'refund_reconcile','actor':order.user,'payload':{'order_id':str(order.id),'payment_id':str(payment.id),'reason':reason},'not_before':timezone.now()})


def apply_capture(order_id,facts,event_id=None,territory='IN'):
    """Accepts already authenticated adapter facts, or explicitly synthetic local tests.

    No public endpoint can construct these facts until a real adapter is qualified.
    """
    if facts.verification_source=='razorpay_api_test':
        from .checkout import qualified_mode
        qualified_mode()
        if facts.provider!='razorpay':raise DomainError('invalid_payment_facts','Invalid verifier/provider binding.',422)
    elif facts.verification_source!='synthetic_test':raise DomainError('provider_not_enabled','No live merchant verifier has been qualified.',409)
    if facts.verification_source=='synthetic_test' and not getattr(settings,'MAISON_LOCAL_FIXTURES',False):raise DomainError('synthetic_payment_forbidden','Synthetic payment facts are local-test only.',403)
    if (type(facts.amount_minor)!=int or facts.amount_minor<=0 or len(facts.evidence_sha256)!=64
            or any(c not in '0123456789abcdef' for c in facts.evidence_sha256)
            or not facts.provider or len(facts.provider)>20 or not facts.payment_id or len(facts.payment_id)>128):
        raise DomainError('invalid_payment_facts','Invalid trusted payment facts.',422)
    with transaction.atomic():
        order=Order.objects.select_for_update(of=('self',)).select_related('offer','user','offer__edition__live_revision').get(pk=order_id)
        if not order.test_only:raise DomainError('synthetic_payment_forbidden','A synthetic event cannot change a real order.',403)
        if event_id:
            event=PaymentEvent.objects.select_for_update().filter(provider=facts.provider,provider_event_id=event_id).first()
            if event and event.body_sha256!=facts.evidence_sha256:raise DomainError('event_payload_mismatch','An event ID was reused with different facts.',409)
            if event:
                if not event.payment_id or event.payment.order_id!=order.id or event.payment.provider_payment_id!=facts.payment_id:
                    raise DomainError('event_identity_mismatch','An authenticated event cannot identify another payment.',409)
                return order_data(order)
        existing=Payment.objects.select_for_update().filter(provider=facts.provider,provider_payment_id=facts.payment_id).first()
        if existing:
            if existing.order_id!=order.id or existing.amount_minor!=facts.amount_minor or existing.currency!=facts.currency:raise DomainError('payment_identity_mismatch','Payment identity cannot be reassigned.',409)
            if event_id:PaymentEvent.objects.create(provider=facts.provider,provider_event_id=event_id,body_sha256=facts.evidence_sha256,payment=existing,status='applied')
            return order_data(order)
        now=timezone.now();late=order.status in ['expired','cancelled','failed'] or order.expires_at<=now
        payment=Payment.objects.create(order=order,provider=facts.provider,provider_payment_id=facts.payment_id,amount_minor=facts.amount_minor,currency=facts.currency,
            verification_source=facts.verification_source,evidence_sha256=facts.evidence_sha256,captured_at=now)
        event=None
        if event_id:event=PaymentEvent.objects.create(provider=facts.provider,provider_event_id=event_id,body_sha256=facts.evidence_sha256,payment=payment,status='applied')
        already_paid=order.status=='paid';order.status='paid';order.paid_at=order.paid_at or now;order.version+=1
        if facts.amount_minor!=order.total_minor or facts.currency!=order.currency or facts.order_reference!=(order.provider_order_id or str(order.id)):
            order.fulfillment_status='review';_review_job(order,payment,'payment_mismatch')
        elif late or already_paid:
            # A genuine second capture is a distinct financial obligation, never another grant.
            order.fulfillment_status='refund_pending' if not already_paid else order.fulfillment_status
            _review_job(order,payment,'late_capture' if late else 'duplicate_capture')
        else:
            try:
                from library.services import authorize_purchase
                edition_id=order.offer_snapshot.get('edition_id')
                from library.models import Edition
                edition=Edition.objects.select_related('live_revision').filter(pk=edition_id).first()
                if not edition or not edition.live_revision_id or not order.offer_snapshot.get('formats'):raise DomainError('content_unavailable','No published edition for this offer.',409)
                for format in order.offer_snapshot['formats']:authorize_purchase(order.user,edition.live_revision,format,territory)
            except DomainError:
                order.fulfillment_status='refund_pending';_review_job(order,payment,'fulfillment_unavailable')
            else:
                Entitlement.objects.get_or_create(grant_key=f'order:{order.id}',defaults={'user':order.user,'source':'one_time_order','scope':'edition','order':order,'edition_id':edition_id,'formats':order.offer_snapshot['formats'],
                    'valid_from':now,'valid_until':now+timedelta(seconds=order.offer_snapshot['duration_seconds'])})
                order.fulfillment_status='granted'
                snapshot={'order_id':str(order.id),'amount_minor':order.total_minor,'currency':order.currency,'local_test_document':True,'sandbox':facts.verification_source=='razorpay_api_test'}
                inv,_=Invoice.objects.get_or_create(order=order,defaults={'number':f"{'SANDBOX' if facts.verification_source=='razorpay_api_test' else 'LOCAL-TEST'}-{order.id}",'amount_minor':order.total_minor,'currency':order.currency,'document_sha256':hashlib.sha256(json.dumps(snapshot,sort_keys=True).encode()).hexdigest(),'line_snapshot':snapshot,'issued_at':now})
                PaymentAllocation.objects.get_or_create(payment=payment,invoice=inv,defaults={'amount_minor':order.total_minor})
        order.save();audit(order.user,'payment.capture_applied',order,{'source':facts.verification_source,'fulfillment':order.fulfillment_status})
        return order_data(order)


def request_refund(user,order_id,operation_id,reason='other',description=''):
    def mutate():
        order=Order.objects.select_for_update().filter(pk=order_id,user=user).first()
        if not order:raise DomainError('not_found','Order not found.',404)
        payment=order.payments.select_for_update().filter(status__in=['captured','partially_refunded']).order_by('captured_at').first()
        if not payment:raise DomainError('refund_unavailable','No captured payment is available.',409)
        old=Refund.objects.filter(operation_id=operation_id).first()
        if old:
            if old.payment.order_id!=order.id:raise DomainError('idempotency_key_reused','Refund operation already belongs to another order.',409)
            return 202,refund_data(old),old.version
        reserved=payment.refunds.filter(status__in=['approved','submitted','pending','processed']).aggregate(n=Sum('amount_minor'))['n'] or 0
        if reserved>=payment.amount_minor:raise DomainError('refund_unavailable','No unreserved captured amount remains.',409)
        refund=Refund.objects.create(payment=payment,operation_id=operation_id,proposed_amount_minor=payment.amount_minor-reserved,amount_minor=None,currency=payment.currency,reason=reason,description=description)
        return 202,refund_data(refund),refund.version
    return apply_operation(user,operation_id,'refund.request',{'order_id':str(order_id),'reason':reason,'description':description},mutate)


def refund_data(row):
    return {'refund_id':str(row.id),'order_id':str(row.payment.order_id),'amount':{'amount_minor':row.amount_minor,'currency':row.currency} if row.amount_minor is not None else None,'status':row.status,'reason':row.reason,'version':row.version,'requested_at':row.created_at.isoformat().replace('+00:00','Z'),'processed_at':row.processed_at.isoformat().replace('+00:00','Z') if row.processed_at else None}


def approve_refund(actor,refund_id,amount_minor,base_version,operation_id,reason='Staff policy review'):
    if not actor.is_active or not actor.is_staff or not actor.has_perm('billing.approve_refund'):raise DomainError('permission_denied','Refund approver permission is required.',403)
    def mutate():
        initial=Refund.objects.select_related('payment').filter(pk=refund_id).first()
        if not initial:raise DomainError('not_found','Refund not found.',404)
        # All financial services lock order -> payment -> refund, including late capture.
        Order.objects.select_for_update().get(pk=initial.payment.order_id)
        payment=Payment.objects.select_for_update().get(pk=initial.payment_id);row=Refund.objects.select_for_update().get(pk=refund_id)
        if row.version!=base_version:raise DomainError('version_conflict','Refund changed.',412,refund_data(row))
        if row.status!='requested':raise DomainError('invalid_refund_state','This request has already been reviewed.',409)
        reserved=payment.refunds.filter(status__in=['approved','submitted','pending','processed']).exclude(pk=row.pk).aggregate(n=Sum('amount_minor'))['n'] or 0
        if type(amount_minor)!=int or amount_minor<=0 or amount_minor>row.proposed_amount_minor or reserved+amount_minor>payment.amount_minor:raise DomainError('refund_exceeds_available','Refund exceeds captured funds.',422)
        row.status='approved';row.amount_minor=amount_minor;row.approved_by=actor;row.approved_at=timezone.now();row.version+=1;row.save()
        OutboxJob.objects.get_or_create(dedupe_key=f'refund-submit:{row.id}',defaults={'kind':'refund_reconcile','actor':row.payment.order.user,'payload':{'refund_id':str(row.id)},'not_before':timezone.now()})
        audit(actor,'refund.approved',row,{'amount_minor':amount_minor,'reason':reason});return 200,refund_data(row),row.version
    return apply_operation(actor,operation_id,'refund.approve',{'refund_id':str(refund_id),'amount_minor':amount_minor,'base_version':base_version,'reason':reason},mutate)


def verify_checkout_signature(stored_order_id,payment_id,callback_order_id,signature,secret):
    """Authenticates callback identity only. Capture/amount/ownership still need provider reconciliation."""
    if not secret or stored_order_id!=callback_order_id:
        raise DomainError('invalid_payment_signature','Payment callback identity failed verification.',400)
    expected=hmac.new(secret.encode(),f'{stored_order_id}|{payment_id}'.encode(),hashlib.sha256).hexdigest()
    if not isinstance(signature,str) or not hmac.compare_digest(expected,signature):
        raise DomainError('invalid_payment_signature','Payment callback signature failed verification.',400)


def verify_webhook_signature(raw_body,signature,secrets):
    """Raw-body HMAC with bounded current/previous key rotation, no JSON reserialization."""
    if not isinstance(raw_body,bytes) or len(raw_body)>1048576 or not isinstance(signature,str):
        raise DomainError('invalid_webhook','Invalid webhook body or signature.',400)
    if not secrets or len(secrets)>2 or any(not isinstance(secret,str) or not secret for secret in secrets):
        raise DomainError('provider_not_enabled','Webhook verification is not configured.',503)
    valid=any(hmac.compare_digest(hmac.new(secret.encode(),raw_body,hashlib.sha256).hexdigest(),signature) for secret in secrets)
    if not valid:raise DomainError('invalid_webhook_signature','Webhook authentication failed.',400)


def apply_synthetic_refund(refund_id,provider_refund_id):
    if not getattr(settings,'MAISON_LOCAL_FIXTURES',False):raise DomainError('synthetic_payment_forbidden','Local tests only.',403)
    with transaction.atomic():
        initial=Refund.objects.select_related('payment').get(pk=refund_id)
        Order.objects.select_for_update().get(pk=initial.payment.order_id)
        payment=Payment.objects.select_for_update().select_related('order').get(pk=initial.payment_id);row=Refund.objects.select_for_update().get(pk=refund_id)
        if not payment.order.test_only:raise DomainError('synthetic_payment_forbidden','Local tests cannot change real orders.',403)
        if row.status=='processed':
            if row.provider_refund_id!=provider_refund_id:raise DomainError('refund_identity_mismatch','Refund identity changed.',409)
            return refund_data(row)
        if row.status not in ['approved','submitted','pending']:raise DomainError('invalid_refund_state','Refund has not been approved.',409)
        row.status='processed';row.provider_refund_id=provider_refund_id;row.processed_at=timezone.now();row.version+=1;row.save()
        total=payment.refunds.filter(status='processed').aggregate(n=Sum('amount_minor'))['n'] or 0
        payment.status='refunded' if total==payment.amount_minor else 'partially_refunded';payment.version+=1;payment.save()
        if total==payment.amount_minor:
            Entitlement.objects.filter(order=payment.order,revoked_at=None).update(revoked_at=timezone.now())
            payment.order.fulfillment_status='refunded';payment.order.version+=1;payment.order.save()
        return refund_data(row)
