from datetime import date
from django.core.management.base import BaseCommand,CommandError
from billing.models import ReinvestmentEntry
from billing.revenue import month_report

class Command(BaseCommand):
    help='Print the monthly revenue report; optionally record the reinvestment set-aside.'
    def add_arguments(self,parser):
        parser.add_argument('--month',required=True,help='YYYY-MM')
        parser.add_argument('--record-set-aside',action='store_true')
    def handle(self,*args,**o):
        try: y,m=map(int,o['month'].split('-'));month=date(y,m,1)
        except ValueError: raise CommandError('--month must be YYYY-MM')
        r=month_report(month);w=self.stdout.write
        w(f"Revenue report {month:%Y-%m} (INR minor units)")
        for s,v in r['by_source'].items(): w(f"{s:<12}{v:>14}")
        w(f"{'total':<12}{r['total_minor']:>14}")
        w(f"{'set-aside':<12}{r['set_aside_due_minor']:>14}")
        for c,v in r['other_currencies'].items(): w(f"other currency {c}: {v} (not included)")
        w(f"spends: {len(r['spends'])}")
        for s in r['overdue_paybacks']: w(f"OVERDUE payback: spend {s['id']} {s['amount_minor']} due {s['payback_due']}")
        if o['record_set_aside']:
            _,created=ReinvestmentEntry.objects.get_or_create(month=month,kind='set_aside',defaults={'amount_minor':r['set_aside_due_minor'],'purpose':'monthly set-aside'})
            w('set-aside recorded' if created else 'set-aside already recorded')
