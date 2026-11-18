"""Opt-in SMTP qualification. Never equates submission with inbox delivery."""
import hashlib
import json
import ssl
import uuid
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail.backends.smtp import EmailBackend
from django.core.management.base import BaseCommand,CommandError
from django.core.validators import validate_email
from django.utils import timezone
from core.api import DomainError


class Command(BaseCommand):
    help='Plan by default; optionally verify configured SMTP TLS/EHLO/authentication and explicitly permitted synthetic submission.'
    def add_arguments(self,parser):
        parser.add_argument('--connect',action='store_true',help='Permit DNS/TLS/EHLO requests to configured SMTP. Sends no message.')
        parser.add_argument('--authenticate',action='store_true',help='With --connect, authenticate using existing environment credentials; sends no message.')
        parser.add_argument('--send',action='store_true',help='Submit one explicit synthetic test through the existing app adapter.')
        parser.add_argument('--to',dest='recipient',help='Explicit owner-authorized test recipient. Never printed in reports.')
        parser.add_argument('--allow-test-email',action='store_true',help='Explicitly permit sending the requested synthetic test email.')

    def handle(self,*args,**options):
        if options['authenticate'] and not options['connect']:raise CommandError('--authenticate requires --connect. No requests made.')
        if options['send'] and not (options['connect'] and options['authenticate'] and options['allow_test_email'] and options['recipient']):
            raise CommandError('--send requires --connect --authenticate --allow-test-email and an explicitly authorized --to recipient. No requests made.')
        if options['recipient'] or options['allow_test_email']:
            if not options['send']:raise CommandError('Recipient/send permission is only used with --send. No requests made.')
        if options['send']:
            try:validate_email(options['recipient'])
            except ValidationError:raise CommandError('A valid explicit test recipient is required. No requests made.') from None
        report={'schema_version':1,'scope':'smtp_transport_only','connection':'not_requested','tls':'not_requested','ehlo':'not_requested',
            'authentication':'not_requested','submission':'not_requested','delivery_confirmed':False,'inbox_placement_verified':False}
        if not options['connect']:
            report['status']='plan';self.stdout.write(json.dumps(report,sort_keys=True));return
        if settings.EMAIL_BACKEND!='django.core.mail.backends.smtp.EmailBackend':
            raise CommandError('Configured application email backend must be SMTP. No requests made.')
        use_ssl=bool(getattr(settings,'EMAIL_USE_SSL',False));use_tls=bool(getattr(settings,'EMAIL_USE_TLS',False))
        if use_ssl==use_tls or not getattr(settings,'EMAIL_HOST',''):
            raise CommandError('Configure one verified TLS mode (SSL or STARTTLS) and SMTP host. No requests made.')
        username=getattr(settings,'EMAIL_HOST_USER','');password=getattr(settings,'EMAIL_HOST_PASSWORD','')
        if options['authenticate'] and (not username or not password):raise CommandError('SMTP authentication requires existing environment credentials. No requests made.')
        try:timeout=min(8,float(getattr(settings,'EMAIL_TIMEOUT',8) or 8))
        except (TypeError,ValueError):raise CommandError('SMTP timeout must be a positive number no greater than8seconds.') from None
        if not 0<timeout<=8:raise CommandError('SMTP timeout must be positive and bounded to8seconds.')
        # Empty credentials deliberately prevent Django.open() from authenticating during --connect.
        backend=EmailBackend(username='',password='',timeout=timeout,fail_silently=False)
        context=backend.ssl_context
        if not context.check_hostname or context.verify_mode!=ssl.CERT_REQUIRED:
            raise CommandError('SMTP TLS hostname/certificate verification must be enabled. No requests made.')
        stage='connection'
        try:
            backend.open()
            if backend.connection is None:raise RuntimeError('no SMTP connection')
            report['connection']='pass';stage='tls'
            sock=backend.connection.sock
            if not isinstance(sock,ssl.SSLSocket) or not sock.getpeercert():raise RuntimeError('no verified TLS peer')
            sock.settimeout(timeout);report['tls']='pass';stage='ehlo'
            code,_=backend.connection.ehlo()
            if not 200<=code<300:raise RuntimeError('EHLO rejected')
            report['ehlo']='pass'
            if options['authenticate']:
                stage='authentication';code,_=backend.connection.login(username,password)
                if code!=235:raise RuntimeError('authentication not accepted')
                report['authentication']='pass'
        except Exception:
            # SMTP exceptions can contain addresses, usernames or server responses. Never serialize them.
            report[stage]='fail';report['status']='fail'
            self.stdout.write(json.dumps(report,sort_keys=True))
            raise CommandError('SMTP transport qualification failed; see the redacted stage report.') from None
        finally:
            try:backend.close()
            except Exception:pass
        if options['send']:
            report['submission']=self._submit(options['recipient'])
        report['status']='pass' if report['submission']!='unknown' else 'fail'
        self.stdout.write(json.dumps(report,sort_keys=True))
        if report['status']=='fail':raise CommandError('SMTP submission outcome is unknown; reconcile the durable probe job before resending.')

    def _submit(self,recipient):
        from core.models import OutboxJob
        from accounts.email_delivery import submit_message
        now=timezone.now();identity=uuid.uuid4();owner=str(uuid.uuid4())
        job=OutboxJob.objects.create(kind='email_transport_probe',dedupe_key=f'email-transport-probe:{identity}',status='claimed',
            payload={'purpose':'explicit_synthetic_transport_probe','recipient_sha256':hashlib.sha256(recipient.encode()).hexdigest()},
            not_before=now,lease_owner=owner,locked_until=now+timedelta(seconds=60))
        try:
            result=submit_message(job,'Earnalism requested SMTP transport test',
                'This is an explicitly requested synthetic Earnalism email transport test. SMTP acceptance does not establish inbox delivery.',[recipient],max_seconds=8)
            if result.get('smtp_submission_accepted') is not True:raise DomainError('email_submission_uncertain','Submission not confirmed.',503)
        except Exception as exc:
            # Keep unknown outcomes durable and blocked; never automatically repeat this optional test.
            OutboxJob.objects.filter(pk=job.pk,status='claimed',lease_owner=owner).update(status='blocked',locked_until=None,lease_owner='',
                error_code=exc.code if isinstance(exc,DomainError) else 'email_submission_uncertain')
            return 'unknown'
        OutboxJob.objects.filter(pk=job.pk,status='claimed',lease_owner=owner).update(status='done',locked_until=None,lease_owner='',completed_at=timezone.now(),
            result={'smtp_submission_accepted':True,'delivery_confirmed':False})
        return 'accepted'
