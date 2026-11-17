import hashlib
import hmac
import io
import tempfile
import uuid
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import transaction,IntegrityError
from django.test import TestCase,override_settings
from django.utils import timezone
from core.api import DomainError
from core.models import OutboxJob,OperationReceipt
from library.models import Edition,Rights
from library import services as library
from library.validation import validate_schema
from .models import Offer,Order,Payment,Entitlement,Refund,Invoice
from . import services as svc

class BillingStateMachineTests(TestCase):
    """Synthetic local transaction evidence, never a provider/merchant acceptance claim."""
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.override=override_settings(MEDIA_ROOT=self.directory.name,MAISON_LOCAL_FIXTURES=True,LOCAL=True);self.override.enable();self.addCleanup(self.override.disable)
        call_command('seed_local_pilot',stdout=io.StringIO())
        self.user=get_user_model().objects.create_user('payer@example.test','Local-Payment-Test-Strong47',is_verified=True)
        self.staff=get_user_model().objects.create_superuser('approver@example.test','Local-Approver-Test-Strong47')
        self.edition=Edition.objects.select_related('live_revision').get(pk='20000000-0000-4000-8000-000000000001')
        self.offer=Offer.objects.create(code='local-test-only',name='Synthetic local offer, not a live price',currency='INR',price_minor=10000,
            duration_seconds=86400,formats=['reader'],terms_version='local-synthetic-test',approved=True,active=True,test_only=True,edition=self.edition)

    def order(self):
        status,data=svc.create_local_order(self.user,self.offer,uuid.uuid4(),return_path='/vault/')
        self.assertEqual(status,201);validate_schema(data,'Order')
        return Order.objects.get(pk=data['order_id'])

    def facts(self,order,payment_id='local_payment_001',amount=None,currency='INR',reference=None):
        return svc.CaptureFacts(provider='local_test',payment_id=payment_id,order_reference=reference or str(order.id),
            amount_minor=order.total_minor if amount is None else amount,currency=currency,evidence_sha256=hashlib.sha256(payment_id.encode()).hexdigest())

    def captured(self):
        order=self.order();data=svc.apply_capture(order.id,self.facts(order),event_id='local_event_001')
        self.assertEqual(data['fulfillment_status'],'granted');validate_schema(data,'Order')
        return order,order.payments.get()

    def test_eligible_capture_exactly_once_with_long_lived_financial_identity(self):
        order=self.order();facts=self.facts(order)
        first=svc.apply_capture(order.id,facts,'local_event_001')
        second=svc.apply_capture(order.id,facts,'local_event_001')
        self.assertEqual(first,second);self.assertEqual(order.payments.count(),1);self.assertEqual(order.entitlements.count(),1)
        self.assertTrue(svc.has_entitlement(self.user,self.edition.live_revision))
        self.assertEqual(Invoice.objects.filter(order=order).count(),1)
        OperationReceipt.objects.all().delete()
        self.assertEqual(svc.apply_capture(order.id,facts,'local_event_001'),first)
        ent=order.entitlements.get();validate_schema(svc.entitlement_data(ent),'Entitlement')

    def test_cancelled_expired_or_past_deadline_capture_records_money_without_access(self):
        for index,state in enumerate(('cancelled','expired','past_deadline')):
            order=self.order()
            if state=='past_deadline': order.expires_at=timezone.now()-timedelta(seconds=1)
            else: order.status=state
            order.version+=1;order.save()
            facts=self.facts(order,f'local_late_{index}')
            first=svc.apply_capture(order.id,facts,event_id=f'late_event_{index}')
            self.assertEqual(first['status'],'paid');self.assertEqual(first['payment_status'],'captured')
            self.assertEqual(first['fulfillment_status'],'refund_pending');self.assertEqual(first['entitlement_ids'],[])
            self.assertEqual(svc.apply_capture(order.id,facts,event_id=f'late_event_{index}'),first)
            jobs=OutboxJob.objects.filter(kind='refund_reconcile',payload__payment_id=str(order.payments.get().id))
            self.assertEqual(jobs.count(),1)

    def test_capture_mismatches_never_grant_and_cannot_reassign_payment(self):
        for index,changes in enumerate(({'amount':9000},{'currency':'USD'},{'reference':'unrelated_order'})):
            order=self.order();facts=self.facts(order,f'bad_payment_{index}',**changes)
            data=svc.apply_capture(order.id,facts)
            self.assertEqual(data['fulfillment_status'],'review');self.assertFalse(order.entitlements.exists())
        other=self.order()
        with self.assertRaises(DomainError): svc.apply_capture(other.id,self.facts(other,'bad_payment_0'))

    def test_partial_refund_one_approval_ceiling_receipts_and_immutable_amount(self):
        order,payment=self.captured()
        _,requested=svc.request_refund(self.user,order.id,uuid.uuid4(),'technical_failure','Local synthetic review')
        self.assertIsNone(requested['amount']);validate_schema(requested,'Refund')
        key=uuid.uuid4();status,approved=svc.approve_refund(self.staff,requested['refund_id'],3000,1,key)
        self.assertEqual(approved['amount']['amount_minor'],3000);self.assertEqual(approved['status'],'approved')
        self.assertEqual(svc.approve_refund(self.staff,requested['refund_id'],3000,1,key),(status,approved))
        with self.assertRaises(DomainError):svc.approve_refund(self.staff,requested['refund_id'],2000,approved['version'],uuid.uuid4())
        with self.assertRaises(IntegrityError),transaction.atomic():Refund.objects.filter(pk=requested['refund_id']).update(amount_minor=4000)
        processed=svc.apply_synthetic_refund(requested['refund_id'],'local_refund_001')
        self.assertEqual(processed['status'],'processed');payment.refresh_from_db();self.assertEqual(payment.status,'partially_refunded')
        self.assertIsNone(order.entitlements.get().revoked_at)
        _,second=svc.request_refund(self.user,order.id,uuid.uuid4(),'other')
        with self.assertRaises(DomainError):svc.approve_refund(self.staff,second['refund_id'],7001,1,uuid.uuid4())
        svc.approve_refund(self.staff,second['refund_id'],7000,1,uuid.uuid4())
        svc.apply_synthetic_refund(second['refund_id'],'local_refund_002')
        payment.refresh_from_db();self.assertEqual(payment.status,'refunded');self.assertIsNotNone(order.entitlements.get().revoked_at)

    def test_database_refund_reservations_and_financial_snapshot_guards(self):
        order,payment=self.captured()
        _,one=svc.request_refund(self.user,order.id,uuid.uuid4());_,two=svc.request_refund(self.user,order.id,uuid.uuid4())
        svc.approve_refund(self.staff,one['refund_id'],8000,1,uuid.uuid4())
        with self.assertRaises(IntegrityError),transaction.atomic():
            Refund.objects.filter(pk=two['refund_id']).update(amount_minor=3000,status='approved',approved_by=self.staff)
        for model,pk,changes in ((Payment,payment.id,{'amount_minor':1}),(Order,order.id,{'total_minor':1}),(Invoice,Invoice.objects.get(order=order).id,{'amount_minor':1})):
            with self.assertRaises(IntegrityError),transaction.atomic():model.objects.filter(pk=pk).update(**changes)

    def test_real_merchant_operations_are_disabled_and_synthetic_facts_cannot_escape_local(self):
        order=self.order()
        with override_settings(MAISON_LOCAL_FIXTURES=False):
            with self.assertRaises(DomainError):svc.apply_capture(order.id,self.facts(order))
        facts=self.facts(order)
        foreign=svc.CaptureFacts(**{**facts.__dict__,'verification_source':'provider_fetch'})
        with self.assertRaises(DomainError):svc.apply_capture(order.id,foreign)
        response=self.client.post('/api/v1/webhooks/razorpay',b'{}',content_type='application/json')
        self.assertEqual(response.status_code,503)

    def test_hmac_helpers_verify_exact_raw_bytes_but_do_not_grant_access(self):
        secret='local-test-only-not-a-provider-credential'
        data=b'{"event":"payment.captured", "local_test":true}'
        signature=hmac.new(secret.encode(),data,hashlib.sha256).hexdigest()
        svc.verify_webhook_signature(data,signature,[secret])
        with self.assertRaises(DomainError):svc.verify_webhook_signature(data.replace(b' ',b''),signature,[secret])
        callback=hmac.new(secret.encode(),b'order_local|pay_local',hashlib.sha256).hexdigest()
        svc.verify_checkout_signature('order_local','pay_local','order_local',callback,secret)
        with self.assertRaises(DomainError):svc.verify_checkout_signature('order_local','pay_local','order_other',callback,secret)
        self.assertFalse(Payment.objects.exists());self.assertFalse(Entitlement.objects.exists())

    def test_free_offline_entitlement_is_durable_explicit_and_exact_revision(self):
        first=svc.ensure_free_entitlement(self.user,self.edition.live_revision)
        second=svc.ensure_free_entitlement(self.user,self.edition.live_revision)
        self.assertEqual(first.id,second.id);self.assertEqual(first.source,'free');self.assertEqual(first.revision_id,self.edition.live_revision_id)
        validate_schema(svc.entitlement_data(first),'Entitlement')
        with self.assertRaises(DomainError):svc.ensure_free_entitlement(self.user,self.edition.live_revision,'audio')
