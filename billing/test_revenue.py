import io,uuid
from datetime import date,datetime,timedelta,timezone as dtz
from django.contrib.auth import get_user_model
from django.core.management import call_command,CommandError
from django.db import IntegrityError,transaction
from django.test import TestCase,override_settings
from django.utils import timezone
from .models import Offer,Invoice,BillingPlan,Subscription,RevenueEntry,ReinvestmentEntry
from .revenue import month_report,record_spend

MONTH=date(2026,12,1)


class RevenueTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('rev@example.test','Revenue-local-test-Strong47',is_verified=True,is_staff=True)
    def pass_invoice(self,code=None,amount=100000,issued=None,currency='INR',test_only=False):
        code=code or 'founding-pass-'+uuid.uuid4().hex[:6]
        offer=Offer.objects.create(code=code,name=code,currency=currency,price_minor=amount,duration_seconds=86400,formats=['reader'],terms_version='x',test_only=test_only)
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
        self.pass_invoice(amount=33333,test_only=True)  # a sandbox/test offer is never revenue
        self.entry('licensing',1000);self.entry('youtube',20001);self.entry('schools',3,month=date(2027,1,1))
        report=month_report(MONTH)
        self.assertEqual(report['by_source']['pass'],100000)
        self.assertEqual(report['by_source']['licensing'],1000)
        self.assertEqual(report['by_source']['youtube'],20001)
        self.assertEqual(report['total_minor'],121001)
        self.assertEqual(report['set_aside_due_minor'],121001*30//100)
        self.assertEqual(report['other_currencies'],{'USD':900})

    def test_spend_without_approval_is_rejected_by_database(self):
        for kw in ({'approved_by':None},{'payback_due':None}):
            with self.assertRaises(IntegrityError),transaction.atomic(): self.spend(**kw)
        ReinvestmentEntry.objects.create(month=MONTH,kind='set_aside',amount_minor=1,purpose='x')
        with self.assertRaises(IntegrityError),transaction.atomic(): self.entry('youtube',1,month=date(2026,12,2))

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

    def test_pass_is_labelled_invoiced_and_set_aside_line_says_so(self):
        self.pass_invoice(amount=1000)
        self.assertEqual(month_report(MONTH)['pass_basis'],'invoiced')
        out=io.StringIO();call_command('revenue_report','--month','2026-12',stdout=out)
        self.assertIn('pass (invoiced; capture not verified; refunds not deducted)',out.getvalue())
        self.assertIn('set-aside (on invoiced figures)',out.getvalue())

    def test_overdue_includes_spends_from_earlier_months(self):
        old=self.spend(month=date(2026,1,1),payback_due=date(2026,2,1))
        self.assertEqual([r['id'] for r in month_report(MONTH)['overdue_paybacks']],[old.pk])
        self.assertEqual(month_report(MONTH)['spends'],[])

    def test_record_spend_refuses_payback_beyond_sixty_days(self):
        from core.api import DomainError
        self.set_aside(1000)
        with self.assertRaises(DomainError) as c: record_spend(MONTH,100,'ads',self.user,date(2027,2,15))
        self.assertEqual(c.exception.code,'PAYBACK_BEYOND_60_DAYS')
        self.assertEqual(record_spend(MONTH,100,'ads',self.user,date(2027,1,30)).kind,'spend')
        with self.assertRaises(CommandError):
            call_command('revenue_report','--month','2026-12','--record-spend','5','--approved-by',self.user.email,'--payback-due','2027-06-01',stdout=io.StringIO())

    def test_revenue_currency_must_be_three_uppercase_letters(self):
        with self.assertRaises(IntegrityError),transaction.atomic(): self.entry('youtube',1,currency='inr')

    def set_aside(self,amount,month=MONTH):
        return ReinvestmentEntry.objects.create(month=month,kind='set_aside',amount_minor=amount,purpose='monthly set-aside')

    def test_manual_pass_entry_is_refused_to_avoid_double_counting(self):
        with self.assertRaises(IntegrityError),transaction.atomic(): self.entry('pass',1000)

    def test_record_spend_needs_a_positive_amount(self):
        from core.api import DomainError
        self.set_aside(1000)
        for amount in (0,-5,True,'5'):
            with self.assertRaises(DomainError) as c: record_spend(MONTH,amount,'ads',self.user,date(2026,12,31))
            self.assertEqual(c.exception.code,'SPEND_AMOUNT_INVALID',amount)
        with self.assertRaises(IntegrityError),transaction.atomic(): self.spend(amount_minor=0)

    def test_record_spend_needs_an_active_verified_staff_approver(self):
        from core.api import DomainError
        self.set_aside(1000)
        User=get_user_model()
        for email,kw in (('ns@example.test',dict(is_verified=True)),('nv@example.test',dict(is_staff=True)),
                         ('na@example.test',dict(is_staff=True,is_verified=True,is_active=False))):
            approver=User.objects.create_user(email,'Revenue-local-test-Strong47',**kw)
            with self.assertRaises(DomainError) as c: record_spend(MONTH,100,'ads',approver,date(2026,12,31))
            self.assertEqual(c.exception.code,'SPEND_APPROVER_INVALID',email)
        self.assertFalse(ReinvestmentEntry.objects.filter(kind='spend').exists())

    def test_spends_never_exceed_total_set_asides(self):
        from core.api import DomainError
        with self.assertRaises(DomainError) as c: record_spend(MONTH,1,'ads',self.user,date(2026,12,31))
        self.assertEqual(c.exception.code,'SPEND_EXCEEDS_SET_ASIDE')
        self.set_aside(600,month=date(2026,11,1));self.set_aside(400)
        self.assertEqual(record_spend(date(2026,11,1),700,'ads',self.user,date(2026,12,15)).amount_minor,700)
        self.assertEqual(record_spend(MONTH,300,'ads',self.user,date(2026,12,31)).amount_minor,300)  # exactly the total
        with self.assertRaises(DomainError) as c: record_spend(MONTH,1,'ads',self.user,date(2026,12,31))
        self.assertEqual(c.exception.code,'SPEND_EXCEEDS_SET_ASIDE')

    def test_bad_payback_date_is_a_command_error(self):
        for value in ('2027-13-01','soon'):
            with self.assertRaises(CommandError):
                call_command('revenue_report','--month','2026-12','--record-spend','5','--approved-by',self.user.email,'--payback-due',value,stdout=io.StringIO())

    def test_reinvest_share_percent_is_bounded(self):
        from django.core.exceptions import ImproperlyConfigured
        from config.settings import reinvest_share_percent
        self.assertEqual(reinvest_share_percent('30'),30)
        self.assertEqual((reinvest_share_percent('0'),reinvest_share_percent('100')),(0,100))
        for raw in ('-1','101','thirty','',' 3.5'):
            with self.assertRaises(ImproperlyConfigured): reinvest_share_percent(raw)
