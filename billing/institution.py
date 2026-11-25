"""Yearly per-class institution invoices: a request for payment, never a card checkout.

Live institution invoices await an approved institution tax/numbering rule: outside the local/test
environment (settings.LOCAL false) or whenever settings.MERCHANT_FINANCE_POLICY is approved, issuing is
refused with finance_policy_required. Only in the local environment is a LOCAL-TEST-INST test document made. Payment recording
for institutions is out of scope: nothing here creates an Order, Payment or PaymentAllocation.
"""
import hashlib
import json
import uuid
from datetime import date,datetime,time,timezone as dtz
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from core.api import DomainError
from core.services import audit
from .models import Invoice,InstitutionAccount


def _year_later(day):
    try:return day.replace(year=day.year+1)
    except ValueError:return day.replace(year=day.year+1,day=28)  # 29 February


def issue_institution_invoice(actor,*,institution,classes,students,price_per_student_minor,period_start):
    from .documents import permission,issue_document,initialize_invoice
    permission(actor)
    name=institution.strip() if isinstance(institution,str) else ''
    if not 1<=len(name)<=200:raise DomainError('validation_error','An institution name of at most 200 characters is required.',422)
    for value in (classes,students,price_per_student_minor):
        if type(value) is not int or value<=0:raise DomainError('validation_error','Classes, students and price per student must be positive whole numbers.',422)
    if not isinstance(period_start,date) or isinstance(period_start,datetime):raise DomainError('validation_error','A period start date is required.',422)
    policy=getattr(settings,'MERCHANT_FINANCE_POLICY',None)
    if not settings.LOCAL or (isinstance(policy,dict) and policy.get('approved') is True):
        raise DomainError('finance_policy_required','No approved tax and numbering rule exists for institution invoices.',409)
    period_end=_year_later(period_start);total=students*price_per_student_minor
    with transaction.atomic():
        account=InstitutionAccount.objects.filter(name__iexact=name).first()
        if not account:account=InstitutionAccount.objects.create(name=name,created_by=actor)
        invoice_id=uuid.uuid4();now=timezone.now()
        snapshot={'institution':name,'institution_id':str(account.pk),'classes':classes,'students':students,'unit_price_minor':price_per_student_minor,
            'period_start':period_start.isoformat(),'period_end':period_end.isoformat(),'amount_minor':total,'currency':'INR','issued_at':now.isoformat(),
            'recipient':{'name':name,'email':account.contact_email},'local_test_document':True,'sandbox':False}
        invoice=Invoice.objects.create(id=invoice_id,institution=account,number=f'LOCAL-TEST-INST-{invoice_id}',amount_minor=total,currency='INR',line_snapshot=snapshot,
            document_sha256=hashlib.sha256(json.dumps(snapshot,sort_keys=True).encode()).hexdigest(),issued_at=now,
            period_start=datetime.combine(period_start,time.min,dtz.utc),period_end=datetime.combine(period_end,time.min,dtz.utc))
        document=initialize_invoice(invoice)
        issue_document(actor,invoice.pk,{'reason':'Institution yearly invoice','issuer_version':'local-test'},document.sequence,uuid.uuid4())
        audit(actor,'institution.invoice_issued',invoice,{'institution':name,'amount_minor':total})
    invoice.refresh_from_db()
    return invoice
