"""Finance-approved immutable documents and owned private delivery."""
import hashlib
import io
import json
import uuid
from datetime import timedelta
from django.db import transaction
from django.db.models import Max,Q
from django.utils import timezone
from core.api import DomainError,api_response,json_endpoint,json_body,expected_version,operation_key
from core.services import apply_operation,audit,payload_hash
from core.models import OperationReceipt,OutboxJob
from core.services import OperationResult
from accounts.views import require_fresh
from .models import Invoice,Refund,PaymentAllocation
from .invoice_models import InvoiceRevision


def digest(snapshot):return hashlib.sha256(json.dumps(snapshot,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def render_pdf(snapshot,number,kind):
    from decimal import Decimal
    money=lambda value:f"{snapshot['currency']} {Decimal(value)/Decimal(100):,.2f}"
    lines=[('CREDIT NOTE' if kind=='credit_note' else 'INVOICE'),number]
    finance=snapshot.get('finance',{});issuer=finance.get('issuer',{})
    lines += [str(issuer.get(key,'')) for key in ['legal_name','address','country','tax_id'] if issuer.get(key)]
    if snapshot.get('issued_at'):lines.append('Issue date: '+str(snapshot['issued_at']))
    recipient=snapshot.get('recipient',{})
    if recipient:lines.append('Recipient account: '+', '.join(str(recipient[key]) for key in ['name','email','member_id'] if recipient.get(key)))
    tax=finance.get('tax',{})
    if kind=='credit_note':net=snapshot['net_minor'];tax_amount=snapshot['tax_minor']
    elif finance:
        if type(finance.get('net_minor')) is not int or type(finance.get('tax_minor')) is not int:raise DomainError('finance_policy_required','Exact approved document tax totals are required.',409)
        net=finance['net_minor'];tax_amount=finance['tax_minor']
    else:net=snapshot['amount_minor'];tax_amount=0
    lines += ['Net: '+money(net),'Tax ('+str(tax.get('label','test-only amount'))+'): '+money(tax_amount),'Total: '+money(snapshot['amount_minor'])]
    for component in tax.get('components',[]) if kind=='invoice' else []:
        lines.append(str(component['label'])+': '+money(component['tax_minor'])+(f" at {Decimal(component['rate_bps'])/Decimal(100):.2f}%" if 'rate_bps' in component else ''))
    for key in ['order_id','invoice_number','refund_id','reason']:
        if snapshot.get(key):lines.append(key.replace('_',' ').title()+': '+str(snapshot[key]))
    if snapshot.get('local_test_document'):lines.insert(1,'TEST DOCUMENT - NOT A TAX INVOICE')
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
    except ImportError as exc:raise DomainError('document_renderer_unavailable','The qualified PDF renderer is unavailable.',503) from exc
    try:
        from .pdf_fonts import draw_text,text_width
    except ImportError:
        if any(not line.isascii() for line in lines):raise DomainError('document_font_qualification_required','Qualified embedded fonts are required for these document characters.',409)
        from reportlab.pdfbase.pdfmetrics import stringWidth
        def draw_text(pdf,text,x,y,font_size=11):pdf.setFont('Helvetica',font_size);pdf.drawString(x,y,text)
        def text_width(text,font_size=11):return stringWidth(text,'Helvetica',font_size)
    output=io.BytesIO();pdf=canvas.Canvas(output,pagesize=A4,invariant=1)
    pdf.setTitle(('Credit note ' if kind=='credit_note' else 'Invoice ')+number)
    y=795
    import regex
    lines=[paragraph for line in lines for paragraph in str(line).splitlines()]
    for line in lines:
        pending=''
        for character in regex.findall(r'\X',line):
            if pending and text_width(pending+character,11)>490:
                if y<55:pdf.showPage();y=795
                draw_text(pdf,pending,50,y,11);y-=19;pending=''
            pending+=character
        if y<55:pdf.showPage();y=795
        draw_text(pdf,pending,50,y,11);y-=19
    pdf.save();return output.getvalue()


def permission(actor):
    if not actor.is_active or not actor.is_staff or not actor.has_perm('billing.issue_financial_document'):
        raise DomainError('permission_denied','Finance document issuance permission is required.',403)


def initialize_invoice(invoice):
    """Initial historical snapshot, no PDF/legal approval inferred."""
    with transaction.atomic():
        row=Invoice.objects.select_for_update().get(pk=invoice.pk)
        if row.current_revision_id:return row.current_revision
        document=InvoiceRevision.objects.create(invoice=row,kind='invoice',sequence=row.revision,number=row.number,amount_minor=row.amount_minor,currency=row.currency,snapshot=row.line_snapshot,snapshot_sha256=digest(row.line_snapshot),issuer_version='retained-original-snapshot')
        Invoice.objects.filter(pk=row.pk).update(current_revision=document)
        return document


def issue_document(actor,invoice_id,data,base,key,refund_id=None):
    permission(actor)
    invoice=Invoice.objects.select_related('order','subscription__plan__offer').filter(pk=invoice_id).first()
    if not invoice:raise DomainError('not_found','Invoice not found.',404)
    request_payload={'invoice_id':str(invoice.id),'refund_id':str(refund_id) if refund_id else None,'version':base,**data}
    request_digest=payload_hash('finance.document.issue',request_payload)
    old=OperationReceipt.objects.filter(actor=actor,operation_id=key).first()
    if old:
        if old.kind!='finance.document.issue' or old.request_sha256!=request_digest:raise DomainError('idempotency_key_reused','Financial document input changed.',409)
        return OperationResult(old.http_status,old.response,True)
    doc_id=uuid.UUID(bytes=uuid.uuid5(uuid.NAMESPACE_URL,f'maison-financial-document:{actor.pk}:{key}').bytes,version=4)
    prior=InvoiceRevision.objects.filter(pk=doc_id).first()
    if prior:
        if prior.snapshot.get('_issuance',{}).get('request_sha256')!=request_digest:raise DomainError('idempotency_key_reused','Financial document input changed.',409)
        if prior.kind=='invoice':
            response=prior.snapshot.get('_issuance',{}).get('response')
            if not response:raise DomainError('finance_document_replay_unavailable','The original invoice response requires finance reconciliation.',409)
            return OperationResult(response['status'],response['body'],True)
        return OperationResult(201,document_data(prior),True)
    if not isinstance(data.get('reason'),str) or not 1<=len(data['reason'].strip())<=500:raise DomainError('validation_error','A bounded finance reason is required.',422)
    snapshot=dict(invoice.line_snapshot);finance=snapshot.get('finance',{})
    if invoice.institution_id:live=snapshot.get('local_test_document') is False  # mode retained at issue from MERCHANT_FINANCE_POLICY['approved']
    else:live=not invoice.order.test_only if invoice.order_id else not invoice.subscription.plan.offer.test_only
    if snapshot.get('amount_minor',invoice.amount_minor)!=invoice.amount_minor or snapshot.get('currency',invoice.currency)!=invoice.currency:raise DomainError('finance_policy_required','Retained document totals do not match the immutable invoice.',409)
    snapshot.update(amount_minor=invoice.amount_minor,currency=invoice.currency,local_test_document=not live)
    issuer_version=data.get('issuer_version')
    if not isinstance(issuer_version,str) or not 1<=len(issuer_version.strip())<=120:raise DomainError('validation_error','Approved issuer version is required.',422)
    if live and (not finance or issuer_version!=finance.get('version')):raise DomainError('finance_policy_required','Issuer version must match the retained finance approval.',409)
    kind='credit_note' if refund_id else 'invoice';refund=None
    if refund_id:
        refund=Refund.objects.select_related('payment').filter(pk=refund_id).first()
        if not refund or refund.status!='processed' or not PaymentAllocation.objects.filter(payment=refund.payment,invoice=invoice,amount_minor=refund.payment.amount_minor).exists():raise DomainError('refund_unavailable','Credit notes require a processed refund allocated to this invoice.',409)
        if InvoiceRevision.objects.filter(refund=refund).exists():raise DomainError('credit_note_exists','This processed refund already has an immutable credit note.',409)
        tax=data.get('tax_minor');evidence=data.get('evidence_ref')
        if type(tax)!=int or not 0<=tax<=refund.amount_minor or not isinstance(evidence,str) or not evidence.strip() or len(evidence)>500:raise DomainError('validation_error','Exact approved refund tax and internal evidence are required.',422)
        if live:
            from .numbering import forecast
            number,number_expected=forecast(finance,'credit_note',refund.pk)
        else:number='TEST-CREDIT-'+str(refund.pk);number_expected=None
        snapshot={'invoice_id':str(invoice.pk),'invoice_number':invoice.number,'refund_id':str(refund.pk),'amount_minor':refund.amount_minor,'currency':refund.currency,'net_minor':refund.amount_minor-tax,'tax_minor':tax,'reason':data['reason'].strip(),'evidence_ref':evidence,'finance':finance,'local_test_document':not live,'issued_at':timezone.now().isoformat(),'recipient':invoice.line_snapshot.get('recipient',{})}
    else:
        number=invoice.number
    # Stable operation UUID and content identity make a retry's private write safe.
    snapshot.setdefault('issued_at',invoice.issued_at.isoformat())
    snapshot['_issuance']={'request_sha256':request_digest,'reason':data['reason'].strip()}
    candidate_sequence=(invoice.documents.aggregate(n=Max('sequence'))['n'] or invoice.revision)+1
    raw=render_pdf(snapshot,number,kind);sha=hashlib.sha256(raw).hexdigest();storage_key=f'exports/invoices/{invoice.id}/{doc_id}/{sha}.pdf'
    from library import storage
    storage.put_private(storage_key,raw,'application/pdf')
    storage.verify_private(storage_key,len(raw),sha,'application/pdf')
    def execute():
        # Consistent financial lock order, then immutable document authority.
        if invoice.order_id:
            from .models import Order
            Order.objects.select_for_update().get(pk=invoice.order_id)
        if refund:
            from .models import Payment
            Payment.objects.select_for_update().get(pk=refund.payment_id)
        row=Invoice.objects.select_for_update().get(pk=invoice.pk)
        current=InvoiceRevision.objects.get(pk=row.current_revision_id) if row.current_revision_id else initialize_invoice(row)
        row.current_revision=current
        if current.sequence!=base:raise DomainError('version_conflict','Invoice document changed.',412)
        if (row.documents.aggregate(n=Max('sequence'))['n'] or 0)+1!=candidate_sequence:raise DomainError('version_conflict','Financial document history changed.',412)
        if refund:
            if row.documents.filter(refund=refund).exists():raise DomainError('credit_note_exists','This refund already has a credit note.',409)
            previous_tax=sum(doc.snapshot.get('tax_minor',0) for doc in row.documents.filter(kind='credit_note'))
            approved_tax=row.line_snapshot.get('finance',{}).get('tax_minor',0)
            if previous_tax+snapshot['tax_minor']>approved_tax:raise DomainError('finance_policy_required','Credit-note tax exceeds the immutable approved invoice tax.',409)
            locked=Refund.objects.select_for_update().get(pk=refund.pk)
            if locked.status!='processed' or locked.amount_minor!=snapshot['amount_minor']:raise DomainError('refund_unavailable','Refund financial state changed.',409)
        if refund and live:
            from .numbering import reserve
            reserved=reserve(finance,'credit_note',refund.pk,expected=number_expected)
            if reserved!=number:raise DomainError('version_conflict','Fiscal-year document number changed; retry.',412)
        if kind=='invoice':
            from .invoices import invoice_data
            public=invoice_data(row)
            public.update(revision=candidate_sequence,number=number)
            snapshot['_issuance']['response']={'status':200,'body':public,'version':candidate_sequence}
        document=InvoiceRevision.objects.create(id=doc_id,invoice=row,kind=kind,sequence=candidate_sequence,refund=refund,number=number,amount_minor=snapshot['amount_minor'],currency=row.currency,snapshot=snapshot,snapshot_sha256=digest(snapshot),storage_key=storage_key,document_sha256=sha,bytes=len(raw),issuer_version=issuer_version,approved_by=actor)
        if kind=='invoice':Invoice.objects.filter(pk=row.pk).update(current_revision=document)
        if refund:OutboxJob.objects.filter(dedupe_key=f'credit-note:{refund.id}',status='blocked').update(status='done',error_code='',completed_at=timezone.now(),result={'credit_note_id':str(document.id)})
        audit(actor,'finance.document_issued',document,{'kind':kind,'invoice_id':str(row.pk),'sha256':sha,'reason':data['reason'].strip()})
        if kind=='invoice':return 200,public,document.sequence
        return 201,document_data(document),document.sequence
    return apply_operation(actor,key,'finance.document.issue',request_payload,execute)


def document_data(row):
    return {'credit_note_id':str(row.pk),'invoice_id':str(row.invoice_id),'number':row.number,'invoice_number':row.snapshot.get('invoice_number') or row.invoice.number,'status':'issued','amount':{'amount_minor':row.amount_minor,'currency':row.currency},'issued_at':row.created_at.isoformat().replace('+00:00','Z'),'revision':row.sequence,'reason':row.snapshot.get('reason',''),'refund_id':str(row.refund_id) if row.refund_id else None}


def owned_documents(user):
    if not user.is_active:raise DomainError('authentication_required','Sign in to continue.',401)
    return InvoiceRevision.objects.filter(kind='credit_note').filter(Q(invoice__order__user=user)|Q(invoice__subscription__user=user)).select_related('invoice')


def owned_document(user,document_id):
    row=owned_documents(user).filter(pk=document_id).first()
    if not row:raise DomainError('not_found','Credit note not found.',404)
    return row


@json_endpoint(('GET',))
def list_credit_notes(request):
    from core.pagination import paginate_queryset
    page=paginate_queryset(request,owned_documents(request.user),'credit-notes',ordering='-created_at')
    page['items']=[document_data(row) for row in page['items']];return api_response(page)

@json_endpoint(('GET',))
def get_credit_note(request,credit_note_id):return api_response(document_data(owned_document(request.user,credit_note_id)))

@json_endpoint(('POST',))
def download_credit_note(request,credit_note_id):
    if request.body:json_body(request,set())
    row=owned_document(request.user,credit_note_id)
    if not row.storage_key:raise DomainError('invoice_not_ready','Credit note PDF is unavailable.',409)
    from library import storage
    if not storage.is_r2():
        from django.core import signing
        token=signing.dumps({'document':str(row.pk),'member':str(request.user.public_id),'sha256':row.document_sha256},salt='maison-credit-note-v1')
        url=request.build_absolute_uri(f'/api/v1/commerce/credit-notes/{row.id}/file?token={token}')
    else:url=storage.private_url(row.storage_key,120,'application/pdf')
    return api_response({'url':url,'expires_at':(timezone.now()+timedelta(seconds=120)).isoformat().replace('+00:00','Z'),'sha256':row.document_sha256,'bytes':row.bytes,'content_type':'application/pdf','revision':row.sequence,'document_id':str(row.id)})

@json_endpoint(('GET',))
def credit_note_file(request,credit_note_id):
    from django.conf import settings
    from django.core import signing
    from django.http import FileResponse
    row=owned_document(request.user,credit_note_id)
    if not settings.LOCAL:raise DomainError('not_found','Request a private download grant.',404)
    try:
        value=signing.loads(request.GET.get('token',''),salt='maison-credit-note-v1',max_age=120)
        if value!={'document':str(row.pk),'member':str(request.user.public_id),'sha256':row.document_sha256}:raise signing.BadSignature
    except signing.BadSignature:raise DomainError('invoice_download_expired','Request a new private download.',410)
    from library import storage
    storage.verify_private(row.storage_key,row.bytes,row.document_sha256,'application/pdf')
    response=FileResponse(storage._local_path(row.storage_key).open('rb'),as_attachment=True,filename=row.number+'.pdf',content_type='application/pdf')
    response['Cache-Control']='private, no-store';response['Referrer-Policy']='no-referrer';response['X-Content-Type-Options']='nosniff'
    return response

@json_endpoint(('POST',))
def issue_invoice(request,invoice_id):
    from library.validation import body
    require_fresh(request);data=body(request,'FinancialDocumentIssueInput')
    status,result=issue_document(request.user,invoice_id,data,expected_version(request),operation_key(request))
    return api_response(result,status,version=result['revision'])

@json_endpoint(('POST',))
def issue_credit_note(request,refund_id):
    from library.validation import body
    require_fresh(request);data=body(request,'CreditNoteIssueInput')
    invoice_id=PaymentAllocation.objects.filter(payment__refunds__pk=refund_id).values_list('invoice_id',flat=True).first()
    if not invoice_id:raise DomainError('refund_unavailable','No allocated invoice supports this refund.',409)
    status,result=issue_document(request.user,invoice_id,data,expected_version(request),operation_key(request),refund_id=refund_id);return api_response(result,status)
