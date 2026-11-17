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
    # No approved production price or merchant adapter exists in the local build.
    return api_response(page([]))


@json_endpoint(('GET','POST'))
def orders(request):
    if request.method=='POST':raise DomainError('feature_disabled','Live checkout is not configured. No provider order or charge was created.',409)
    return api_response(page([order_data(x) for x in Order.objects.filter(user=request.user).select_related('offer').order_by('-created_at')[:100]]))


@json_endpoint(('GET',))
def order(request,order_id):
    row=Order.objects.filter(pk=order_id,user=request.user).select_related('offer').first()
    if not row:raise DomainError('not_found','Order not found.',404)
    return api_response(order_data(row),version=row.version)


@json_endpoint(('GET',))
def entitlements(request):
    rows=Entitlement.objects.filter(user=request.user).order_by('-valid_until')[:100]
    return api_response(page([entitlement_data(e) for e in rows]))


@json_endpoint(('GET','POST'))
def refunds(request):
    if request.method=='GET':return api_response(page([refund_data(x) for x in Refund.objects.filter(payment__order__user=request.user).select_related('payment').order_by('-created_at')[:100]]))
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
    # No enabled merchant adapter may apply public events. Dedicated route is the sole CSRF exemption.
    raise DomainError('provider_not_enabled','Merchant webhook processing is not configured and qualified.',503)
