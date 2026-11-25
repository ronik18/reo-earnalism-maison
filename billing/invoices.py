"""Owned immutable invoice history and verified, short-lived private PDF delivery.

Creating an invoice snapshot does not render a PDF. Only a retained document,
verified and bound by permitted finance staff, can be downloaded.
"""
import re
from datetime import timedelta
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import Q,Prefetch
from django.http import FileResponse
from django.utils import timezone
from core.api import DomainError,api_response,json_endpoint,json_body,expected_version
from core.services import audit
from .models import Invoice,PaymentAllocation
from .invoice_models import InvoiceArtifact

GRANT_SALT='maison-invoice-download-v1'
GRANT_SECONDS=120


def iso(value):
    return value.isoformat().replace('+00:00','Z') if value else None


def owned_queryset(user):
    if not user.is_active:
        raise DomainError('authentication_required','Sign in to continue.',401)
    return Invoice.objects.filter(Q(order__user=user)|Q(subscription__user=user)).select_related('order','subscription','subscription__plan','current_revision').prefetch_related(
        Prefetch('paymentallocation_set',queryset=PaymentAllocation.objects.select_related('payment','payment__order').prefetch_related('payment__refunds').order_by('payment__captured_at','id')))


def own_invoice(user,invoice_id):
    row=owned_queryset(user).filter(pk=invoice_id).first()
    if not row:
        raise DomainError('not_found','Invoice not found.',404)
    return row


def invoice_data(row):
    # Historical paid totals stay intact after refunds; only explicit allocations
    # and processed refund records determine the derived current refund state.
    allocations=sorted(row.paymentallocation_set.all(),key=lambda allocation:(allocation.payment.captured_at,allocation.pk))
    owner_id=row.order.user_id if row.order_id else (row.subscription.user_id if row.subscription_id else None)  # institution invoices have no member owner; any allocation fails reconciliation
    allocated=0;paid_at=None;refunded=0
    for allocation in allocations:
        payment=allocation.payment
        # Orders do not yet retain an exact subscription/cycle link. Shared offers are insufficient.
        source_mismatch=(row.order_id is not None and payment.order_id!=row.order_id) or row.subscription_id is not None
        if source_mismatch or payment.order.user_id!=owner_id or payment.currency!=row.currency or payment.status not in {'captured','partially_refunded','refunded'} or not 0<allocation.amount_minor<=payment.amount_minor:
            raise DomainError('invoice_reconciliation_required','Invoice allocations require finance reconciliation.',503)
        amount=allocation.amount_minor
        allocated+=amount
        if paid_at is None and allocated>=row.amount_minor:
            paid_at=payment.captured_at
        processed=sum(refund.amount_minor or 0 for refund in payment.refunds.all() if refund.status=='processed')
        # No amount is removed from the paid historical snapshot.
        if processed and amount!=payment.amount_minor:
            raise DomainError('invoice_reconciliation_required','Refund allocation requires finance reconciliation before this invoice can be displayed.',503)
        refunded+=min(processed,amount)
    if allocated>row.amount_minor:
        raise DomainError('invoice_reconciliation_required','Invoice allocations exceed the immutable snapshot.',503)
    paid=allocated
    return {'invoice_id':str(row.id),'subscription_id':str(row.subscription_id) if row.subscription_id else None,
            'order_id':str(row.order_id) if row.order_id else None,'status':'paid' if paid>=row.amount_minor else 'issued',
            'refund_status':'full' if paid and refunded>=paid else ('partial' if refunded else 'none'),
            'amount':{'amount_minor':row.amount_minor,'currency':row.currency},'paid_amount_minor':paid,
            'period_start':iso(row.period_start),'period_end':iso(row.period_end),'issued_at':iso(row.issued_at),
            'paid_at':iso(paid_at),'revision':row.current_revision.sequence if row.current_revision_id else row.revision,'number':row.current_revision.number if row.current_revision_id else row.number}


def bind_artifact(actor,invoice_id,*,storage_key,sha256,bytes,issuer_version):
    """Bind an already rendered, operator-approved exact PDF. Never render here."""
    if not actor.is_active or not actor.is_staff or not actor.has_perm('billing.attach_invoice_artifact'):
        raise DomainError('permission_denied','Invoice document approval permission is required.',403)
    if (type(bytes)!=int or bytes<5 or not re.fullmatch('[a-f0-9]{64}',sha256 or '') or
        not isinstance(issuer_version,str) or not 1<=len(issuer_version.strip())<=120):
        raise DomainError('validation_error','Exact document size, hash and approved issuer version are required.',422)
    expected=f'exports/invoices/{invoice_id}/{sha256}.pdf'
    if storage_key!=expected:
        raise DomainError('invalid_storage_key','Invoice object identity must match the invoice and exact PDF hash.',422)
    from library import storage
    storage.verify_private(storage_key,bytes,sha256,'application/pdf')
    stream,_,_=storage._open(storage_key)
    try:
        if stream.read(5)!=b'%PDF-':
            raise DomainError('invalid_invoice_document','The retained artifact is not a PDF.',422)
    finally:
        stream.close()
    with transaction.atomic():
        row=Invoice.objects.select_for_update().filter(pk=invoice_id).first()
        if not row:
            raise DomainError('not_found','Invoice not found.',404)
        prior=InvoiceArtifact.objects.filter(invoice=row).first()
        if prior:
            if (prior.storage_key,prior.sha256,prior.bytes,prior.snapshot_sha256,prior.issuer_version)!=(storage_key,sha256,bytes,row.document_sha256,issuer_version.strip()):
                raise DomainError('invoice_artifact_conflict','An immutable document is already bound to this invoice.',409)
            return prior
        artifact=InvoiceArtifact.objects.create(invoice=row,storage_key=storage_key,sha256=sha256,bytes=bytes,
            snapshot_sha256=row.document_sha256,issuer_version=issuer_version.strip(),approved_by=actor)
        audit(actor,'invoice.artifact_bound',row,{'sha256':sha256,'bytes':bytes,'issuer_version':issuer_version.strip()})
        return artifact


def ready_artifact(row):
    if row.current_revision_id and row.current_revision.storage_key:
        from types import SimpleNamespace
        doc=row.current_revision
        return SimpleNamespace(storage_key=doc.storage_key,sha256=doc.document_sha256,bytes=doc.bytes,snapshot_sha256=doc.snapshot_sha256)
    if row.current_revision_id and (row.current_revision.sequence!=row.revision or row.current_revision.approved_by_id is not None):raise DomainError('invoice_not_ready','Current invoice revision has no approved PDF.',409)
    artifact=InvoiceArtifact.objects.filter(invoice=row).first()
    if not artifact or artifact.snapshot_sha256!=row.document_sha256:
        raise DomainError('invoice_not_ready','This invoice has no approved rendered document yet.',409)
    return artifact


@json_endpoint(('GET',))
def list_invoices(request):
    from core.pagination import paginate_queryset
    page=paginate_queryset(request,owned_queryset(request.user),'invoices',ordering='-issued_at')
    page['items']=[invoice_data(row) for row in page['items']]
    return api_response(page)


@json_endpoint(('GET',))
def get_invoice(request,invoice_id):
    return api_response(invoice_data(own_invoice(request.user,invoice_id)))


@json_endpoint(('POST',))
def download_invoice(request,invoice_id):
    if request.body:
        json_body(request,set())
    row=own_invoice(request.user,invoice_id)
    selected_revision=row.current_revision.sequence if row.current_revision_id else row.revision
    if request.headers.get('If-Match') and expected_version(request)!=selected_revision:raise DomainError('version_conflict','Invoice document changed.',412)
    artifact=ready_artifact(row)
    from library import storage
    now=timezone.now()
    if storage.is_r2():
        # Binding already independently verified the immutable object; mint only
        # after a fresh ownership check, without proxying the document through app.
        url=storage.private_url(artifact.storage_key,GRANT_SECONDS,'application/pdf')
    else:
        token=signing.dumps({'invoice':str(row.id),'member':str(request.user.public_id),
            'device':str(getattr(getattr(request,'device',None),'id','')),'sha256':artifact.sha256},salt=GRANT_SALT,compress=True)
        url=request.build_absolute_uri(f'/api/v1/commerce/invoices/{row.id}/file?token={token}')
    response=api_response({'url':url,'expires_at':iso(now+timedelta(seconds=GRANT_SECONDS)),
        'sha256':artifact.sha256,'bytes':artifact.bytes,'content_type':'application/pdf','revision':selected_revision,**({'document_id':str(row.current_revision_id)} if row.current_revision_id else {})})
    response['Referrer-Policy']='no-referrer'
    return response


@json_endpoint(('GET',))
def invoice_file(request,invoice_id):
    row=own_invoice(request.user,invoice_id)
    artifact=ready_artifact(row)
    if not settings.LOCAL:
        raise DomainError('not_found','Request a private download grant.',404)
    try:
        data=signing.loads(request.GET.get('token',''),salt=GRANT_SALT,max_age=GRANT_SECONDS)
        expected={'invoice':str(row.id),'member':str(request.user.public_id),
            'device':str(getattr(getattr(request,'device',None),'id','')),'sha256':artifact.sha256}
        if data!=expected:
            raise signing.BadSignature
    except signing.BadSignature:
        raise DomainError('invoice_download_expired','Request a new private invoice download.',410)
    from library import storage
    storage.verify_private(artifact.storage_key,artifact.bytes,artifact.sha256,'application/pdf')
    response=FileResponse(storage._local_path(artifact.storage_key).open('rb'),as_attachment=True,
        filename=f'earnalism-invoice-{row.id}.pdf',content_type='application/pdf')
    response['Cache-Control']='private, no-store'
    response['Referrer-Policy']='no-referrer'
    response['X-Content-Type-Options']='nosniff'
    return response
