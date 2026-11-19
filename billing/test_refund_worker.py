"""Durable sandbox refund tests: mocked provider only, no money movement."""
import uuid
from dataclasses import replace
from unittest.mock import patch
from django.utils import timezone
from django.test import TestCase,override_settings
from core.api import DomainError
from core.models import OutboxJob
from . import tests as fixtures,services
from .models import Refund,Invoice
from .refunds import process_refund_job

@override_settings(RAZORPAY_ENABLED=True,RAZORPAY_MODE='test',RAZORPAY_KEY_ID='rzp_test_fixture',RAZORPAY_KEY_SECRET='fixture',MERCHANT_ENTITY_CONFIG_VERSION='fixture')
class RefundWorkerTests(TestCase):
    setUp=fixtures.BillingStateMachineTests.setUp
    order=fixtures.BillingStateMachineTests.order
    facts=fixtures.BillingStateMachineTests.facts
    def approved(self,amount=None):
        order=self.order();order.provider='razorpay';order.provider_order_id='order_fixture';order.save()
        facts=replace(self.facts(order,payment_id='pay_fixture'),provider='razorpay',verification_source='razorpay_api_test',order_reference='order_fixture')
        services.apply_capture(order.id,facts,event_id='fixture_capture')
        _,proposal=services.request_refund(self.user,order.id,uuid.uuid4())
        services.approve_refund(self.staff,proposal['refund_id'],amount or order.total_minor,proposal['version'],uuid.uuid4())
        row=Refund.objects.get(pk=proposal['refund_id'])
        return order,row,OutboxJob.objects.get(dedupe_key=f'refund-submit:{row.id}')
    def response(self,row,status='processed',**extra):
        return {'id':'rfnd_fixture','payment_id':row.payment.provider_payment_id,'amount':row.amount_minor,'currency':row.currency,'receipt':str(row.id),'notes':{'maison_refund_id':str(row.id)},'status':status,**extra}
    def test_processed_once_revokes_only_full_refund_and_retains_invoice(self):
        order,row,job=self.approved();invoice=Invoice.objects.get(order=order)
        with patch('billing.refunds.RazorpayClient') as provider:
            provider.return_value.create_refund.return_value=self.response(row)
            self.assertEqual(process_refund_job(job)['status'],'processed')
            self.assertEqual(process_refund_job(job)['status'],'processed')
            provider.return_value.create_refund.assert_called_once()
        self.assertIsNotNone(order.entitlements.get().revoked_at)
        self.assertTrue(Invoice.objects.filter(pk=invoice.pk).exists())
    def test_pending_fetches_existing_identity_and_partial_preserves_access(self):
        order,row,job=self.approved(3000)
        with patch('billing.refunds.RazorpayClient') as provider:
            provider.return_value.create_refund.return_value=self.response(row,'pending')
            pending=process_refund_job(job)
            self.assertTrue(pending['awaiting_provider_confirmation']);self.assertEqual(pending['status'],'pending')
            provider.return_value.fetch_refund.return_value=self.response(row)
            process_refund_job(job)
            provider.return_value.create_refund.assert_called_once();provider.return_value.fetch_refund.assert_called_once()
        self.assertIsNone(order.entitlements.get().revoked_at)
        row.payment.refresh_from_db();self.assertEqual(row.payment.status,'partially_refunded')
    def test_uncertain_post_never_repeats_and_review_has_no_provider_call(self):
        order,row,job=self.approved()
        with patch('billing.refunds.RazorpayClient') as provider:
            provider.return_value.create_refund.side_effect=DomainError('provider_outcome_unknown','Fixture timeout',503)
            with self.assertRaises(DomainError):process_refund_job(job)
            provider.return_value.find_refund.return_value=None
            with self.assertRaises(DomainError) as error:process_refund_job(job)
            self.assertEqual(error.exception.code,'awaiting_resolution')
            provider.return_value.create_refund.assert_called_once()
            provider.return_value.find_refund.return_value=self.response(row)
            self.assertEqual(process_refund_job(job)['status'],'processed')
        review=OutboxJob.objects.create(not_before=timezone.now(),kind='refund_review',dedupe_key='review-fixture',actor=self.user,payload={'payment_id':str(row.payment_id)})
        with patch('billing.refunds.RazorpayClient') as provider:
            with self.assertRaises(DomainError) as error:process_refund_job(review)
            self.assertEqual(error.exception.code,'refund_review_required');provider.assert_not_called()
    def test_wrong_amount_remains_unprocessed_and_not_reposted(self):
        order,row,job=self.approved()
        with patch('billing.refunds.RazorpayClient') as provider:
            provider.return_value.create_refund.return_value=self.response(row,amount=row.amount_minor+1)
            with self.assertRaises(DomainError) as error:process_refund_job(job)
            self.assertEqual(error.exception.code,'awaiting_resolution')
        row.refresh_from_db();self.assertEqual(row.status,'approved');self.assertIsNone(order.entitlements.get().revoked_at)
    def test_duplicate_capture_refund_preserves_original_funded_entitlement(self):
        order,row,_=self.approved(1000)
        facts=replace(self.facts(order,payment_id='pay_duplicate'),provider='razorpay',verification_source='razorpay_api_test',order_reference='order_fixture')
        services.apply_capture(order.id,facts,event_id='fixture_duplicate')
        payment=order.payments.get(provider_payment_id='pay_duplicate')
        proposal=Refund.objects.create(payment=payment,operation_id=uuid.uuid4(),proposed_amount_minor=payment.amount_minor,currency=payment.currency,reason='duplicate')
        services.approve_refund(self.staff,proposal.pk,payment.amount_minor,proposal.version,uuid.uuid4())
        proposal.refresh_from_db();job=OutboxJob.objects.get(dedupe_key=f'refund-submit:{proposal.id}')
        with patch('billing.refunds.RazorpayClient') as provider:
            provider.return_value.create_refund.return_value=self.response(proposal)
            process_refund_job(job)
        self.assertIsNone(order.entitlements.get().revoked_at)
        order.refresh_from_db();self.assertEqual(order.fulfillment_status,'granted')
