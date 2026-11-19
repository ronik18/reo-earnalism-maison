"""Owned streamed financial exports and existing-obligation deletion boundaries."""
import hashlib
import io
import json
import time
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.db.models.query import QuerySet
from django.test import TestCase,override_settings
from django.utils import timezone
from core.api import DomainError
from core.models import OutboxJob
from billing.models import Offer,Order,Payment,Invoice,InvoiceRevision,Refund,PaymentAllocation,Subscription,Mandate,BillingPlan
from .models import User
from .privacy import _write_export,delete_account


@override_settings(LOCAL=True,MAISON_LOCAL_FIXTURES=True,MEDIA_STORAGE_BACKEND='local')
class FinancialPrivacyExportTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('financial-export-owner@example.test','Fixture-Only-Password-47',is_verified=True)
        self.other=User.objects.create_user('financial-export-other@example.test','Fixture-Only-Password-47',is_verified=True)
        self.staff=User.objects.create_superuser('private-operator@example.test','Fixture-Only-Password-47')
        self.offer=Offer.objects.create(code='privacy-finance-fixture',name='Synthetic financial fixture',price_minor=100,currency='INR',duration_seconds=3600,terms_version='fixture')
        self.plan=BillingPlan.objects.create(offer=self.offer,interval_unit='month')
    def snapshot(self,user):
        return {'amount_minor':100,'currency':'INR','recipient':{'member_id':str(user.public_id),'name':'Owned buyer' if user==self.user else 'FOREIGN-RECIPIENT','email':user.email,'address':'Owned billing address','provider_token_id':'TOKEN-SENTINEL'},'finance':{'net_minor':90,'tax_minor':10,'total_minor':100,'currency':'INR','issuer':{'legal_name':'Fixture publisher','country':'IN','address':'Invoice address','tax_id':'PUBLIC-FIXTURE-TAX-ID','operator_secret':'ISSUER-PRIVATE-SENTINEL'},'tax':{'label':'Fixture tax','tax_minor':10,'components':[{'label':'Approved fixture component','tax_minor':10,'rate_bps':1000,'evidence_ref':'COMPONENT-EVIDENCE-SENTINEL'}],'evidence_ref':'TAX-EVIDENCE-SENTINEL'},'numbering':{'evidence_ref':'NUMBERING-EVIDENCE-SENTINEL'}},'evidence_ref':'PRIVATE-EVIDENCE-SENTINEL','_issuance':{'request_sha256':'INTERNAL-ISSUANCE-SENTINEL','response':{'private':'INTERNAL-RESPONSE-SENTINEL'}},'storage_key':'exports/PRIVATE-STORAGE-SENTINEL','signed_url':'https://private.invalid/?secret=SIGNED-CAPABILITY-SENTINEL'}
    def records(self,user,suffix):
        now=timezone.now();snapshot=self.snapshot(user)
        order=Order.objects.create(user=user,offer=self.offer,total_minor=100,currency='INR',offer_snapshot={},operation_id=uuid.uuid4(),request_sha256='a'*64,provider='local_test',test_only=True,status='paid',paid_at=now,expires_at=now+timedelta(hours=1))
        payment=Payment.objects.create(order=order,provider='local_test',provider_payment_id='pay_RAW-PRIVATE-'+suffix,amount_minor=100,currency='INR',captured_at=now,verification_source='synthetic_test',evidence_sha256='b'*64)
        invoice=Invoice.objects.create(order=order,number='INV-'+suffix,amount_minor=100,currency='INR',document_sha256='c'*64,line_snapshot=snapshot,issued_at=now)
        PaymentAllocation.objects.create(payment=payment,invoice=invoice,amount_minor=100)
        original=InvoiceRevision.objects.create(invoice=invoice,kind='invoice',sequence=1,number=invoice.number,amount_minor=100,currency='INR',snapshot=snapshot,snapshot_sha256='d'*64,storage_key='exports/PRIVATE-STORAGE-'+suffix,document_sha256='e'*64,bytes=100,issuer_version='INTERNAL-ISSUER-VERSION',approved_by=self.staff)
        Invoice.objects.filter(pk=invoice.pk).update(current_revision=original)
        refund=Refund.objects.create(payment=payment,operation_id=uuid.uuid4(),proposed_amount_minor=25,currency='INR',reason='Member refund')
        refund.status='approved';refund.amount_minor=25;refund.approved_by=self.staff;refund.approved_at=now;refund.save()
        refund.status='processed';refund.processed_at=now;refund.provider_refund_id='rfnd_RAW-PRIVATE-'+suffix;refund.save()
        credit=InvoiceRevision.objects.create(invoice=invoice,kind='credit_note',sequence=2,refund=refund,number='CN-'+suffix,amount_minor=25,currency='INR',snapshot={**snapshot,'amount_minor':25,'tax_minor':0,'invoice_number':invoice.number,'reason':'Approved refund'},snapshot_sha256='f'*64,issuer_version='INTERNAL-ISSUER-VERSION',approved_by=self.staff)
        mandate=Mandate.objects.create(user=user,status='authorized',authorized_at=now,max_amount_minor=100,provider_mandate_id='mandate_RAW-PRIVATE-'+suffix,provider_customer_id='cust_RAW-PRIVATE-'+suffix,provider_token_id='token_RAW-PRIVATE-'+suffix,provider_payment_id='pay_RAW-PRIVATE-'+suffix,provider_invoice_id='inv_RAW-PRIVATE-'+suffix)
        subscription=Subscription.objects.create(user=user,plan=self.plan,mandate=mandate,status='cancelled',provider_status='cancelled',provider_subscription_id='sub_RAW-PRIVATE-'+suffix)
        return invoice,original,credit,refund,subscription,mandate
    def test_streams_all_owned_revisions_credit_notes_and_public_agreements_without_private_fields(self):
        invoice,original,credit,refund,subscription,mandate=self.records(self.user,'OWNER')
        foreign=self.records(self.other,'FOREIGN')
        rows=[InvoiceRevision(invoice=invoice,kind='invoice',sequence=n,number=invoice.number,amount_minor=100,currency='INR',snapshot=self.snapshot(self.user),snapshot_sha256='a'*64,issuer_version='private-version',approved_by=self.staff) for n in range(3,204)]
        InvoiceRevision.objects.bulk_create(rows);Invoice.objects.filter(pk=invoice.pk).update(current_revision=rows[-1])
        output=io.BytesIO();original_iterator=QuerySet.iterator
        with patch.object(QuerySet,'iterator',autospec=True,side_effect=original_iterator) as streaming:
            size,sha=_write_export(self.user,output,time.monotonic()+20)
        raw=output.read();body=json.loads(raw)
        self.assertEqual(size,len(raw));self.assertEqual(sha,hashlib.sha256(raw).hexdigest())
        self.assertGreaterEqual(streaming.call_count,10);self.assertTrue(all(item.kwargs.get('chunk_size')==200 for item in streaming.call_args_list))
        self.assertEqual(len(body['invoices']),1);self.assertEqual(body['invoices'][0]['current_revision_id'],str(rows[-1].id))
        self.assertEqual(len(body['invoice_revisions']),203)
        credits=[row for row in body['invoice_revisions'] if row['kind']=='credit_note'];self.assertEqual(len(credits),1)
        self.assertEqual(credits[0]['refund_id'],str(refund.pk));self.assertEqual(credits[0]['amount_minor'],25)
        self.assertEqual(body['subscriptions'][0]['id'],str(subscription.pk));self.assertEqual(body['mandates'][0]['id'],str(mandate.pk))
        details=body['invoices'][0]['line_snapshot'];self.assertEqual(details['recipient']['email'],self.user.email)
        self.assertEqual(details['finance']['issuer']['tax_id'],'PUBLIC-FIXTURE-TAX-ID');self.assertEqual(details['finance']['tax']['components'][0]['tax_minor'],10)
        text=raw.decode()
        for forbidden in ['FOREIGN-RECIPIENT',str(foreign[0].pk),str(foreign[4].pk),str(foreign[5].pk),self.other.email,'RAW-PRIVATE','PRIVATE-STORAGE','SIGNED-CAPABILITY','PRIVATE-EVIDENCE','TAX-EVIDENCE','COMPONENT-EVIDENCE','NUMBERING-EVIDENCE','INTERNAL-ISSUANCE','INTERNAL-RESPONSE','INTERNAL-ISSUER','ISSUER-PRIVATE','TOKEN-SENTINEL',self.staff.email,'approved_by','issuer_version','_issuance','storage_key','signed_url','provider_customer_id','provider_token_id']:
            self.assertNotIn(forbidden,text)


@override_settings(LOCAL=True,MEDIA_STORAGE_BACKEND='local')
class FinancialDeletionBoundaryTests(TestCase):
    def setup_agreement(self,status='active',provider_id='sub_fixture',revocation_pending=False):
        user=User.objects.create_user(f'{uuid.uuid4()}@example.test','Fixture-Only-Password-47',is_verified=True)
        offer=Offer.objects.create(code=str(uuid.uuid4()),name='Historical fixture',price_minor=100,currency='INR',duration_seconds=3600,terms_version='fixture')
        plan=BillingPlan.objects.create(offer=offer,interval_unit='month');now=timezone.now()
        mandate=Mandate.objects.create(user=user,status='authorized',authorized_at=now,max_amount_minor=100,provider_mandate_id='token-fixture-'+str(uuid.uuid4()),revocation_pending=revocation_pending)
        sub=Subscription.objects.create(user=user,plan=plan,mandate=mandate,status=status,provider_status='active' if status=='active' else ('created' if status=='pending' else status),provider_subscription_id=('sub_'+uuid.uuid4().hex) if provider_id else None,current_period_start=now-timedelta(days=1),current_period_end=now+timedelta(days=29),paid_through=now+timedelta(days=29))
        job=OutboxJob.objects.create(kind='privacy_delete',actor=user,dedupe_key=str(uuid.uuid4()),not_before=now)
        return user,sub,mandate,job
    def test_active_provider_agreement_defers_without_anonymization(self):
        user,sub,mandate,job=self.setup_agreement();email=user.email
        with self.assertRaises(DomainError) as error:delete_account(job)
        self.assertEqual(error.exception.code,'awaiting_resolution');self.assertIn('Settings > Billing',error.exception.message)
        user.refresh_from_db();self.assertTrue(user.is_active);self.assertEqual(user.email,email)
        sub.refresh_from_db();self.assertIsNotNone(sub.paid_through)
    def test_pending_revocation_defers_even_after_subscription_is_terminal(self):
        user,sub,mandate,job=self.setup_agreement(status='cancelled',revocation_pending=True)
        with self.assertRaises(DomainError):delete_account(job)
        user.refresh_from_db();self.assertTrue(user.is_active)
    def test_terminal_financial_history_does_not_prevent_anonymization(self):
        for status in ['cancelled','completed','expired']:
            with self.subTest(status=status):
                user,sub,mandate,job=self.setup_agreement(status=status)
                delete_account(job);user.refresh_from_db();self.assertFalse(user.is_active)
                self.assertTrue(Subscription.objects.filter(pk=sub.pk).exists());self.assertTrue(Mandate.objects.filter(pk=mandate.pk).exists())
    def test_unused_token_without_provider_collection_does_not_block(self):
        user,sub,mandate,job=self.setup_agreement(status='pending',provider_id=None)
        delete_account(job);user.refresh_from_db();self.assertFalse(user.is_active)
    def test_active_service_only_blocks_while_linked_bank_authority_is_unresolved(self):
        for bank_status in ['cancelled','expired','authorized','pending']:
            with self.subTest(bank_status=bank_status):
                user,sub,mandate,job=self.setup_agreement(status='active')
                paid_through=sub.paid_through
                mandate.status=bank_status
                if bank_status=='cancelled':mandate.revoked_at=timezone.now()
                if bank_status=='expired':mandate.expires_at=timezone.now()-timedelta(seconds=1)
                mandate.save(update_fields=['status','revoked_at','expires_at'])
                if bank_status in ['cancelled','expired']:
                    delete_account(job);user.refresh_from_db();self.assertFalse(user.is_active)
                    sub.refresh_from_db();self.assertEqual(sub.paid_through,paid_through)
                    self.assertTrue(Mandate.objects.filter(pk=mandate.pk).exists())
                else:
                    with self.assertRaises(DomainError) as error:delete_account(job)
                    self.assertEqual(error.exception.code,'awaiting_resolution')
                    user.refresh_from_db();self.assertTrue(user.is_active)
