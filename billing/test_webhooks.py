"""Authenticated sandbox contract tests; never contact a merchant or charge money."""
import hashlib
import hmac
import json
import uuid
from unittest.mock import patch
from django.test import TestCase,RequestFactory,override_settings
from django.db import OperationalError
from django.urls import resolve
from django.utils import timezone
from core.api import DomainError
from core.models import OutboxJob,AuditEvent,OperationReceipt
from .models import Order,Payment,PaymentEvent,Entitlement
from . import tests as existing_tests
from .checkout import process_payment_event,process_order_reconcile,request_order_reconciliation
from . import services,views


@override_settings(RAZORPAY_ENABLED=True,RAZORPAY_MODE='test',RAZORPAY_KEY_ID='rzp_test_fixture',RAZORPAY_KEY_SECRET='fixture-secret',MERCHANT_ENTITY_CONFIG_VERSION='sandbox-fixture',RAZORPAY_WEBHOOK_SECRETS=['fixture-webhook-secret'])
class DurableWebhookTests(TestCase):
    setUp=existing_tests.BillingStateMachineTests.setUp
    order=existing_tests.BillingStateMachineTests.order
    facts=existing_tests.BillingStateMachineTests.facts
    captured=existing_tests.BillingStateMachineTests.captured

    def send(self,data,event_id='fixture-event'):
        raw=json.dumps(data,separators=(',',':')).encode()
        signature=hmac.new(b'fixture-webhook-secret',raw,hashlib.sha256).hexdigest()
        return self.client.post('/api/v1/webhooks/razorpay',raw,content_type='application/json',HTTP_X_RAZORPAY_SIGNATURE=signature,HTTP_X_RAZORPAY_EVENT_ID=event_id)

    def test_unknown_and_incomplete_events_have_durable_receipts_without_private_payload(self):
        raw={'event':'unsupported.fixture','contact':'private@example.test'}
        self.assertEqual(self.send(raw).status_code,200)
        self.assertEqual(self.send(raw).status_code,200)
        self.assertEqual(PaymentEvent.objects.count(),1)
        job=OutboxJob.objects.get(kind='payment_event_reconcile')
        self.assertEqual(job.status,'blocked');self.assertEqual(job.error_code,'event_not_supported')
        self.assertNotIn('private@example.test',str(job.payload))
        self.assertEqual(self.send({'event':'payment.captured'},'incomplete').status_code,200)
        self.assertEqual(OutboxJob.objects.get(payload__event_name='payment.captured').error_code,'event_incomplete')
        self.assertEqual(self.send({'event':'different'},'fixture-event').status_code,409)
        self.assertFalse(Payment.objects.exists());self.assertFalse(Entitlement.objects.exists())

    def test_complete_event_queues_then_applies_authoritative_capture_exactly_once(self):
        order=self.order();order.provider='razorpay';order.provider_order_id='order_fixture';order.status='created';order.save()
        data={'event':'payment.captured','payload':{'payment':{'entity':{'id':'pay_fixture','order_id':'order_fixture'}}}}
        self.assertEqual(self.send(data).status_code,200)
        self.assertFalse(Payment.objects.exists());self.assertFalse(Entitlement.objects.exists())
        event=PaymentEvent.objects.get();self.assertEqual(event.status,'received')
        job=OutboxJob.objects.get(kind='payment_event_reconcile');self.assertEqual(job.status,'pending')
        facts={'id':'pay_fixture','order_id':'order_fixture','status':'captured','captured':True,'amount':order.total_minor,'currency':order.currency}
        with patch('billing.checkout.RazorpayClient') as adapter:
            adapter.return_value.fetch_payment.return_value=facts
            result=process_payment_event(job);self.assertEqual(result['status'],'applied')
            process_payment_event(job);adapter.return_value.fetch_payment.assert_called_once()
        event.refresh_from_db();self.assertEqual(event.status,'applied');self.assertIsNotNone(event.payment_id)
        self.assertEqual(Payment.objects.count(),1);self.assertEqual(order.entitlements.count(),1)
        self.assertEqual(self.send(data).status_code,200)
        self.assertEqual(OutboxJob.objects.filter(kind='payment_event_reconcile').count(),1)

    def test_missing_order_retries_and_invalid_webhook_never_acknowledges_lost_receipt(self):
        data={'event':'payment.captured','payload':{'payment':{'entity':{'id':'pay_missing','order_id':'order_missing'}}}}
        self.assertEqual(self.send(data).status_code,200)
        with self.assertRaises(DomainError) as error:process_payment_event(OutboxJob.objects.get(kind='payment_event_reconcile'))
        self.assertEqual(error.exception.status,503)
        self.assertEqual(self.send([],event_id='array').status_code,400)
        with patch('billing.webhooks.PaymentEvent.objects.get_or_create',side_effect=OperationalError('Synthetic DB failure')):
            self.assertEqual(self.send(data,event_id='db-failure').status_code,503)
        self.assertFalse(PaymentEvent.objects.filter(provider_event_id='db-failure').exists())

    def request(self,path,data,actor=None,version=None,key=None,fresh=True):
        headers={'HTTP_IDEMPOTENCY_KEY':str(key or uuid.uuid4())}
        if version is not None:headers['HTTP_IF_MATCH']=f'"v{version}"'
        request=RequestFactory().post(path,data,content_type='application/json',**headers)
        request.user=actor or self.staff;request.session={'reauthenticated_at':timezone.now().isoformat()} if fresh else {}
        return request

    def call(self,request):
        match=resolve(request.path)
        return match.func(request,*match.args,**match.kwargs)

    def test_refund_rejection_requires_fresh_permission_version_and_replays_same_receipt(self):
        order,_=self.captured();_,proposal=services.request_refund(self.user,order.id,uuid.uuid4())
        path=f"/api/v1/staff/refunds/{proposal['refund_id']}/reject";key=uuid.uuid4();data={'reason':'Synthetic policy review'}
        self.assertEqual(resolve(path).func,views.reject)
        self.assertEqual(self.call(self.request(path,data,actor=self.user,version=proposal['version'])).status_code,403)
        self.assertEqual(self.call(self.request(path,data,version=proposal['version'],fresh=False)).status_code,403)
        first=self.call(self.request(path,data,version=proposal['version'],key=key));self.assertEqual(first.status_code,200)
        self.assertEqual(json.loads(first.content)['status'],'rejected')
        replay=self.call(self.request(path,data,version=proposal['version'],key=key));self.assertEqual(json.loads(replay.content),json.loads(first.content))
        self.assertEqual(self.call(self.request(path,data,version=proposal['version'])).status_code,412)
        self.assertEqual(AuditEvent.objects.filter(action='refund.rejected').count(),1)
        self.assertFalse(OutboxJob.objects.filter(dedupe_key__startswith='refund-submit:').exists())

    def test_staff_order_reconcile_is_scoped_durable_intent_not_capture(self):
        order=self.order();path=f'/api/v1/staff/orders/{order.id}/reconcile';key=uuid.uuid4();data={'reason':'Synthetic reconciliation check'}
        self.assertEqual(resolve(path).func,views.reconcile)
        self.assertEqual(self.call(self.request(path,data,actor=self.user)).status_code,403)
        self.assertEqual(self.call(self.request(path,data,fresh=False)).status_code,403)
        response=self.call(self.request(path,data,key=key));self.assertEqual(response.status_code,200)
        self.assertEqual(json.loads(self.call(self.request(path,data,key=key)).content),json.loads(response.content))
        self.assertEqual(OutboxJob.objects.filter(kind='order_payment_reconcile').count(),1)
        self.assertFalse(Payment.objects.exists());self.assertNotIn(data['reason'],response.content.decode())
        OperationReceipt.objects.filter(actor=self.staff,operation_id=key).delete()
        self.assertEqual(self.call(self.request(path,data,key=key)).status_code,200)
        self.assertEqual(OutboxJob.objects.filter(kind='order_payment_reconcile').count(),1)
        self.assertEqual(self.call(self.request(path,{'reason':'Changed input'},key=key)).status_code,409)

    def test_order_reconcile_never_trusts_wrong_or_truncated_provider_collection(self):
        order=self.order();order.provider='razorpay';order.provider_order_id='order_fixture';order.status='created';order.save()
        request_order_reconciliation(self.staff,order.id,uuid.uuid4(),'Synthetic collection check')
        job=OutboxJob.objects.get(kind='order_payment_reconcile')
        for response in [{'count':2,'items':[]},{'items':[{'order_id':'order_other'}]}]:
            with patch('billing.checkout.RazorpayClient') as adapter:
                adapter.return_value.order_payments.return_value=response
                with self.assertRaises(DomainError):process_order_reconcile(job)
                adapter.return_value.fetch_payment.assert_not_called()
        self.assertFalse(Payment.objects.exists())
