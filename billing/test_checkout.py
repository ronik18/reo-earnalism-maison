import uuid
from unittest.mock import patch
from django.test import TestCase,override_settings
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
    def test_unqualified_live_checkout_stays_disabled(self):
        with self.assertRaises(DomainError):qualified_mode()
