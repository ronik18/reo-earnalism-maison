"""Explicit approved sequence behavior; fixtures are not GST/legal approval."""
from datetime import datetime,timezone
from django.test import TestCase
from django.db import transaction
from core.api import DomainError
from .numbering import forecast,reserve
from .invoice_models import FinanceNumberSequence

class LegalNumberingTests(TestCase):
    def policy(self):return {'version':'fixture','issuer':{'legal_name':'Fixture issuer','country':'IN','tax_id':'TEST-NOT-REGISTRATION'},'numbering':{'scheme':'fy_sequence','version':'fixture-numbering','prefix':'INV','credit_note_prefix':'CN','fiscal_year_start_month':4,'time_zone':'Asia/Kolkata','width':6}}
    def test_separate_consecutive_fiscal_sequences_and_local_year_boundary(self):
        policy=self.policy();before=datetime(2026,3,31,18,29,tzinfo=timezone.utc);after=datetime(2026,3,31,18,31,tzinfo=timezone.utc)
        self.assertEqual(reserve(policy,'invoice','ignored',before),'INV2526000001')
        self.assertEqual(reserve(policy,'invoice','ignored',before),'INV2526000002')
        self.assertEqual(reserve(policy,'invoice','ignored',after),'INV2627000001')
        self.assertEqual(reserve(policy,'credit_note','ignored',after),'CN2627000001')
        self.assertTrue(all(len(value)<=16 for value in [forecast(policy,'invoice','x',before)[0],forecast(policy,'invoice','x',after)[0]]))
    def test_failed_transaction_does_not_consume_number_and_forecast_cas_is_enforced(self):
        policy=self.policy()
        with self.assertRaises(RuntimeError):
            with transaction.atomic():reserve(policy,'invoice','x');raise RuntimeError('fixture rollback')
        self.assertEqual(forecast(policy,'invoice','x')[1],1)
        reserve(policy,'invoice','x',expected=1)
        with self.assertRaises(DomainError):reserve(policy,'invoice','x',expected=1)
        self.assertEqual(FinanceNumberSequence.objects.get().next_number,2)
    def test_uuid_scheme_requires_explicit_non_gst_review_and_length_limit(self):
        policy=self.policy();policy['numbering']={'scheme':'prefix_uuid','prefix':'INV'}
        with self.assertRaises(DomainError):reserve(policy,'invoice','uuid')
        policy['numbering'].update(applicability='reviewed_non_gst',evidence_ref='internal:fixture')
        self.assertEqual(reserve(policy,'invoice','uuid'),'INV-uuid')
        policy=self.policy();policy['numbering']['prefix']='TOO-LONG-LEGAL'
        with self.assertRaises(DomainError):reserve(policy,'invoice','x')

from django.test import TransactionTestCase
from django.db import close_old_connections,connections

class ConcurrentLegalNumberingTests(TransactionTestCase):
    def test_concurrent_reservations_are_unique_consecutive_and_committed(self):
        from concurrent.futures import ThreadPoolExecutor
        policy=LegalNumberingTests.policy(self)
        def allocate(_):
            close_old_connections()
            try:return reserve(policy,'invoice','fixture',datetime(2026,11,19,tzinfo=timezone.utc))
            finally:connections['default'].close()
        with ThreadPoolExecutor(max_workers=3) as pool:numbers=list(pool.map(allocate,range(3)))
        self.assertEqual(sorted(numbers),['INV2627000001','INV2627000002','INV2627000003'])
