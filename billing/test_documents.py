"""Immutable document authority; synthetic fixtures do not establish tax compliance."""
import hashlib
import uuid
from unittest.mock import patch
from django.test import TestCase,RequestFactory
from django.db import IntegrityError,transaction
from django.contrib.auth import get_user_model
from core.api import DomainError
from core.models import OperationReceipt
from . import tests as fixtures,services
from .models import Invoice,Refund
from .invoice_models import InvoiceRevision
from .documents import issue_document,initialize_invoice,owned_document,render_pdf

class FinancialDocumentTests(TestCase):
    setUp=fixtures.BillingStateMachineTests.setUp
    order=fixtures.BillingStateMachineTests.order
    facts=fixtures.BillingStateMachineTests.facts
    captured=fixtures.BillingStateMachineTests.captured
    def ready(self):
        order,payment=self.captured();invoice=Invoice.objects.get(order=order);initialize_invoice(invoice);invoice.refresh_from_db()
        return order,payment,invoice
    def render(self):return patch('billing.documents.render_pdf',return_value=b'%PDF-1.4\nSynthetic document authority fixture\n%%EOF')
    def test_invoice_revision_is_append_only_and_reissue_is_current_private_document(self):
        order,payment,invoice=self.ready();original=invoice.current_revision
        with self.render():
            result=issue_document(self.staff,invoice.pk,{'reason':'Correct document layout','issuer_version':'fixture'},1,uuid.uuid4())
        self.assertEqual(result[0],200);invoice.refresh_from_db();self.assertNotEqual(invoice.current_revision_id,original.pk)
        self.assertEqual(invoice.amount_minor,order.total_minor);self.assertEqual(invoice.documents.count(),2)
        from .invoices import ready_artifact
        artifact=ready_artifact(invoice);self.assertEqual(artifact.sha256,invoice.current_revision.document_sha256)
        for change in [lambda:InvoiceRevision.objects.filter(pk=original.pk).update(number='changed'),lambda:InvoiceRevision.objects.filter(pk=original.pk).delete(),lambda:Invoice.objects.filter(pk=invoice.pk).update(current_revision=original)]:
            with self.assertRaises(IntegrityError),transaction.atomic():change()
    def test_credit_note_keeps_payable_pointer_and_exact_refund_link(self):
        order,payment,invoice=self.ready();current=invoice.current_revision_id
        _,proposal=services.request_refund(self.user,order.pk,uuid.uuid4());services.approve_refund(self.staff,proposal['refund_id'],3000,1,uuid.uuid4());services.apply_synthetic_refund(proposal['refund_id'],'local_refund_fixture')
        data={'reason':'Approved partial refund','issuer_version':'fixture','tax_minor':0,'evidence_ref':'internal:fixture-tax'}
        with self.render():result=issue_document(self.staff,invoice.pk,data,1,uuid.uuid4(),refund_id=proposal['refund_id'])
        doc=InvoiceRevision.objects.get(pk=result[1]['credit_note_id']);self.assertEqual(doc.amount_minor,3000);self.assertEqual(doc.kind,'credit_note')
        invoice.refresh_from_db();self.assertEqual(invoice.current_revision_id,current)
        with self.assertRaises(IntegrityError),transaction.atomic():Invoice.objects.filter(pk=invoice.pk).update(current_revision=doc)
        other=get_user_model().objects.create_user('not-owner@example.test','Fixture-Password-47')
        with self.assertRaises(DomainError):owned_document(other,doc.pk)
        self.assertEqual(owned_document(self.user,doc.pk),doc)
    def test_replay_survives_receipt_cleanup_without_another_object_write(self):
        _,_,invoice=self.ready();key=uuid.uuid4();data={'reason':'Approved layout','issuer_version':'fixture'}
        with self.render(),patch('library.storage.put_private',wraps=__import__('library.storage',fromlist=['put_private']).put_private) as writer:
            first=issue_document(self.staff,invoice.pk,data,1,key);OperationReceipt.objects.filter(actor=self.staff,operation_id=key).delete()
            second=issue_document(self.staff,invoice.pk,data,1,key);self.assertEqual(first[1],second[1]);self.assertEqual(writer.call_count,1)
            with self.assertRaises(DomainError):issue_document(self.staff,invoice.pk,{**data,'reason':'changed'},1,key)
    def test_unapproved_and_wrong_refund_or_tax_never_produce_document(self):
        _,_,invoice=self.ready()
        with self.render() as renderer:
            with self.assertRaises(DomainError):issue_document(self.user,invoice.pk,{'reason':'x','issuer_version':'fixture'},1,uuid.uuid4())
            with self.assertRaises(DomainError):issue_document(self.staff,invoice.pk,{'reason':'x','issuer_version':'fixture','tax_minor':True,'evidence_ref':'fixture'},1,uuid.uuid4(),refund_id=uuid.uuid4())
            renderer.assert_not_called()
    def test_database_rejects_amount_change_even_without_service(self):
        _,_,invoice=self.ready()
        with self.assertRaises(IntegrityError),transaction.atomic():
            InvoiceRevision.objects.create(invoice=invoice,kind='invoice',sequence=2,number='invalid-finance',amount_minor=invoice.amount_minor+1,currency=invoice.currency,snapshot={},snapshot_sha256='a'*64,issuer_version='fixture')
    def test_unsupported_legal_unicode_is_explicit_not_silently_lost(self):
        with self.assertRaises(DomainError) as error:render_pdf({'currency':'INR','amount_minor':1,'finance':{'issuer':{'legal_name':'\u0378'},'net_minor':1,'tax_minor':0}},'FIXTURE','invoice')
        self.assertIn(error.exception.code,['document_font_qualification_required','financial_document_glyph_unavailable'])
    def test_actual_pdf_renderer_preserves_english_and_bengali_with_real_money(self):
        raw=render_pdf({'currency':'INR','amount_minor':12345,'issued_at':'2026-11-19T12:00:00Z','recipient':{'name':'বাংলা পাঠক','email':'fixture@example.test'},'finance':{'issuer':{'legal_name':'Fixture publisher','address':'Line one\nLine two'},'net_minor':12000,'tax_minor':345,'tax':{'label':'Approved fixture tax'}}},'TEST-NOT-LEGAL','invoice')
        self.assertTrue(raw.startswith(b'%PDF-'));self.assertGreater(len(raw),5000)
    def test_invoice_grant_checks_selected_revision_before_minting(self):
        _,_,invoice=self.ready()
        with self.render():issue_document(self.staff,invoice.pk,{'reason':'Approved layout','issuer_version':'fixture'},1,uuid.uuid4())
        from .invoices import download_invoice
        request=RequestFactory().post('/',data='{}',content_type='application/json',HTTP_IF_MATCH='"v1"');request.user=self.user
        self.assertEqual(download_invoice(request,invoice.pk).status_code,412)
        request=RequestFactory().post('/',data='{}',content_type='application/json',HTTP_IF_MATCH='"v2"');request.user=self.user
        response=download_invoice(request,invoice.pk);self.assertEqual(response.status_code,200)
        import json
        self.assertEqual(json.loads(response.content)['revision'],2)
    def test_owned_credit_history_serializes_without_per_document_queries(self):
        _,_,invoice=self.ready()
        for index in range(3):
            _,proposal=services.request_refund(self.user,invoice.order_id,uuid.uuid4());services.approve_refund(self.staff,proposal['refund_id'],1000,1,uuid.uuid4());services.apply_synthetic_refund(proposal['refund_id'],f'local_refund_{index}')
            with patch('billing.documents.render_pdf',side_effect=lambda snapshot,number,kind:b'%PDF-1.4\\n'+number.encode()+b'\\n%%EOF'):
                issue_document(self.staff,invoice.pk,{'reason':'Approved partial refund','issuer_version':'fixture','tax_minor':0,'evidence_ref':'internal:fixture'},1,uuid.uuid4(),refund_id=proposal['refund_id'])
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .documents import owned_documents,document_data
        with CaptureQueriesContext(connection) as queries:result=[document_data(row) for row in owned_documents(self.user)]
        self.assertEqual(len(result),3);self.assertEqual(len(queries),1)
    def test_legacy_local_snapshot_gets_authoritative_totals_and_test_marking(self):
        order=self.order()
        from django.utils import timezone
        invoice=Invoice.objects.create(order=order,number='LEGACY-FIXTURE',revision=3,amount_minor=order.total_minor,currency=order.currency,line_snapshot={},document_sha256='a'*64,issued_at=timezone.now())
        with self.render():issue_document(self.staff,invoice.pk,{'reason':'Retained document qualification','issuer_version':'fixture'},3,uuid.uuid4())
        invoice.refresh_from_db();self.assertEqual(invoice.current_revision.snapshot['amount_minor'],invoice.amount_minor)
        self.assertTrue(invoice.current_revision.snapshot['local_test_document'])
    def test_invalid_issuance_does_not_bootstrap_history_or_write_objects(self):
        order=self.order()
        from django.utils import timezone
        invoice=Invoice.objects.create(order=order,number='UNISSUED-FIXTURE',amount_minor=order.total_minor,currency=order.currency,line_snapshot={},document_sha256='a'*64,issued_at=timezone.now())
        with patch('library.storage.put_private') as writer,patch('billing.documents.render_pdf') as renderer:
            for data in [{'reason':'','issuer_version':'fixture'},{'reason':'Approved layout','issuer_version':''},{'reason':'Approved layout','issuer_version':'x'*121}]:
                with self.subTest(data=data),self.assertRaises(DomainError):issue_document(self.staff,invoice.pk,data,1,uuid.uuid4())
            writer.assert_not_called();renderer.assert_not_called()
        invoice.refresh_from_db();self.assertIsNone(invoice.current_revision_id)
        self.assertFalse(InvoiceRevision.objects.filter(invoice=invoice).exists())
    def test_http_invoice_replay_returns_original_dto_status_and_etag_after_later_reissue(self):
        import json
        from django.utils import timezone
        from django.urls import resolve
        from library.validation import validate_schema
        _,_,invoice=self.ready();first_key=uuid.uuid4()
        def post(key,base,reason):
            request=RequestFactory().post(f'/api/v1/staff/invoices/{invoice.id}/issue',data=json.dumps({'reason':reason,'issuer_version':'fixture'}),content_type='application/json',HTTP_IF_MATCH=f'"v{base}"',HTTP_IDEMPOTENCY_KEY=str(key))
            request.user=self.staff;request.session={'reauthenticated_at':timezone.now().isoformat()}
            match=resolve(request.path);return match.func(request,*match.args,**match.kwargs)
        with self.render():
            original=post(first_key,1,'Original approved layout')
            newer=post(uuid.uuid4(),2,'Later approved layout')
        self.assertEqual(original.status_code,200);self.assertEqual(newer.status_code,200)
        original_body=json.loads(original.content);self.assertEqual(original_body['revision'],2)
        validate_schema(original_body,'Invoice');self.assertEqual(json.loads(newer.content)['revision'],3)
        with patch('library.storage.put_private') as writer,patch('billing.documents.render_pdf') as renderer:
            replay=post(first_key,1,'Original approved layout')
            OperationReceipt.objects.filter(actor=self.staff,operation_id=first_key).delete()
            durable_replay=post(first_key,1,'Original approved layout')
            for response in [replay,durable_replay]:
                self.assertEqual(response.status_code,original.status_code)
                self.assertEqual(response['ETag'],original['ETag'])
                self.assertEqual(json.loads(response.content),original_body)
            writer.assert_not_called();renderer.assert_not_called()
