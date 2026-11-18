"""Isolated synthetic history/document tests, never finance or merchant acceptance."""
import hashlib
import json
import tempfile
import uuid
from datetime import timedelta
from urllib.parse import urlsplit,parse_qs
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError,transaction
from django.test import TestCase,Client,RequestFactory,override_settings
from django.utils import timezone
from library.validation import validate_schema
from library import storage
from .models import Offer,Order,Invoice,Payment,PaymentAllocation,Refund,InvoiceArtifact
from .invoices import bind_artifact,invoice_data
from core.api import DomainError


class InvoiceHistoryTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media=tempfile.TemporaryDirectory(prefix='maison-invoice-test-')
        cls.override=override_settings(MEDIA_ROOT=cls.media.name,MEDIA_STORAGE_BACKEND='local',LOCAL=True,
            FEATURES={**settings.FEATURES,'recurring_billing':False})
        cls.override.enable();super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass();cls.override.disable();cls.media.cleanup()

    def setUp(self):
        self.user=get_user_model().objects.create_user('invoice-owner@example.test','Invoice-local-test-Strong47',is_verified=True)
        self.other=get_user_model().objects.create_user('invoice-other@example.test','Invoice-local-test-Strong47',is_verified=True)
        self.finance=get_user_model().objects.create_superuser('invoice-finance@example.test','Invoice-local-test-Strong47')
        self.offer=Offer.objects.create(code='invoice-local',name='Original test-only offer',currency='INR',price_minor=100,
            duration_seconds=86400,formats=['reader'],terms_version='synthetic',test_only=True)
        self.login(self.client,self.user)

    def login(self,client,user):
        response=client.get('/api/v1/session')
        token=response.json()['csrf_token']
        result=client.post('/api/v1/auth/login',json.dumps({'email':user.email,'password':'Invoice-local-test-Strong47'}),
            content_type='application/json',HTTP_X_CSRFTOKEN=token)
        self.assertEqual(result.status_code,200)

    def invoice(self,user=None,number=None):
        order=Order.objects.create(user=user or self.user,offer=self.offer,total_minor=100,currency='INR',offer_snapshot={},
            operation_id=uuid.uuid4(),request_sha256='0'*64,expires_at=timezone.now()+timedelta(hours=1))
        return Invoice.objects.create(order=order,number=number or 'TEST-'+str(uuid.uuid4()),amount_minor=100,currency='INR',
            document_sha256='1'*64,line_snapshot={'synthetic':True},issued_at=timezone.now())

    def artifact(self,row):
        # Deliberately synthetic bytes for transport tests, not a tax invoice.
        raw=b'%PDF-1.4\nSynthetic local invoice transport fixture only.\n%%EOF\n'
        sha=hashlib.sha256(raw).hexdigest();key=f'exports/invoices/{row.id}/{sha}.pdf'
        storage.put_private(key,raw,'application/pdf')
        return bind_artifact(self.finance,row.id,storage_key=key,sha256=sha,bytes=len(raw),issuer_version='synthetic-local-approval'),raw

    def post(self,path,client=None):
        return (client or self.client).post(path,'{}',content_type='application/json')

    def test_history_detail_and_download_denials_are_owned_even_with_recurring_off(self):
        row=self.invoice();foreign=self.invoice(self.other)
        self.assertEqual(self.client.get('/api/v1/commerce/invoices/'+str(row.id)).status_code,200)
        response=self.client.get('/api/v1/commerce/invoices')
        self.assertEqual(response.status_code,200);validate_schema(response.json(),'InvoicePage')
        self.assertEqual([x['invoice_id'] for x in response.json()['items']],[str(row.id)])
        for path,method in [(str(foreign.id),'get'),(str(foreign.id)+'/download','post'),(str(uuid.uuid4()),'get')]:
            result=self.post('/api/v1/commerce/invoices/'+path) if method=='post' else self.client.get('/api/v1/commerce/invoices/'+path)
            self.assertEqual(result.status_code,404)
            self.assertIn('no-store',result['Cache-Control'])
        self.client.post('/api/v1/commerce/invoices/'+str(row.id)+'/download','{}',content_type='application/json')
        anonymous=Client()
        self.assertEqual(anonymous.get('/api/v1/commerce/invoices').status_code,401)

    def test_more_than_100_invoices_have_no_omissions_or_cross_member_cursors(self):
        for i in range(105):self.invoice(number='TEST-PAGE-'+str(i))
        ids=[];cursor=None
        while True:
            params={'limit':37}
            if cursor:params['cursor']=cursor
            response=self.client.get('/api/v1/commerce/invoices',params)
            self.assertEqual(response.status_code,200)
            data=response.json();validate_schema(data,'InvoicePage');ids.extend(x['invoice_id'] for x in data['items'])
            cursor=data['next_cursor']
            if not cursor:break
            if len(ids)==37:
                other_client=Client();self.login(other_client,self.other)
                self.assertEqual(other_client.get('/api/v1/commerce/invoices',{'limit':37,'cursor':cursor}).status_code,422)
                self.assertEqual(self.client.get('/api/v1/commerce/invoices',{'limit':38,'cursor':cursor}).status_code,422)
        self.assertEqual(len(ids),105);self.assertEqual(len(set(ids)),105)
        for bad in (0,101,'invalid'):
            self.assertEqual(self.client.get('/api/v1/commerce/invoices',{'limit':bad}).status_code,422)

    def test_missing_document_is_409_not_a_fabricated_pdf(self):
        row=self.invoice()
        response=self.post(f'/api/v1/commerce/invoices/{row.id}/download')
        self.assertEqual(response.status_code,409);self.assertEqual(response.json()['code'],'invoice_not_ready')
        self.assertNotIn('url',response.json())
        self.assertIn('no-store',response['Cache-Control'])

    def test_verified_local_download_is_account_device_and_expiry_bound(self):
        row=self.invoice();artifact,raw=self.artifact(row)
        path=f'/api/v1/commerce/invoices/{row.id}/download'
        response=self.client.generic('POST',path,data=b'');self.assertEqual(response.status_code,200)
        grant=response.json();validate_schema(grant,'PrivateFileGrant');self.assertEqual(grant['sha256'],artifact.sha256)
        self.assertEqual(grant['bytes'],len(raw));self.assertEqual(grant['content_type'],'application/pdf')
        url=urlsplit(grant['url']);file_url=url.path+'?'+url.query
        delivered=self.client.get(file_url)
        self.assertEqual(delivered.status_code,200)
        self.assertEqual(b''.join(delivered.streaming_content),raw)
        self.assertEqual(delivered['Content-Type'],'application/pdf')
        self.assertIn('attachment',delivered['Content-Disposition']);self.assertIn('no-store',delivered['Cache-Control'])
        self.assertEqual(self.client.get(url.path).status_code,410)
        other=Client();self.login(other,self.other)
        self.assertEqual(other.get(file_url).status_code,404)
        same_member_new_device=Client();self.login(same_member_new_device,self.user)
        self.assertEqual(same_member_new_device.get(file_url).status_code,410)
        with patch('django.core.signing.time.time',return_value=timezone.now().timestamp()+121):
            self.assertEqual(self.client.get(file_url).status_code,410)

    def test_artifacts_require_operator_authority_and_exact_immutable_bytes(self):
        row=self.invoice();artifact,raw=self.artifact(row)
        with self.assertRaises(DomainError) as err:
            bind_artifact(self.user,row.id,storage_key=artifact.storage_key,sha256=artifact.sha256,bytes=len(raw),issuer_version='fake')
        self.assertEqual(err.exception.status,403)
        artifact.issuer_version='different'
        with self.assertRaises(ValidationError):artifact.save()
        with self.assertRaises(IntegrityError),transaction.atomic():
            InvoiceArtifact.objects.filter(pk=row.id).update(bytes=1)
        with self.assertRaises(IntegrityError),transaction.atomic():
            InvoiceArtifact.objects.filter(pk=row.id).delete()
        storage._local_path(artifact.storage_key).write_bytes(raw+b'changed')
        grant=self.post(f'/api/v1/commerce/invoices/{row.id}/download').json()
        url=urlsplit(grant['url'])
        bad=self.client.get(url.path+'?'+url.query)
        self.assertEqual(bad.status_code,422)

    def test_paid_and_refund_history_does_not_rewrite_invoice_snapshot(self):
        row=self.invoice()
        payment=Payment.objects.create(order=row.order,provider='local_test',provider_payment_id='synthetic-payment',amount_minor=100,
            currency='INR',status='captured',captured_at=timezone.now(),verification_source='local_test',evidence_sha256='2'*64)
        PaymentAllocation.objects.create(payment=payment,invoice=row,amount_minor=100)
        first=invoice_data(row);self.assertEqual(first['status'],'paid');self.assertEqual(first['paid_amount_minor'],100)
        self.assertEqual(first['refund_status'],'none');validate_schema(first,'Invoice')
        Refund.objects.create(payment=payment,operation_id=uuid.uuid4(),proposed_amount_minor=40,amount_minor=40,currency='INR',reason='synthetic',
            status='processed',approved_by=self.finance,approved_at=timezone.now(),processed_at=timezone.now(),provider_refund_id='synthetic-refund')
        second=invoice_data(row);self.assertEqual(second['paid_amount_minor'],100);self.assertEqual(second['refund_status'],'partial')
        Refund.objects.create(payment=payment,operation_id=uuid.uuid4(),proposed_amount_minor=60,amount_minor=60,currency='INR',reason='synthetic',
            status='processed',approved_by=self.finance,approved_at=timezone.now(),processed_at=timezone.now(),provider_refund_id='synthetic-refund-final')
        full=invoice_data(row);self.assertEqual(full['paid_amount_minor'],100);self.assertEqual(full['refund_status'],'full')
        row.refresh_from_db();self.assertEqual(row.document_sha256,'1'*64);self.assertEqual(row.line_snapshot,{'synthetic':True})

    def test_download_requires_csrf_and_never_enables_remote_artifact_fallback(self):
        row=self.invoice();self.artifact(row)
        secure=Client(enforce_csrf_checks=True);self.login(secure,self.user)
        self.assertEqual(self.post(f'/api/v1/commerce/invoices/{row.id}/download',secure).status_code,403)
        with override_settings(LOCAL=False):
            from .invoices import invoice_file
            request=RequestFactory().get(f'/api/v1/commerce/invoices/{row.id}/file?token=irrelevant');request.user=self.user
            response=invoice_file(request,row.id)
            self.assertEqual(response.status_code,404)


    def test_existing_subscription_invoice_history_has_its_own_owner_and_period(self):
        from .subscription_models import BillingPlan,Subscription
        plan=BillingPlan.objects.create(offer=self.offer,interval_unit='month')
        subscription=Subscription.objects.create(user=self.user,plan=plan)
        start=timezone.now()-timedelta(days=30);end=timezone.now()
        row=Invoice.objects.create(subscription=subscription,number='TEST-SUBSCRIPTION',amount_minor=100,currency='INR',
            document_sha256='3'*64,line_snapshot={'synthetic':True},issued_at=end,period_start=start,period_end=end)
        data=self.client.get('/api/v1/commerce/invoices/'+str(row.id)).json()
        validate_schema(data,'Invoice');self.assertEqual(data['subscription_id'],str(subscription.id));self.assertIsNone(data['order_id'])
        self.assertEqual(data['period_start'],start.isoformat().replace('+00:00','Z'))
        with self.assertRaises(IntegrityError),transaction.atomic():
            Invoice.objects.create(number='TEST-NO-SOURCE',amount_minor=100,currency='INR',document_sha256='3'*64,line_snapshot={},issued_at=end)
        other=Client();self.login(other,self.other)
        self.assertEqual(other.get('/api/v1/commerce/invoices/'+str(row.id)).status_code,404)

    def test_direct_private_delivery_requires_owned_ready_artifact_and_short_grant(self):
        row=self.invoice();artifact,raw=self.artifact(row)
        with patch('library.storage.is_r2',return_value=True),patch('library.storage.private_url',return_value='https://private.example.test/short-lived') as presign:
            response=self.post(f'/api/v1/commerce/invoices/{row.id}/download')
            self.assertEqual(response.status_code,200);validate_schema(response.json(),'PrivateFileGrant')
            presign.assert_called_once_with(artifact.storage_key,120,'application/pdf')
            expiry=__import__('django.utils.dateparse',fromlist=['parse_datetime']).parse_datetime(response.json()['expires_at'])
            self.assertLessEqual((expiry-timezone.now()).total_seconds(),120)
            presign.reset_mock()
            foreign=self.invoice(self.other)
            self.assertEqual(self.post(f'/api/v1/commerce/invoices/{foreign.id}/download').status_code,404)
            presign.assert_not_called()


    def test_allocation_bounds_and_cross_owner_records_are_enforced_in_postgresql(self):
        row=self.invoice();foreign=self.invoice(self.other)
        payment=Payment.objects.create(order=row.order,provider='local_test',provider_payment_id='bounded-payment',amount_minor=100,
            currency='INR',status='captured',captured_at=timezone.now(),verification_source='local_test',evidence_sha256='2'*64)
        with self.assertRaises(IntegrityError),transaction.atomic():
            PaymentAllocation.objects.create(payment=payment,invoice=foreign,amount_minor=100)
        with self.assertRaises(IntegrityError),transaction.atomic():
            PaymentAllocation.objects.create(payment=payment,invoice=row,amount_minor=101)
        allocation=PaymentAllocation.objects.create(payment=payment,invoice=row,amount_minor=100)
        with self.assertRaises(IntegrityError),transaction.atomic():
            PaymentAllocation.objects.filter(pk=allocation.pk).update(amount_minor=50)
        with self.assertRaises(IntegrityError),transaction.atomic():
            PaymentAllocation.objects.filter(pk=allocation.pk).delete()

    def test_split_payment_refund_attribution_never_guesses_an_invoice_refund(self):
        row=self.invoice()
        payment=Payment.objects.create(order=row.order,provider='local_test',provider_payment_id='split-payment',amount_minor=200,
            currency='INR',status='captured',captured_at=timezone.now(),verification_source='local_test',evidence_sha256='2'*64)
        PaymentAllocation.objects.create(payment=payment,invoice=row,amount_minor=100)
        Refund.objects.create(payment=payment,operation_id=uuid.uuid4(),proposed_amount_minor=50,amount_minor=50,currency='INR',reason='synthetic',
            status='processed',approved_by=self.finance,approved_at=timezone.now(),processed_at=timezone.now(),provider_refund_id='split-refund')
        with self.assertRaises(DomainError) as err:invoice_data(row)
        self.assertEqual(err.exception.code,'invoice_reconciliation_required')
        self.assertEqual(err.exception.status,503)


    def test_same_owner_wrong_order_allocation_is_denied_by_db_and_dto(self):
        paid_row=self.invoice();different_order_invoice=self.invoice()
        payment=Payment.objects.create(order=paid_row.order,provider='local_test',provider_payment_id='wrong-order-payment',amount_minor=100,
            currency='INR',status='captured',captured_at=timezone.now(),verification_source='local_test',evidence_sha256='2'*64)
        with self.assertRaises(IntegrityError),transaction.atomic():
            PaymentAllocation.objects.create(payment=payment,invoice=different_order_invoice,amount_minor=100)
        # A retained inconsistent allocation must not be projected as paid history.
        different_order_invoice._prefetched_objects_cache={'paymentallocation_set':[PaymentAllocation(payment=payment,invoice=different_order_invoice,amount_minor=100)]}
        with self.assertRaises(DomainError) as err:invoice_data(different_order_invoice)
        self.assertEqual(err.exception.code,'invoice_reconciliation_required')

    def test_subscription_invoice_requires_exact_payment_linkage_not_shared_offer(self):
        from .subscription_models import BillingPlan,Subscription
        plan=BillingPlan.objects.create(offer=self.offer,interval_unit='month')
        subscription=Subscription.objects.create(user=self.user,plan=plan)
        row=Invoice.objects.create(subscription=subscription,number='TEST-SUBSCRIPTION-SOURCE',amount_minor=100,currency='INR',
            document_sha256='3'*64,line_snapshot={'synthetic':True},issued_at=timezone.now())
        other_offer=Offer.objects.create(code='different-offer',name='Different original test-only offer',currency='INR',price_minor=100,
            duration_seconds=86400,formats=['reader'],terms_version='synthetic',test_only=True)
        order=Order.objects.create(user=self.user,offer=other_offer,total_minor=100,currency='INR',offer_snapshot={},
            operation_id=uuid.uuid4(),request_sha256='0'*64,expires_at=timezone.now()+timedelta(hours=1))
        wrong=Payment.objects.create(order=order,provider='local_test',provider_payment_id='wrong-plan-payment',amount_minor=100,
            currency='INR',status='captured',captured_at=timezone.now(),verification_source='local_test',evidence_sha256='2'*64)
        with self.assertRaises(IntegrityError),transaction.atomic():
            PaymentAllocation.objects.create(payment=wrong,invoice=row,amount_minor=100)
        row._prefetched_objects_cache={'paymentallocation_set':[PaymentAllocation(payment=wrong,invoice=row,amount_minor=100)]}
        with self.assertRaises(DomainError) as err:invoice_data(row)
        self.assertEqual(err.exception.code,'invoice_reconciliation_required')
        row._prefetched_objects_cache={}
        matching=self.invoice().order
        correct=Payment.objects.create(order=matching,provider='local_test',provider_payment_id='matching-plan-payment',amount_minor=100,
            currency='INR',status='captured',captured_at=timezone.now(),verification_source='local_test',evidence_sha256='2'*64)
        # Same member and offer still cannot identify a subscription or cycle.
        with self.assertRaises(IntegrityError),transaction.atomic():
            PaymentAllocation.objects.create(payment=correct,invoice=row,amount_minor=100)
        row._prefetched_objects_cache={'paymentallocation_set':[PaymentAllocation(payment=correct,invoice=row,amount_minor=100)]}
        with self.assertRaises(DomainError) as err:invoice_data(row)
        self.assertEqual(err.exception.code,'invoice_reconciliation_required')
