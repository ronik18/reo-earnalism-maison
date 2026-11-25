"""Monthly revenue report: every income source, and the reinvestment share due."""
from datetime import date
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
    # so a founding-pass receipt is the issued subscription-cycle invoice itself.
    invoices=Invoice.objects.filter(subscription__plan__offer__code__startswith='founding-pass-',issued_at__date__gte=start,issued_at__date__lt=end)
    for row in invoices.values('currency').annotate(total=Sum('amount_minor')):
        if row['currency']=='INR': by_source['pass']+=row['total']
        else: other[row['currency']]=other.get(row['currency'],0)+row['total']
    for row in RevenueEntry.objects.filter(month=start).values('source','currency').annotate(total=Sum('amount_minor')):
        if row['currency']=='INR': by_source[row['source']]+=row['total']
        else: other[row['currency']]=other.get(row['currency'],0)+row['total']
    total=sum(by_source.values())
    spends=list(ReinvestmentEntry.objects.filter(month=start,kind='spend').order_by('id').values('id','amount_minor','purpose','approved_by_id','payback_due','paid_back'))
    today=timezone.localdate()
    overdue=[s for s in spends if s['payback_due']<today and s['paid_back'] is not True]
    return {'month':start,'by_source':by_source,'other_currencies':other,'total_minor':total,
        'set_aside_due_minor':total*settings.MAISON_REINVEST_SHARE_PERCENT//100,'spends':spends,'overdue_paybacks':overdue}
