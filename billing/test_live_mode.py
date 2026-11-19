"""Mode/finance source acceptance with mocked merchant facts; never real payments."""
import uuid
from datetime import timedelta
from django.utils import timezone
from unittest.mock import patch
from django.test import TestCase,override_settings
from core.api import DomainError
from core.models import OutboxJob
from . import tests as fixtures,services
from .models import Order,Invoice,Refund
from .checkout import create_order,process_checkout,reconcile_payment,eligible
from .refunds import process_refund_job

@override_settings(RAZORPAY_ENABLED=True,RAZORPAY_MODE='live',RAZORPAY_KEY_ID='rzp_live_fixture',RAZORPAY_KEY_SECRET='fixture',RAZORPAY_LIVE_APPROVED=True,MERCHANT_ENTITY_CONFIG_VERSION='fixture')
class LiveModeTests(TestCase):
    setUp=fixtures.BillingStateMachineTests.setUp
    def policy(self):
        return {'approved':True,'version':'fixture-finance-v1','issuer':{'legal_name':'Fixture entity','address':'Fixture address','country':'IN'},'numbering':{'scheme':'prefix_uuid','prefix':'FIXTURE'},'offer_tax':{str(self.offer.id):{'offer_version':self.offer.version,'territory':'IN','currency':'INR','price_minor':self.offer.price_minor,'basis':'inclusive','tax_minor':1000,'label':'Fixture approved tax','evidence_ref':'internal:test-only-finance-decision'}}}
    def create(self):
        self.offer.test_only=False;self.offer.save()
        with override_settings(MERCHANT_FINANCE_POLICY=self.policy()):
            _,dto=create_order(self.user,{'offer_id':str(self.offer.id),'offer_version':self.offer.version,'terms_version':self.offer.terms_version,'return_path':'/vault/'},uuid.uuid4(),'IN')
        return Order.objects.get(pk=dto['order_id'])
    def capture(self,order):
        row={'id':'pay_livefixture','order_id':order.provider_order_id,'status':'captured','captured':True,'amount':order.total_minor,'currency':order.currency}
        with patch('billing.checkout.RazorpayClient') as adapter:
            adapter.return_value.fetch_payment.return_value=row
            return reconcile_payment(order,'pay_livefixture',event_id='live-fixture-event')
    def test_live_order_capture_invoice_and_refund_bound_to_approved_policy(self):
        order=self.create();self.assertFalse(order.test_only)
        job=OutboxJob.objects.get(dedupe_key=f'checkout:{order.id}')
        with override_settings(MERCHANT_FINANCE_POLICY=self.policy()),patch('billing.checkout.RazorpayClient') as adapter:
            adapter.return_value.create_order.return_value={'id':'order_livefixture','amount':order.total_minor,'currency':order.currency,'receipt':str(order.id)}
            process_checkout(job)
        order.refresh_from_db();self.assertEqual(services.checkout_data(order)['name'],'Earnalism')
        self.assertEqual(self.capture(order)['fulfillment_status'],'granted')
        payment=order.payments.get();self.assertEqual(payment.verification_source,'razorpay_api_live')
        invoice=Invoice.objects.get(order=order);self.assertTrue(invoice.number.startswith('FIXTURE-'))
        self.assertFalse(invoice.line_snapshot['local_test_document']);self.assertEqual(invoice.line_snapshot['finance']['tax_minor'],1000)
        _,proposal=services.request_refund(self.user,order.pk,uuid.uuid4());services.approve_refund(self.staff,proposal['refund_id'],order.total_minor,proposal['version'],uuid.uuid4())
        refund=Refund.objects.get(pk=proposal['refund_id']);job=OutboxJob.objects.get(dedupe_key=f'refund-submit:{refund.id}')
        with patch('billing.refunds.RazorpayClient') as adapter:
            adapter.return_value.create_refund.return_value={'id':'rfnd_livefixture','payment_id':payment.provider_payment_id,'amount':refund.amount_minor,'currency':refund.currency,'receipt':str(refund.pk),'notes':{'maison_refund_id':str(refund.pk)},'status':'processed'}
            self.assertEqual(process_refund_job(job)['status'],'processed')
    def test_test_offer_and_cross_mode_order_cannot_use_live_adapter(self):
        with self.assertRaises(DomainError) as error:eligible(self.user,self.offer,'IN')
        self.assertEqual(error.exception.code,'offer_unavailable')
        order=self.create()
        with override_settings(RAZORPAY_MODE='test',RAZORPAY_KEY_ID='rzp_test_fixture'),patch('billing.checkout.RazorpayClient') as adapter:
            with self.assertRaises(DomainError) as error:reconcile_payment(order,'pay_fixture')
            self.assertEqual(error.exception.code,'provider_mode_mismatch');adapter.assert_not_called()
    def test_unapproved_finance_prevents_order_without_guessing_tax(self):
        self.offer.test_only=False;self.offer.save()
        with override_settings(MERCHANT_FINANCE_POLICY={}):
            with self.assertRaises(DomainError) as error:eligible(self.user,self.offer,'IN')
            self.assertEqual(error.exception.code,'finance_policy_required')
        self.assertFalse(Order.objects.exists())
    def test_legacy_live_capture_without_finance_retains_money_for_review(self):
        self.offer.test_only=False;self.offer.save()
        order=Order.objects.create(user=self.user,offer=self.offer,total_minor=self.offer.price_minor,currency='INR',offer_snapshot={'edition_id':str(self.edition.id),'formats':['reader'],'duration_seconds':86400},operation_id=uuid.uuid4(),request_sha256='f'*64,provider='razorpay',provider_order_id='order_livefixture',test_only=False,status='created',expires_at=timezone.now()+timedelta(minutes=5))
        self.assertEqual(self.capture(order)['fulfillment_status'],'refund_pending')
        self.assertTrue(order.payments.exists());self.assertFalse(Invoice.objects.filter(order=order).exists());self.assertFalse(order.entitlements.exists())
