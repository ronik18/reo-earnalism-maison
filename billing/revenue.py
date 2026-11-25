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
    invoices=Invoice.objects.filter(subscription__plan__offer__code__startswith='founding-pass-',issued_at__date__gte=start,issued_at__date__lt=end)
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
    """Owner-approved growth spend; payback must fall within 60 days of the month start."""
    from core.api import DomainError
    start=month.replace(day=1)
    if approved_by is None or payback_due is None: raise DomainError('APPROVAL_REQUIRED','A spend needs an approver and a payback date.',422)
    if payback_due>start+timedelta(days=60): raise DomainError('PAYBACK_BEYOND_60_DAYS','Payback must be due within 60 days.',422)
    return ReinvestmentEntry.objects.create(month=start,kind='spend',amount_minor=amount_minor,purpose=purpose,approved_by=approved_by,payback_due=payback_due,paid_back=False)
