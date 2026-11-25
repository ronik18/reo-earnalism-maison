import io,uuid
from datetime import date,datetime,timedelta,timezone as dtz
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError,transaction
from django.test import TestCase,override_settings
from django.utils import timezone
from .models import Offer,Invoice,BillingPlan,Subscription,RevenueEntry,ReinvestmentEntry
from .revenue import month_report

MONTH=date(2026,12,1)


class RevenueTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('rev@example.test','Revenue-local-test-Strong47',is_verified=True)
    def pass_invoice(self,code=None,amount=100000,issued=None,currency='INR'):
        code=code or 'founding-pass-'+uuid.uuid4().hex[:6]
        offer=Offer.objects.create(code=code,name=code,currency=currency,price_minor=amount,duration_seconds=86400,formats=['reader'],terms_version='x')
        plan=BillingPlan.objects.create(offer=offer,interval_unit='year')
        sub=Subscription.objects.create(user=self.user,plan=plan)
        inv=Invoice.objects.create(subscription=sub,number='R-'+str(uuid.uuid4()),amount_minor=amount,currency=currency,line_snapshot={},document_sha256='a'*64,issued_at=issued or datetime(2026,12,10,12,tzinfo=dtz.utc))
        return inv
    def entry(self,source,amount,month=MONTH,currency='INR'):
        return RevenueEntry.objects.create(month=month,source=source,amount_minor=amount,currency=currency,reference='ref',recorded_by=self.user)
    def spend(self,**kw):
        data=dict(month=MONTH,kind='spend',amount_minor=500,purpose='ads',approved_by=self.user,payback_due=date(2026,12,31),paid_back=False)
        data.update(kw);return ReinvestmentEntry.objects.create(**data)

    @override_settings(MAISON_REINVEST_SHARE_PERCENT=30)
    def test_report_sums_by_source_and_computes_thirty_percent(self):
        self.pass_invoice(amount=100000)
        self.pass_invoice(code='other-plan',amount=77777)
        self.pass_invoice(amount=5000,issued=datetime(2026,11,30,12,tzinfo=dtz.utc))
        self.pass_invoice(code='founding-pass-usd',amount=900,currency='USD')
        self.entry('pass',1000);self.entry('youtube',20001);self.entry('schools',3,month=date(2027,1,1))
        report=month_report(MONTH)
        self.assertEqual(report['by_source']['pass'],101000)
        self.assertEqual(report['by_source']['youtube'],20001)
        self.assertEqual(report['total_minor'],121001)
        self.assertEqual(report['set_aside_due_minor'],121001*30//100)
        self.assertEqual(report['other_currencies'],{'USD':900})

    def test_spend_without_approval_is_rejected_by_database(self):
        for kw in ({'approved_by':None},{'payback_due':None}):
            with self.assertRaises(IntegrityError),transaction.atomic(): self.spend(**kw)
        ReinvestmentEntry.objects.create(month=MONTH,kind='set_aside',amount_minor=1,purpose='x')
        with self.assertRaises(IntegrityError),transaction.atomic(): self.entry('pass',1,month=date(2026,12,2))

    def test_spend_past_sixty_days_unpaid_is_flagged(self):
        today=timezone.localdate()
        late=self.spend(payback_due=today-timedelta(days=1))
        self.spend(payback_due=today-timedelta(days=5),paid_back=True)
        self.spend(payback_due=today+timedelta(days=30))
        self.assertEqual([r['id'] for r in month_report(MONTH)['overdue_paybacks']],[late.pk])
        self.assertEqual(len(month_report(MONTH)['spends']),3)

    @override_settings(MAISON_REINVEST_SHARE_PERCENT=30)
    def test_command_prints_and_records_set_aside_once(self):
        self.entry('podcast',10000)
        out=io.StringIO()
        for _ in range(2): call_command('revenue_report','--month','2026-12','--record-set-aside',stdout=out)
        self.assertIn('podcast',out.getvalue())
        rows=ReinvestmentEntry.objects.filter(kind='set_aside',month=MONTH)
        self.assertEqual([r.amount_minor for r in rows],[3000])
