import io
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from core.api import DomainError
from core.jobs import run_due_jobs
from core.models import AuditEvent, OutboxJob
from library import services
from library.models import Edition, Rights
from operations.publication import process_scheduled_publication


class ScheduledPublicationTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        options = override_settings(MEDIA_ROOT=directory.name, MAISON_LOCAL_FIXTURES=True, LOCAL=True)
        options.enable(); self.addCleanup(options.disable)
        call_command('seed_local_pilot', stdout=io.StringIO())
        self.publisher = get_user_model().objects.create_superuser('scheduler@example.test', 'Test-Only-Passphrase-47')
        self.edition = Edition.objects.get(pk='20000000-0000-4000-8000-000000000001')
        self.original_live = self.edition.live_revision_id
        self.revision = services.clone_revision(self.original_live)
        Rights.objects.filter(revision=self.revision).update(approved=True)
        self.revision.refresh_from_db()
        self.revision.validation_evidence = {'browser': {'status': 'pass', 'sha256': self.revision.content_sha256,
                                                        'scope': 'local_test_only'}}
        self.revision.save()

    def schedule(self):
        self.revision.refresh_from_db()
        state = services.transition_revision(self.publisher, self.revision.id, 'mark-ready', self.revision.version,
                                             self.revision.content_sha256, 'Synthetic local acceptance only')
        self.due = timezone.now() + timedelta(minutes=1)
        services.transition_revision(self.publisher, self.revision.id, 'schedule', state['version'],
                                     self.revision.content_sha256, 'Synthetic local acceptance only', self.due)
        self.revision.refresh_from_db()
        return OutboxJob.objects.get(dedupe_key=f'scheduled-publication:{self.revision.id}:{self.revision.version}')

    def test_real_due_worker_publishes_exact_revision_and_audits_once(self):
        job = self.schedule()
        with patch('operations.publication.timezone.now', return_value=self.due + timedelta(seconds=1)):
            self.assertEqual(run_due_jobs(limit=1, max_seconds=5), {'processed': 1})
            self.assertEqual(process_scheduled_publication(job), {'status': 'skipped', 'reason': 'revision_superseded'})
        job.refresh_from_db(); self.edition.refresh_from_db()
        self.assertEqual(job.status, 'done'); self.assertEqual(job.result['status'], 'published')
        self.assertEqual(self.edition.live_revision_id, self.revision.id)
        self.assertEqual(AuditEvent.objects.filter(action='content.publish', entity_id=str(self.revision.id)).count(), 1)

    def test_reschedule_makes_old_job_inert_and_draft_is_never_promoted(self):
        old = self.schedule()
        services.transition_revision(self.publisher, self.revision.id, 'schedule', self.revision.version,
                                     self.revision.content_sha256, 'Synthetic reschedule', self.due + timedelta(hours=1))
        with patch('operations.publication.timezone.now', return_value=self.due + timedelta(seconds=1)):
            self.assertEqual(process_scheduled_publication(old)['status'], 'skipped')
        self.edition.refresh_from_db(); self.assertEqual(self.edition.live_revision_id, self.original_live)

    def test_expired_authority_and_revoked_rights_hold_without_publication(self):
        job = self.schedule()
        self.publisher.is_active = False; self.publisher.save(update_fields=['is_active'])
        with patch('operations.publication.timezone.now', return_value=self.due + timedelta(seconds=1)):
            with self.assertRaises(DomainError) as error:
                process_scheduled_publication(job)
            self.assertEqual(error.exception.code, 'scheduled_publication_held')
        self.publisher.is_active = True; self.publisher.save(update_fields=['is_active'])
        Rights.objects.filter(revision=self.revision).update(approved=False)
        with patch('operations.publication.timezone.now', return_value=self.due + timedelta(seconds=1)):
            run_due_jobs(limit=1, max_seconds=5)
        job.refresh_from_db(); self.edition.refresh_from_db()
        self.assertEqual(job.status, 'blocked'); self.assertEqual(job.error_code, 'scheduled_publication_held')
        self.assertEqual(self.edition.live_revision_id, self.original_live)

    def test_premature_job_and_tampered_actor_do_not_publish(self):
        job = self.schedule()
        with self.assertRaises(DomainError) as error:
            process_scheduled_publication(job)
        self.assertEqual(error.exception.code, 'scheduled_publication_invalid')
        job.payload = {**job.payload, 'actor_id': str(self.publisher.pk + 1)}
        with self.assertRaises(DomainError) as error:
            process_scheduled_publication(job)
        self.assertEqual(error.exception.code, 'scheduled_publication_invalid')

    def test_audit_failure_rolls_back_live_pointer_and_publication(self):
        job = self.schedule()
        with patch('operations.publication.timezone.now', return_value=self.due + timedelta(seconds=1)), \
                patch('operations.publication.audit', side_effect=RuntimeError('local synthetic failure')):
            with self.assertRaises(RuntimeError):
                process_scheduled_publication(job)
        self.edition.refresh_from_db(); self.revision.refresh_from_db()
        self.assertEqual(self.edition.live_revision_id, self.original_live)
        self.assertEqual(self.revision.state, 'ready')
