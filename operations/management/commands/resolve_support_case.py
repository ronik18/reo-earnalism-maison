import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Preview or record actual operator-confirmed support resolution. Management-shell access '
            'is the authorization boundary; --operator attributes the existing active staff member '
            'and does not assert browser MFA. Does not send mail or modify mailbox copies.')

    def add_arguments(self, parser):
        parser.add_argument('--job', required=True, help='Exact contact_support job UUID.')
        parser.add_argument('--operator', required=True, help='Existing active staff public UUID.')
        parser.add_argument('--resolution-ref', required=True, help='Opaque operator case reference, no message text or URLs.')
        parser.add_argument('--apply', action='store_true', help='Record resolution now; default is a nonmutating preview.')
        parser.add_argument('--no-outstanding-obligation', action='store_true',
                            help='Attest the case is actually resolved and has no outstanding dispute/legal/financial obligation.')

    def handle(self, *args, **options):
        from accounts.support_resolution import resolve_support_case
        result = resolve_support_case(
            operator_id=options['operator'], job_id=options['job'],
            resolution_ref=options['resolution_ref'], apply=options['apply'],
            obligations_reviewed=options['no_outstanding_obligation'])
        self.stdout.write(json.dumps(result, sort_keys=True))
