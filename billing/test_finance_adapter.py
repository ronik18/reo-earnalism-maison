"""Strict provider routes and minimized authenticated event intake; no HTTP calls."""
from unittest.mock import patch,call
from django.test import SimpleTestCase,TestCase
from core.api import DomainError
from core.models import OutboxJob
from .razorpay import RazorpayClient
from . import test_webhooks as fixtures

class QualifiedProviderRouteTests(SimpleTestCase):
    def test_customer_token_and_invoice_routes_are_exact_and_validate_ids(self):
        with patch.object(RazorpayClient,'__init__',return_value=None):client=RazorpayClient()
        with patch.object(client,'request',return_value={}) as request:
            client.fetch_customer_token('cust_fixture','token_fixture')
            client.cancel_customer_token('cust_fixture','token_fixture')
            client.delete_customer_token('cust_fixture','token_fixture')
            client.fetch_invoice('inv_fixture')
            self.assertEqual(request.call_args_list,[call('GET','/customers/cust_fixture/tokens/token_fixture'),call('PUT','/customers/cust_fixture/tokens/token_fixture/cancel',{}),call('DELETE','/customers/cust_fixture/tokens/token_fixture'),call('GET','/invoices/inv_fixture')])
            with self.assertRaises(DomainError):client.delete_customer_token('cust_fixture/other','token_fixture')
            self.assertEqual(request.call_count,4)

class TokenWebhookIntakeTests(TestCase):
    setUp=fixtures.DurableWebhookTests.setUp
    send=fixtures.DurableWebhookTests.send
    def test_signed_token_event_keeps_only_exact_authority_fields(self):
        from django.test import override_settings
        with override_settings(RAZORPAY_ENABLED=True,RAZORPAY_KEY_ID='rzp_test_fixture',RAZORPAY_KEY_SECRET='fixture',MERCHANT_ENTITY_CONFIG_VERSION='fixture',RAZORPAY_WEBHOOK_SECRETS=['fixture-webhook-secret'],RAZORPAY_MODE='test'):
            response=self.send({'event':'token.cancelled','payload':{'token':{'entity':{'id':'token_fixture','customer_id':'cust_fixture','email':'private@example.test','bank_account':{'number':'fixture-never-retain'}}}}})
        self.assertEqual(response.status_code,200)
        job=OutboxJob.objects.get(kind='payment_event_reconcile');self.assertEqual(job.status,'pending')
        self.assertEqual(job.payload['provider_token_id'],'token_fixture');self.assertEqual(job.payload['provider_mode'],'test')
        self.assertNotIn('private@example.test',str(job.payload));self.assertNotIn('fixture-never-retain',str(job.payload))

class ProviderHTTPMetadataTests(SimpleTestCase):
    def test_status_metadata_is_internal_without_changing_public_error_or_leaking_body(self):
        from django.test import override_settings
        with override_settings(RAZORPAY_ENABLED=True,RAZORPAY_MODE='test',RAZORPAY_KEY_ID='rzp_test_fixture',RAZORPAY_KEY_SECRET='fixture',MERCHANT_ENTITY_CONFIG_VERSION='fixture'):
            with patch('billing.razorpay.http.client.HTTPSConnection') as transport:
                connection=transport.return_value;connection.sock=None
                response=connection.getresponse.return_value;response.status=404
                response.read.side_effect=[b'{"private":"do-not-expose-provider-body"}',b'']
                with self.assertRaises(DomainError) as error:RazorpayClient().fetch_customer_token('cust_fixture','token_fixture')
        self.assertEqual(error.exception.code,'provider_request_failed');self.assertEqual(error.exception.status,422)
        self.assertEqual(error.exception.provider_http_status,404)
        self.assertNotIn('do-not-expose-provider-body',str(error.exception))
