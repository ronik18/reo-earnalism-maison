"""Institution (school) yearly invoices: a request for payment, never a card checkout.

Live institution invoices await an approved institution tax rule; only local test documents are issued."""
import uuid
from datetime import date,timedelta
from io import StringIO
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError,transaction
from django.test import TestCase,override_settings
from django.utils import timezone
from core.api import DomainError
from .institution import issue_institution_invoice
from .invoices import owned_queryset
from .models import Invoice,InstitutionAccount,Offer,Order,Payment,PaymentAllocation

PDF=b'%PDF-1.4\nSynthetic institution fixture\n%%EOF'


class InstitutionInvoiceTests(TestCase):
    def setUp(self):
        User=get_user_model()
        self.staff=User.objects.create_superuser('inst-approver@example.test','Local-Approver-Test-Strong47')
        self.plain=User.objects.create_user('inst-member@example.test','Fixture-Password-47')
        render=patch('billing.documents.render_pdf',return_value=PDF);render.start();self.addCleanup(render.stop)
    def issue(self,**kw):
        data=dict(institution='Greenfield School',classes=3,students=90,price_per_student_minor=20000,period_start=date(2027,4,1));data.update(kw)
        return issue_institution_invoice(self.staff,**data)
    def test_local_test_document_series_and_totals(self):
        invoice=self.issue()
        self.assertEqual(invoice.amount_minor,90*20000);self.assertEqual(invoice.currency,'INR')
        self.assertTrue(invoice.number.startswith('LOCAL-TEST-'))
        self.assertIsNone(invoice.order_id);self.assertIsNone(invoice.subscription_id)
        self.assertEqual(invoice.institution.name,'Greenfield School')
        self.assertEqual((invoice.period_start.date(),invoice.period_end.date()),(date(2027,4,1),date(2028,4,1)))
        snap=invoice.line_snapshot
        self.assertEqual((snap['institution'],snap['classes'],snap['students'],snap['unit_price_minor'],snap['period_start'],snap['period_end']),('Greenfield School',3,90,20000,'2027-04-01','2028-04-01'))
        self.assertTrue(snap['local_test_document'])
        invoice.refresh_from_db();self.assertIsNotNone(invoice.current_revision_id);self.assertEqual(invoice.current_revision.kind,'invoice');self.assertTrue(invoice.current_revision.storage_key)
        self.assertEqual(self.issue().institution_id,invoice.institution_id);self.assertEqual(InstitutionAccount.objects.count(),1)
        self.assertFalse(PaymentAllocation.objects.exists())
    def test_database_rejects_a_payment_allocation_to_an_institution_invoice(self):
        invoice=self.issue()
        offer=Offer.objects.create(code='inst-alloc',name='Original test-only offer',currency='INR',price_minor=invoice.amount_minor,duration_seconds=86400,formats=['reader'],terms_version='synthetic',test_only=True)
        order=Order.objects.create(user=self.plain,offer=offer,total_minor=invoice.amount_minor,currency='INR',offer_snapshot={},operation_id=uuid.uuid4(),request_sha256='0'*64,expires_at=timezone.now()+timedelta(hours=1))
        payment=Payment.objects.create(order=order,provider='local_test',provider_payment_id='inst-alloc-payment',amount_minor=invoice.amount_minor,currency='INR',status='captured',captured_at=timezone.now(),verification_source='local_test',evidence_sha256='2'*64)
        with self.assertRaises(IntegrityError),transaction.atomic():
            PaymentAllocation.objects.create(payment=payment,invoice=invoice,amount_minor=100)
        self.assertFalse(PaymentAllocation.objects.exists())
    def test_zero_students_refused(self):
        for bad in ({'students':0},{'classes':0},{'price_per_student_minor':0},{'students':-1},{'institution':'  '}):
            with self.assertRaises(DomainError):self.issue(**bad)
        self.assertFalse(Invoice.objects.exists())
    def test_invoice_requires_finance_permission(self):
        with self.assertRaises(DomainError) as caught:issue_institution_invoice(self.plain,institution='X',classes=1,students=1,price_per_student_minor=1,period_start=date(2027,4,1))
        self.assertEqual(caught.exception.status,403);self.assertFalse(Invoice.objects.exists());self.assertFalse(InstitutionAccount.objects.exists())
    def test_institution_invoices_never_appear_in_member_lists(self):
        self.issue()
        for user in (self.plain,self.staff):self.assertFalse(owned_queryset(user).exists())
    def test_exactly_one_source_is_enforced_by_the_database(self):
        invoice=self.issue()
        with self.assertRaises(IntegrityError),transaction.atomic():
            Invoice.objects.create(number='NOSRC',amount_minor=1,currency='INR',line_snapshot={},document_sha256='a'*64,issued_at=invoice.issued_at)
    def test_command_requires_staff_and_uses_default_price(self):
        out=StringIO()
        call_command('institution_invoice',institution='Hill School',classes=2,students=40,period_start='2027-04-01',by='inst-approver@example.test',stdout=out)
        invoice=Invoice.objects.get(institution__name='Hill School');self.assertEqual(invoice.amount_minor,40*20000);self.assertIn(invoice.number,out.getvalue())
        with self.assertRaises(CommandError):call_command('institution_invoice',institution='Hill School',classes=2,students=40,period_start='2027-04-01',by='inst-member@example.test',stdout=StringIO())

    def test_refused_outside_local_environment(self):
        with override_settings(LOCAL=False):
            with self.assertRaises(DomainError) as caught:self.issue()
        self.assertEqual((caught.exception.code,caught.exception.status),('finance_policy_required',409))
        self.assertFalse(Invoice.objects.exists());self.assertFalse(InstitutionAccount.objects.exists())
    def test_refused_when_finance_policy_is_approved(self):
        with override_settings(MERCHANT_FINANCE_POLICY={'approved':True,'version':'x'}):
            with self.assertRaises(DomainError) as caught:self.issue()
        self.assertEqual((caught.exception.code,caught.exception.status),('finance_policy_required',409))
        self.assertFalse(Invoice.objects.exists());self.assertFalse(InstitutionAccount.objects.exists())
    def test_account_lookup_is_case_insensitive(self):
        a=self.issue();b=self.issue(institution='  GREENFIELD school ')
        self.assertEqual(a.institution_id,b.institution_id);self.assertEqual(InstitutionAccount.objects.count(),1)
