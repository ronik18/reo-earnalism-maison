import uuid
from unittest.mock import patch
from django.test import TestCase,SimpleTestCase,override_settings
from core.api import DomainError
from core.models import OutboxJob
from . import tests as existing_tests
from .models import Order
from .checkout import create_order,process_checkout,qualified_mode
from library.validation import validate_schema

@override_settings(RAZORPAY_ENABLED=True,RAZORPAY_MODE='test',RAZORPAY_KEY_ID='rzp_test_fixture',RAZORPAY_KEY_SECRET='fixture-secret',MERCHANT_ENTITY_CONFIG_VERSION='sandbox-fixture')
class HostedSandboxTests(TestCase):
    setUp=existing_tests.BillingStateMachineTests.setUp
    def test_checkout_unknown_outcome_never_repeats_create(self):
        data={'offer_id':str(self.offer.id),'offer_version':self.offer.version,'terms_version':self.offer.terms_version,'return_path':'/vault/'}
        status,body=create_order(self.user,data,uuid.uuid4(),'IN');self.assertEqual(status,202)
        row=Order.objects.get(pk=body['order_id']);job=OutboxJob.objects.get(dedupe_key=f'checkout:{row.id}')
        with patch('billing.checkout.RazorpayClient') as adapter:
            adapter.return_value.create_order.side_effect=DomainError('provider_outcome_unknown','Unknown',503)
            with self.assertRaises(DomainError):process_checkout(job)
            adapter.return_value.create_order.assert_called_once()
        with patch('billing.checkout.RazorpayClient') as adapter:
            adapter.return_value.find_order.return_value={'id':'order_fixture','amount':row.total_minor,'currency':row.currency,'receipt':str(row.id)}
            process_checkout(job);adapter.return_value.create_order.assert_not_called()
        row.refresh_from_db();from .services import order_data
        dto=order_data(row);validate_schema(dto,'Order');self.assertEqual(dto['checkout']['provider_order_id'],'order_fixture')

    @override_settings(RAZORPAY_MODE='live',RAZORPAY_KEY_ID='rzp_live_fixture',RAZORPAY_LIVE_APPROVED=True)
    def test_live_transport_uses_explicit_approval_but_offer_requires_finance(self):
        self.assertEqual(qualified_mode()[0],'live')
        self.offer.test_only=False;self.offer.save()
        from .checkout import eligible
        with self.assertRaises(DomainError) as error:eligible(self.user,self.offer,'IN')
        self.assertEqual(error.exception.code,'finance_policy_required')


    def test_provider_order_response_does_not_reopen_expired_order(self):
        data={'offer_id':str(self.offer.id),'offer_version':self.offer.version,'terms_version':self.offer.terms_version,'return_path':'/en/vault/'}
        _,body=create_order(self.user,data,uuid.uuid4(),'IN');row=Order.objects.get(pk=body['order_id'])
        job=OutboxJob.objects.get(dedupe_key=f'checkout:{row.id}')
        def expire(order):
            Order.objects.filter(pk=order.pk).update(status='expired')
            return {'id':'order_expired','amount':order.total_minor,'currency':order.currency,'receipt':str(order.id)}
        with patch('billing.checkout.RazorpayClient') as adapter:
            adapter.return_value.create_order.side_effect=expire
            process_checkout(job)
        row.refresh_from_db();self.assertEqual(row.status,'expired');self.assertEqual(row.provider_order_id,'order_expired')


class BoundedMerchantSearchTests(SimpleTestCase):
    def test_full_search_bound_never_claims_unique_order_or_refund(self):
        from types import SimpleNamespace
        from django.utils import timezone
        from unittest.mock import Mock
        from .razorpay import RazorpayClient
        client=object.__new__(RazorpayClient)
        order=SimpleNamespace(id=uuid.uuid4(),created_at=timezone.now())
        first={'receipt':str(order.id),'notes':{'maison_order_id':str(order.id)}}
        pages=[{'items':[first]+[{} for _ in range(99)]}]+[{'items':[{} for _ in range(100)]} for _ in range(4)]
        client.request=Mock(side_effect=pages)
        with self.assertRaises(DomainError) as error:client.find_order(order)
        self.assertEqual(error.exception.code,'provider_search_incomplete')
        refund=SimpleNamespace(id=uuid.uuid4(),payment=SimpleNamespace(provider_payment_id='pay_fixture'))
        client.request=Mock(return_value={'items':[{} for _ in range(100)]})
        with self.assertRaises(DomainError) as error:client.find_refund(refund)
        self.assertEqual(error.exception.code,'provider_search_incomplete')
