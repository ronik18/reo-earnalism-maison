import io
import json
import ssl
from unittest.mock import Mock,patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase,TestCase,override_settings
from core.api import DomainError

SMTP_SETTINGS={'EMAIL_BACKEND':'django.core.mail.backends.smtp.EmailBackend','EMAIL_HOST':'smtp.example.test','EMAIL_USE_SSL':True,'EMAIL_USE_TLS':False,
    'EMAIL_TIMEOUT':20,'EMAIL_HOST_USER':'never-print-user','EMAIL_HOST_PASSWORD':'never-print-password'}

@override_settings(**SMTP_SETTINGS)
class EmailTransportQualificationTests(SimpleTestCase):
    def backend(self):
        backend=Mock();backend.ssl_context=ssl.create_default_context()
        sock=Mock(spec=ssl.SSLSocket);sock.getpeercert.return_value={'subject':'synthetic-test-only'}
        backend.connection.sock=sock;backend.connection.ehlo.return_value=(250,b'capabilities');backend.connection.login.return_value=(235,b'ok')
        return backend

    def run_command(self,**options):
        output=io.StringIO();call_command('qualify_email_transport',stdout=output,**options);return json.loads(output.getvalue())

    def test_default_plan_is_network_free_and_redacted(self):
        with patch('operations.management.commands.qualify_email_transport.EmailBackend') as backend:
            result=self.run_command()
        backend.assert_not_called();self.assertEqual(result['status'],'plan');self.assertFalse(result['delivery_confirmed'])
        self.assertNotIn('never-print',str(result))

    def test_connect_does_tls_ehlo_without_authentication_or_message(self):
        backend=self.backend()
        with patch('operations.management.commands.qualify_email_transport.EmailBackend',return_value=backend) as factory:
            result=self.run_command(connect=True)
        self.assertEqual(factory.call_args.kwargs['username'],'');self.assertEqual(factory.call_args.kwargs['password'],'');self.assertEqual(factory.call_args.kwargs['timeout'],8)
        backend.connection.login.assert_not_called();self.assertEqual(result['ehlo'],'pass');self.assertEqual(result['authentication'],'not_requested');backend.close.assert_called_once()

    def test_authentication_is_separate_and_uses_only_existing_credentials(self):
        backend=self.backend()
        with patch('operations.management.commands.qualify_email_transport.EmailBackend',return_value=backend):result=self.run_command(connect=True,authenticate=True)
        backend.connection.login.assert_called_once_with('never-print-user','never-print-password')
        self.assertEqual(result['authentication'],'pass');self.assertEqual(result['submission'],'not_requested');self.assertNotIn('never-print',str(result))

    def test_explicit_send_permission_and_existing_credentials_required_before_network(self):
        with patch('operations.management.commands.qualify_email_transport.EmailBackend') as backend:
            for options in [{'authenticate':True},{'send':True},{'connect':True,'authenticate':True,'send':True,'recipient':'allowed@example.test'}]:
                with self.subTest(options=options),self.assertRaises(CommandError):self.run_command(**options)
            with override_settings(EMAIL_HOST_PASSWORD=''),self.assertRaises(CommandError):self.run_command(connect=True,authenticate=True)
            backend.assert_not_called()

    def test_explicit_send_flags_route_through_existing_submission_adapter(self):
        backend=self.backend()
        with patch('operations.management.commands.qualify_email_transport.EmailBackend',return_value=backend),patch('operations.management.commands.qualify_email_transport.Command._submit',return_value='accepted') as submit:
            result=self.run_command(connect=True,authenticate=True,send=True,allow_test_email=True,recipient='explicit@example.test')
        submit.assert_called_once_with('explicit@example.test');self.assertEqual(result['submission'],'accepted')
        self.assertFalse(result['inbox_placement_verified']);self.assertNotIn('explicit@example.test',str(result))

    def test_tls_verification_cannot_be_disabled_and_errors_remain_redacted(self):
        backend=self.backend();backend.ssl_context.check_hostname=False
        with patch('operations.management.commands.qualify_email_transport.EmailBackend',return_value=backend),self.assertRaises(CommandError):self.run_command(connect=True)
        backend.open.assert_not_called()
        backend=self.backend();backend.connection.ehlo.side_effect=RuntimeError('never-print-password recipient@example.test token=secret')
        output=io.StringIO()
        with patch('operations.management.commands.qualify_email_transport.EmailBackend',return_value=backend),self.assertRaises(CommandError) as error:
            call_command('qualify_email_transport',connect=True,stdout=output)
        self.assertNotIn('never-print',output.getvalue()+str(error.exception));self.assertNotIn('recipient@',output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['ehlo'],'fail')

@override_settings(**SMTP_SETTINGS)
class EmailTransportSubmissionTests(TestCase):
    def test_submission_uses_app_adapter_and_never_claims_inbox_delivery(self):
        from operations.management.commands.qualify_email_transport import Command
        from core.models import OutboxJob
        def accepted(job,subject,body,recipients,**kwargs):
            stored=OutboxJob.objects.get(pk=job.pk)
            self.assertEqual(stored.status,'claimed');self.assertEqual(recipients,['explicit@example.test']);self.assertEqual(kwargs['max_seconds'],8)
            self.assertNotIn('token=',body);self.assertNotIn('explicit@example.test',str(stored.payload))
            return {'smtp_submission_accepted':True,'delivery_confirmed':False}
        with patch('accounts.email_delivery.submit_message',side_effect=accepted):result=Command()._submit('explicit@example.test')
        self.assertEqual(result,'accepted');job=OutboxJob.objects.get();self.assertEqual(job.status,'done');self.assertFalse(job.result['delivery_confirmed'])

    def test_unknown_submission_is_durable_blocked_not_resent(self):
        from operations.management.commands.qualify_email_transport import Command
        from core.models import OutboxJob
        with patch('accounts.email_delivery.submit_message',side_effect=DomainError('email_submission_uncertain','secret provider text',503)) as send:
            self.assertEqual(Command()._submit('explicit@example.test'),'unknown');send.assert_called_once()
        job=OutboxJob.objects.get();self.assertEqual(job.status,'blocked');self.assertEqual(job.error_code,'email_submission_uncertain')
