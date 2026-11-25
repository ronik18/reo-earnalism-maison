from datetime import date
from django.core.management.base import BaseCommand,CommandError
from billing.models import ReinvestmentEntry
from billing.revenue import month_report

class Command(BaseCommand):
    help='Print the monthly revenue report; optionally record the reinvestment set-aside.'
    def add_arguments(self,parser):
        parser.add_argument('--month',required=True,help='YYYY-MM')
        parser.add_argument('--record-set-aside',action='store_true')
        parser.add_argument('--record-spend',type=int,metavar='AMOUNT_MINOR')
        parser.add_argument('--purpose',default='')
        parser.add_argument('--approved-by',help='approver email')
        parser.add_argument('--payback-due',help='YYYY-MM-DD')
    def handle(self,*args,**o):
        try: y,m=map(int,o['month'].split('-'));month=date(y,m,1)
        except ValueError: raise CommandError('--month must be YYYY-MM')
        if o['record_spend'] is not None:
            from django.contrib.auth import get_user_model
            from billing.revenue import record_spend
            from core.api import DomainError
            user=get_user_model().objects.filter(email=o['approved_by']).first()
            try: payback=date.fromisoformat(o['payback_due']) if o['payback_due'] else None
            except ValueError: raise CommandError('--payback-due must be YYYY-MM-DD')
            try: record_spend(month,o['record_spend'],o['purpose'],user,payback)
            except DomainError as e: raise CommandError(str(e))
        r=month_report(month);w=self.stdout.write
        w(f"Revenue report {month:%Y-%m} (INR minor units)")
        for s,v in r['by_source'].items(): w(f"{(s+' (invoiced; capture not verified; refunds not deducted)') if s=='pass' else s:<12}{v:>14}")
        w(f"{'total':<12}{r['total_minor']:>14}")
        w(f"{'set-aside (on invoiced figures)':<12}{r['set_aside_due_minor']:>14}")
        for c,v in r['other_currencies'].items(): w(f"other currency {c}: {v} (not included)")
        w(f"spends: {len(r['spends'])}")
        for s in r['overdue_paybacks']: w(f"OVERDUE payback: spend {s['id']} {s['amount_minor']} due {s['payback_due']}")
        if o['record_set_aside']:
            _,created=ReinvestmentEntry.objects.get_or_create(month=month,kind='set_aside',defaults={'amount_minor':r['set_aside_due_minor'],'purpose':'monthly set-aside'})
            w('set-aside recorded' if created else 'set-aside already recorded')
