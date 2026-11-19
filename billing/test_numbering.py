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
    def test_approval_version_rotation_keeps_visible_invoice_and_credit_series(self):
        from copy import deepcopy
        policy=self.policy();at=datetime(2026,11,19,tzinfo=timezone.utc)
        self.assertEqual(reserve(policy,'invoice','first',at),'INV2627000001')
        self.assertEqual(reserve(policy,'credit_note','first',at),'CN2627000001')
        changed=deepcopy(policy);changed['version']='new-issuer-approval';changed['numbering']['version']='new-numbering-approval'
        self.assertEqual(forecast(changed,'invoice','second',at),('INV2627000002',2))
        self.assertEqual(reserve(changed,'invoice','second',at,expected=2),'INV2627000002')
        self.assertEqual(reserve(changed,'credit_note','second',at),'CN2627000002')
        self.assertEqual(FinanceNumberSequence.objects.count(),2)
    def test_unknown_legacy_prefix_history_is_retained_and_sets_high_water(self):
        from .numbering import parameters
        policy=self.policy();at=datetime(2026,11,19,tzinfo=timezone.utc)
        _,_,key=parameters(policy,'invoice',at)
        old=FinanceNumberSequence.objects.create(**key,next_number=8)
        changed={**policy,'numbering':{**policy['numbering'],'version':'replacement-approval'}}
        self.assertEqual(forecast(changed,'invoice','first',at),('INV2627000008',8))
        self.assertEqual(reserve(changed,'invoice','first',at,expected=8),'INV2627000008')
        old.refresh_from_db();self.assertIsNone(old.series_prefix);self.assertEqual(old.next_number,8)
        self.assertEqual(reserve(policy,'invoice','second',at),'INV2627000009')
    def test_distinct_visible_prefixes_with_same_approval_are_independent(self):
        policy=self.policy();at=datetime(2026,11,19,tzinfo=timezone.utc)
        self.assertEqual(reserve(policy,'invoice','first',at),'INV2627000001')
        changed={**policy,'numbering':{**policy['numbering'],'prefix':'OTHER'}}
        self.assertEqual(reserve(changed,'invoice','first',at),'OTHER2627000001')
        self.assertEqual(reserve(policy,'invoice','second',at),'INV2627000002')
    def test_invalid_numbering_version_fails_before_counter_write(self):
        policy=self.policy()
        for version in [None,'',True,'x'*121]:
            with self.subTest(version=version),self.assertRaises(DomainError) as error:
                reserve({**policy,'numbering':{**policy['numbering'],'version':version}},'invoice','fixture')
            self.assertEqual(error.exception.code,'finance_policy_required')
        self.assertFalse(FinanceNumberSequence.objects.exists())
        del policy['numbering']['version']
        self.assertTrue(reserve(policy,'invoice','fixture').startswith('INV'))
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

    def test_concurrent_different_approvals_share_one_visible_series(self):
        from concurrent.futures import ThreadPoolExecutor
        def allocate(index):
            close_old_connections()
            try:
                policy=LegalNumberingTests.policy(self);policy['numbering']['version']=f'approval-{index}'
                return reserve(policy,'invoice','fixture',datetime(2026,11,19,tzinfo=timezone.utc))
            finally:connections['default'].close()
        with ThreadPoolExecutor(max_workers=3) as pool:numbers=list(pool.map(allocate,range(3)))
        self.assertEqual(sorted(numbers),['INV2627000001','INV2627000002','INV2627000003'])
        self.assertEqual(FinanceNumberSequence.objects.count(),1)
