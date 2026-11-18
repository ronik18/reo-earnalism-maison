from django.conf import settings
from core.pagination import paginate_queryset
from core.api import json_endpoint,api_response,DomainError,json_body,operation_key,expected_version
from .models import Order,Entitlement,Offer,Refund,Invoice
from .services import order_data,request_refund,refund_data,approve_refund
from accounts.views import require_fresh
from library.validation import body as validated_body
from .services import entitlement_data
from django.views.decorators.csrf import csrf_exempt


def page(values):return {'items':values,'next_cursor':None,'has_more':False}


@json_endpoint(('GET',))
def offers(request):
    from .checkout import eligible,offer_data
    values=[]
    for row in Offer.objects.filter(active=True,approved=True).select_related('edition__live_revision')[:100]:
        try:eligible(request.user,row,getattr(request,'territory','IN' if settings.LOCAL else 'ZZ'))
        except DomainError:continue
        values.append(offer_data(row))
    return api_response(page(values))


@json_endpoint(('GET','POST'))
def orders(request):
    if request.method=='POST':
        from .checkout import create_order
        status,body=create_order(request.user,validated_body(request,'OrderInput'),operation_key(request),getattr(request,'territory','IN' if settings.LOCAL else 'ZZ'))
        return api_response(body,status,version=body['version'])
    result=paginate_queryset(request,Order.objects.filter(user=request.user).select_related('offer'),'orders')
    result['items']=[order_data(x) for x in result['items']]
    return api_response(result)


@json_endpoint(('GET',))
def order(request,order_id):
    row=Order.objects.filter(pk=order_id,user=request.user).select_related('offer').first()
    if not row:raise DomainError('not_found','Order not found.',404)
    return api_response(order_data(row),version=row.version)


@json_endpoint(('GET',))
def entitlements(request):
    result=paginate_queryset(request,Entitlement.objects.filter(user=request.user),'entitlements',ordering='id')
    result['items']=[entitlement_data(e) for e in result['items']]
    return api_response(result)


@json_endpoint(('GET','POST'))
def refunds(request):
    if request.method=='GET':
        result=paginate_queryset(request,Refund.objects.filter(payment__order__user=request.user).select_related('payment'),'refunds')
        result['items']=[refund_data(x) for x in result['items']]
        return api_response(result)
    d=validated_body(request,'RefundRequestInput')
    status,body=request_refund(request.user,d['order_id'],operation_key(request),d['reason'],d['description']);return api_response(body,status,version=body['version'])


@json_endpoint(('GET',))
def refund(request,refund_id):
    row=Refund.objects.filter(pk=refund_id,payment__order__user=request.user).select_related('payment').first()
    if not row:raise DomainError('not_found','Refund not found.',404)
    return api_response(refund_data(row),version=row.version)


@json_endpoint(('POST',))
def approve(request,refund_id):
    require_fresh(request);d=validated_body(request,'RefundApprovalInput')
    status,body=approve_refund(request.user,refund_id,d['amount_minor'],expected_version(request),operation_key(request),d['reason']);return api_response(body,status,version=body['version'])


@json_endpoint(('GET','POST','DELETE'),auth=False)
def disabled(request,**kwargs):raise DomainError('feature_disabled','This merchant/provider capability is not configured and qualified.',409)


@json_endpoint(('GET',))
def invoices(request):return api_response(page([]))


@csrf_exempt
@json_endpoint(('POST',),auth=False)
def webhook(request):
    import json
    from .checkout import qualified_mode,reconcile_payment
    from .services import verify_webhook_signature
    from .razorpay import evidence_hash
    qualified_mode();raw=request.body
    verify_webhook_signature(raw,request.headers.get('X-Razorpay-Signature'),getattr(settings,'RAZORPAY_WEBHOOK_SECRETS',()))
    try:data=json.loads(raw)
    except (ValueError,UnicodeDecodeError):raise DomainError('invalid_webhook','Invalid event JSON.',400)
    event_id=request.headers.get('X-Razorpay-Event-Id','')
    if not event_id or len(event_id)>128:raise DomainError('invalid_webhook','A bounded event ID is required.',400)
    if data.get('event') not in ['payment.captured','order.paid']:return api_response({'received':True})
    try:payment=data['payload']['payment']['entity'];identity=payment['id'];provider_order=payment['order_id']
    except (KeyError,TypeError):raise DomainError('invalid_webhook','Missing payment identity.',400)
    row=Order.objects.filter(provider='razorpay',provider_order_id=provider_order).select_related('offer').first()
    if not row:raise DomainError('awaiting_resolution','Merchant order is not yet reconciled.',409)
    import hashlib
    reconcile_payment(row,identity,event_id=event_id,event_hash=hashlib.sha256(raw).hexdigest())
    return api_response({'received':True})


@json_endpoint(('POST',))
def verify_payment(request,order_id):
    from .checkout import qualified_mode,reconcile_payment
    from .services import verify_checkout_signature
    mode,key,secret=qualified_mode();data=validated_body(request,'PaymentVerificationInput')
    row=Order.objects.filter(pk=order_id,user=request.user).select_related('offer').first()
    if not row:raise DomainError('not_found','Order not found.',404)
    verify_checkout_signature(row.provider_order_id,data['razorpay_payment_id'],data['razorpay_order_id'],data['razorpay_signature'],secret)
    body=reconcile_payment(row,data['razorpay_payment_id'])
    return api_response(body,version=body['version'])
