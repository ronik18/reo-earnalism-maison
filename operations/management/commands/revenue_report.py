from datetime import date
from django.core.management.base import BaseCommand,CommandError
from billing.models import ReinvestmentEntry
from billing.revenue import month_report,record_set_aside
from core.api import DomainError

class Command(BaseCommand):
    help='Print the monthly revenue report; optionally record the reinvestment set-aside.'
    def add_arguments(self,parser):
        parser.add_argument('--month',required=True,help='YYYY-MM')
        parser.add_argument('--record-set-aside',action='store_true')
        parser.add_argument('--update-set-aside',action='store_true',help='With --record-set-aside: change an existing row whose amount differs (audited).')
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
            try: row,state=record_set_aside(month,r['set_aside_due_minor'],update=o['update_set_aside'])
            except DomainError as e:
                if e.code=='SET_ASIDE_DIFFERS':
                    recorded=ReinvestmentEntry.objects.get(month=month,kind='set_aside').amount_minor
                    w(f"set-aside recorded: {recorded}; computed now: {r['set_aside_due_minor']}")
                raise CommandError(str(e))
            w({'created':'set-aside recorded','unchanged':'set-aside already recorded','updated':f"set-aside updated to {row.amount_minor}"}[state])
