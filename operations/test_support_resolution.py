import io
import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from accounts.support_resolution import resolve_support_case
from core.models import AuditEvent, OutboxJob


class SupportResolutionTests(TestCase):
    def setUp(self):
        self.now=timezone.now()
        self.operator=User.objects.create_user('support-operator@example.test',is_staff=True)
        self.member=User.objects.create_user('support-member@example.test',is_verified=True)
        self.job=OutboxJob.objects.create(kind='contact_support',actor=self.member,dedupe_key=uuid.uuid4().hex,
            status='done',not_before=self.now,completed_at=self.now-timedelta(days=120),
            payload={'email':'private@example.test','message':'private support text','email_outcome':'submitting'},
            result={'status':'submitted','smtp_submission_accepted':True})
        self.args=dict(operator_id=self.operator.public_id,job_id=self.job.id,resolution_ref='CASE-42')

    def test_preview_is_nonmutating_and_output_never_contains_message_or_email(self):
        output=io.StringIO()
        call_command('resolve_support_case',job=str(self.job.pk),operator=str(self.operator.public_id),resolution_ref='CASE-42',stdout=output)
        data=json.loads(output.getvalue())
        self.assertTrue(data['dry_run']);self.assertFalse(data['changed'])
        self.assertTrue(data['requires_obligation_review'])
        self.job.refresh_from_db();self.assertNotIn('retention_case',self.job.result)
        self.assertEqual(AuditEvent.objects.count(),0)
        self.assertNotIn('private',output.getvalue());self.assertNotIn('@',output.getvalue())

    def test_apply_current_timestamp_is_idempotent_and_never_uses_smtp_completion_as_resolution(self):
        with patch('accounts.support_resolution.timezone.now',return_value=self.now):
            first=resolve_support_case(**self.args,apply=True,obligations_reviewed=True)
        self.assertTrue(first['changed']);self.assertEqual(first['resolved_at'],self.now.isoformat().replace('+00:00','Z'))
        self.job.refresh_from_db();case=dict(self.job.result['retention_case'])
        later=self.now+timedelta(days=5)
        with patch('accounts.support_resolution.timezone.now',return_value=later):
            second=resolve_support_case(**self.args,apply=True,obligations_reviewed=True)
        self.assertFalse(second['changed']);self.job.refresh_from_db();self.assertEqual(self.job.result['retention_case'],case)
        self.assertEqual(AuditEvent.objects.filter(action='support.resolved').count(),1)
        with self.assertRaises(CommandError):resolve_support_case(**{**self.args,'resolution_ref':'DIFFERENT'},apply=True,obligations_reviewed=True)

    def test_requires_actual_staff_and_obligation_attestation(self):
        with self.assertRaises(CommandError):resolve_support_case(**{**self.args,'operator_id':self.member.public_id},apply=True,obligations_reviewed=True)
        self.operator.is_active=False;self.operator.save()
        with self.assertRaises(CommandError):resolve_support_case(**self.args,apply=True,obligations_reviewed=True)
        self.operator.is_active=True;self.operator.save()
        with self.assertRaises(CommandError):resolve_support_case(**self.args,apply=True)
        self.job.refresh_from_db();self.assertNotIn('retention_case',self.job.result)

    def test_pending_unknown_wrong_category_and_all_holds_rejected(self):
        for status in ['pending','claimed','blocked','dead','cancelled']:
            self.job.status=status;self.job.save()
            with self.assertRaises(CommandError):resolve_support_case(**self.args,apply=True,obligations_reviewed=True)
        self.job.status='done';self.job.payload['email_outcome']='unknown';self.job.save()
        with self.assertRaises(CommandError):resolve_support_case(**self.args,apply=True,obligations_reviewed=True)
        self.job.payload['email_outcome']='submitting';self.job.kind='email_action';self.job.save()
        with self.assertRaises(CommandError):resolve_support_case(**self.args,apply=True,obligations_reviewed=True)
        self.job.kind='contact_support';self.job.payload['legal_hold']=True;self.job.save()
        with self.assertRaises(CommandError):resolve_support_case(**self.args,apply=True,obligations_reviewed=True)
        self.job.payload.pop('legal_hold');self.job.save()
        AuditEvent.objects.create(action='retention.hold',entity_kind='OutboxJob',entity_id=str(self.job.pk))
        with self.assertRaises(CommandError):resolve_support_case(**self.args,apply=True,obligations_reviewed=True)

    def test_rejects_untrusted_identifiers_references_and_existing_malformed_metadata(self):
        for changes in [{'job_id':'bad'},{'operator_id':'bad'},{'resolution_ref':'https://secret.test/x'},
                        {'resolution_ref':'contains message spaces'},{'resolution_ref':'x'*81},{'apply':'yes'}]:
            with self.assertRaises(CommandError):resolve_support_case(**{**self.args,**changes})
        self.job.result['retention_case']={'resolved_at':'not-a-date'};self.job.save()
        with self.assertRaises(CommandError):resolve_support_case(**self.args,apply=True,obligations_reviewed=True)

    def test_cli_apply_records_resolution_without_provider_calls(self):
        output=io.StringIO()
        with patch('accounts.email_delivery.submit_message') as submit:
            call_command('resolve_support_case',job=str(self.job.pk),operator=str(self.operator.public_id),
                         resolution_ref='CASE-CLI',apply=True,no_outstanding_obligation=True,stdout=output)
        data=json.loads(output.getvalue());self.assertTrue(data['changed']);self.assertFalse(data['mailbox_modified'])
        self.job.refresh_from_db();self.assertEqual(self.job.result['retention_case']['resolution_ref'],'CASE-CLI')
        submit.assert_not_called()
