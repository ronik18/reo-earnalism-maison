"""Monthly revenue report: every income source, and the reinvestment share due."""
from datetime import date,timedelta
from django.conf import settings
from django.db.models import Sum
from django.utils import timezone
from .models import Invoice,RevenueEntry,ReinvestmentEntry
from .revenue_models import SOURCES

def month_report(month):
    start=month.replace(day=1)
    end=date(start.year+(start.month==12),start.month%12+1,1)
    by_source={s:0 for s in SOURCES};other={}
    # Subscription invoices cannot carry PaymentAllocation rows (DB guard maison_payment_allocation_guard),
    # so pass revenue is INVOICED (issued subscription-cycle invoices); capture is not verified and refunds are not deducted.
    # Test-only (sandbox) offers are never revenue. Manual RevenueEntry rows cannot use source 'pass' (DB check),
    # so Pass revenue is counted once, from invoices only.
    invoices=Invoice.objects.filter(subscription__plan__offer__code__startswith='founding-pass-',subscription__plan__offer__test_only=False,
        issued_at__date__gte=start,issued_at__date__lt=end)
    for row in invoices.values('currency').annotate(total=Sum('amount_minor')):
        if row['currency']=='INR': by_source['pass']+=row['total']
        else: other[row['currency']]=other.get(row['currency'],0)+row['total']
    for row in RevenueEntry.objects.filter(month=start).values('source','currency').annotate(total=Sum('amount_minor')):
        if row['currency']=='INR': by_source[row['source']]+=row['total']
        else: other[row['currency']]=other.get(row['currency'],0)+row['total']
    total=sum(by_source.values())
    cols=('id','month','amount_minor','purpose','approved_by_id','payback_due','paid_back')
    spends=list(ReinvestmentEntry.objects.filter(month=start,kind='spend').order_by('id').values(*cols))
    today=timezone.localdate()
    overdue=list(ReinvestmentEntry.objects.filter(kind='spend',payback_due__lt=today).exclude(paid_back=True).order_by('month','id').values(*cols))
    return {'month':start,'by_source':by_source,'pass_basis':'invoiced','other_currencies':other,'total_minor':total,
        'set_aside_due_minor':total*settings.MAISON_REINVEST_SHARE_PERCENT//100,'spends':spends,'overdue_paybacks':overdue}

def record_spend(month,amount_minor,purpose,approved_by,payback_due):
    """Owner-approved growth spend, only from money already set aside: payback within 60 days of the month start,
    an active verified staff approver, a positive amount, and all spends ever never above all set-asides ever."""
    from core.api import DomainError
    from django.db import transaction
    start=month.replace(day=1)
    if approved_by is None or payback_due is None: raise DomainError('APPROVAL_REQUIRED','A spend needs an approver and a payback date.',422)
    if type(amount_minor) is not int or amount_minor<=0: raise DomainError('SPEND_AMOUNT_INVALID','A spend amount must be a positive whole number of minor units.',422)
    if not (approved_by.is_active and approved_by.is_staff and approved_by.is_verified):
        raise DomainError('SPEND_APPROVER_INVALID','The approver must be an active, verified staff account.',422)
    if payback_due>start+timedelta(days=60): raise DomainError('PAYBACK_BEYOND_60_DAYS','Payback must be due within 60 days.',422)
    with transaction.atomic():
        # Lock the set-aside rows so concurrent spends are checked one at a time against committed totals.
        list(ReinvestmentEntry.objects.select_for_update().filter(kind='set_aside').values_list('pk',flat=True))
        totals={row['kind']:row['total'] for row in ReinvestmentEntry.objects.values('kind').annotate(total=Sum('amount_minor'))}
        if totals.get('spend',0)+amount_minor>totals.get('set_aside',0):
            raise DomainError('SPEND_EXCEEDS_SET_ASIDE','Total spends would exceed the total set aside from earned revenue.',422)
        return ReinvestmentEntry.objects.create(month=start,kind='spend',amount_minor=amount_minor,purpose=purpose,approved_by=approved_by,payback_due=payback_due,paid_back=False)
