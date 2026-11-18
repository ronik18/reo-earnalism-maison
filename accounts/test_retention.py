import uuid
from datetime import timedelta
from django.contrib.sessions.models import Session
from django.test import TestCase
from django.utils import timezone
from core.models import AuditEvent, OperationReceipt, OutboxJob
from .models import User, EmailActionToken, Preferences, Device
from .retention import cleanup_account_retention


class RetentionTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.member = User.objects.create_user('member@example.test', is_verified=True)

    def action(self, user=None, days=9, status='done', outcome='submitted'):
        action = EmailActionToken.objects.create(user=user or self.member, email_normalized='mail@example.test', purpose='verify_email', token_sha256=uuid.uuid4().hex, expires_at=self.now-timedelta(days=days))
        EmailActionToken.objects.filter(pk=action.pk).update(created_at=self.now-timedelta(days=days+1))
        job = OutboxJob.objects.create(kind='email_action', actor=user or self.member, dedupe_key=uuid.uuid4().hex, payload={'action_id':str(action.pk), 'email_outcome':'submitting'}, status=status, not_before=self.now, result={'status':outcome}, completed_at=self.now-timedelta(days=days))
        return action, job

    def test_preview_has_no_writes_and_apply_scrubs_exact_terminal_category(self):
        action, job = self.action()
        preview = cleanup_account_retention()
        self.assertTrue(preview['dry_run']); self.assertEqual(preview['eligible']['action_tokens'], 1)
        self.assertTrue(EmailActionToken.objects.filter(pk=action.pk).exists())
        job.refresh_from_db(); self.assertIn('action_id',job.payload)
        result = cleanup_account_retention(dry_run=False)
        self.assertEqual(result['eligible']['action_tokens'],1)
        self.assertFalse(EmailActionToken.objects.filter(pk=action.pk).exists())
        job.refresh_from_db(); self.assertEqual(job.payload,{'retention_cleaned':True})
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['action_tokens'],0)

    def test_pending_uncertain_hold_and_recent_tokens_are_preserved(self):
        for status,outcome in [('pending','submitted'),('claimed','submitted'),('dead','submitted'),('done','unknown')]:
            self.action(status=status,outcome=outcome)
        action, job = self.action(); job.payload['legal_hold']=True; job.save()
        self.action(days=6)
        cleanup_account_retention(dry_run=False)
        self.assertEqual(EmailActionToken.objects.count(),6)

    def test_consumed_token_retains_seven_days_not_original_expiry(self):
        action, _ = self.action(days=-2)
        action.consumed_at=self.now-timedelta(days=8); action.save()
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['action_tokens'],1)

    def test_sessions_devices_and_receipts_obey_expiry_and_35_day_floor(self):
        old=Session.objects.create(session_key='old-session',session_data='private',expire_date=self.now-timedelta(seconds=1))
        current=Session.objects.create(session_key='current-session',session_data='private',expire_date=self.now+timedelta(days=1))
        Device.objects.create(user=self.member,session=old,token_binding_sha256='x'*64,expires_at=self.now-timedelta(seconds=1))
        Device.objects.create(user=self.member,session=current,token_binding_sha256='y'*64,expires_at=self.now+timedelta(days=1))
        def receipt(days,expires):
            row=OperationReceipt.objects.create(actor=self.member,operation_id=uuid.uuid4(),kind='progress.update',request_sha256='z'*64,http_status=200,response={},expires_at=expires)
            OperationReceipt.objects.filter(pk=row.pk).update(created_at=self.now-timedelta(days=days)); return row
        expired=receipt(36,self.now-timedelta(days=1)); fresh=receipt(2,self.now-timedelta(days=1)); valid=receipt(36,self.now+timedelta(days=1))
        report=cleanup_account_retention(dry_run=False)['eligible']
        self.assertEqual((report['sessions'],report['devices'],report['receipts']),(1,1,1))
        self.assertTrue(Session.objects.filter(pk=current.pk).exists()); self.assertEqual(OperationReceipt.objects.count(),2)
        self.assertTrue(OperationReceipt.objects.filter(pk=fresh.pk).exists());self.assertTrue(OperationReceipt.objects.filter(pk=valid.pk).exists())

    def abandoned(self, name):
        user=User.objects.create_user(name+'@example.test')
        User.objects.filter(pk=user.pk).update(date_joined=self.now-timedelta(days=10))
        user.refresh_from_db(); return user

    def test_abandoned_scaffolding_removed_but_audit_preserved(self):
        user=self.abandoned('abandoned'); action,job=self.action(user=user)
        audit=AuditEvent.objects.create(actor=user,action='account.registered',entity_kind='User',entity_id=str(user.pk))
        result=cleanup_account_retention(dry_run=False)
        self.assertEqual(result['eligible']['abandoned_signups'],1)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())
        audit.refresh_from_db(); self.assertIsNone(audit.actor_id)
        job.refresh_from_db(); self.assertIsNone(job.actor_id);self.assertEqual(job.payload,{'retention_cleaned':True})
        self.assertTrue(User.objects.filter(pk=self.member.pk).exists())

    def test_account_activity_pending_mail_and_holds_preserve_accounts(self):
        activity=self.abandoned('activity')
        Device.objects.create(user=activity,token_binding_sha256='x'*64,expires_at=self.now-timedelta(days=1))
        pending=self.abandoned('pending');self.action(user=pending,status='pending')
        hold=self.abandoned('hold');AuditEvent.objects.create(actor=hold,action='legal.hold',entity_kind='User',entity_id=str(hold.pk))
        edited=self.abandoned('edited');Preferences.objects.create(user=edited,version=2)
        cleanup_account_retention(dry_run=False)
        self.assertTrue(User.objects.filter(pk__in=[activity.pk,pending.pk,hold.pk,edited.pk]).count()==4)

    def test_batch_bound_and_invalid_arguments(self):
        self.action();self.action()
        self.assertEqual(cleanup_account_retention(limit=1,dry_run=False)['eligible']['action_tokens'],1)
        self.assertEqual(EmailActionToken.objects.count(),1)
        for kwargs in [{'limit':0},{'limit':True},{'max_seconds':0},{'dry_run':'yes'}]:
            with self.assertRaises(ValueError):cleanup_account_retention(**kwargs)

    def test_orphan_completed_mail_scrubbed_but_unknown_delivery_retained(self):
        old=self.now-timedelta(days=8)
        def job(status,outcome):
            return OutboxJob.objects.create(kind='email_action',actor=self.member,dedupe_key=uuid.uuid4().hex,payload={'action_id':str(uuid.uuid4()),'email_outcome':outcome},status=status,completed_at=old,not_before=old)
        done=job('done','accepted');unknown=job('done','unknown')
        cleanup_account_retention(dry_run=False)
        done.refresh_from_db();unknown.refresh_from_db()
        self.assertEqual(done.payload,{'retention_cleaned':True});self.assertEqual(unknown.payload['email_outcome'],'unknown')

    def test_checkpoint_advances_past_pending_prefix_and_wraps(self):
        first, first_job = self.action(status='pending')
        second, second_job = self.action()
        # Assign deterministic ordered IDs without modifying the held job state.
        first_id, second_id = uuid.UUID(int=1), uuid.UUID(int=2)
        EmailActionToken.objects.filter(pk=first.pk).update(id=first_id)
        EmailActionToken.objects.filter(pk=second.pk).update(id=second_id)
        first_job.payload['action_id']=str(first_id);first_job.save()
        second_job.payload['action_id']=str(second_id);second_job.save()
        self.assertEqual(cleanup_account_retention(limit=1,dry_run=False)['eligible']['action_tokens'],0)
        checkpoint=OutboxJob.objects.get(dedupe_key='retention:v1')
        self.assertEqual(checkpoint.payload['cursors']['actions'],str(first_id))
        before=dict(checkpoint.payload)
        self.assertEqual(cleanup_account_retention(limit=1)['eligible']['action_tokens'],1)
        checkpoint.refresh_from_db();self.assertEqual(checkpoint.payload,before)
        self.assertEqual(cleanup_account_retention(limit=1,dry_run=False)['eligible']['action_tokens'],1)
        checkpoint.refresh_from_db();self.assertIsNone(checkpoint.payload['cursors']['actions'])
        self.assertTrue(EmailActionToken.objects.filter(pk=first_id).exists())
        self.assertFalse(EmailActionToken.objects.filter(pk=second_id).exists())
        self.assertEqual(cleanup_account_retention(limit=1,dry_run=False)['eligible']['action_tokens'],0)

    def test_checkpoint_advances_past_held_signup(self):
        held=self.abandoned('held-prefix');eligible=self.abandoned('eligible-suffix')
        AuditEvent.objects.create(actor=held,action='legal.hold',entity_kind='User',entity_id=str(held.pk))
        self.assertEqual(cleanup_account_retention(limit=1,dry_run=False)['eligible']['abandoned_signups'],0)
        self.assertEqual(cleanup_account_retention(limit=1,dry_run=False)['eligible']['abandoned_signups'],1)
        self.assertTrue(User.objects.filter(pk=held.pk).exists())
        self.assertFalse(User.objects.filter(pk=eligible.pk).exists())

    def test_checkpoint_advances_past_referenced_device_without_deleting_license(self):
        from billing.models import Entitlement
        from library.models import Work, Edition, Revision, Rights
        from reader.models import DownloadLicense
        import io, tempfile
        from django.core.management import call_command
        from django.test import override_settings
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        config=override_settings(MEDIA_ROOT=directory.name,LOCAL=True,MAISON_LOCAL_FIXTURES=True)
        config.enable();self.addCleanup(config.disable)
        call_command('seed_local_pilot',stdout=io.StringIO())
        edition=Edition.objects.select_related('live_revision').get(slug='river-notebook-en')
        revision=edition.live_revision
        right=revision.rights.get(format='reader',action='download')
        entitlement=Entitlement.objects.create(grant_key='retention-test',user=self.member,source='free',scope='edition',edition=edition,revision=revision,formats=['reader'],valid_from=self.now-timedelta(days=2))
        held=Device.objects.create(id=uuid.UUID(int=1),user=self.member,token_binding_sha256='h'*64,expires_at=self.now-timedelta(hours=1))
        removable=Device.objects.create(id=uuid.UUID(int=2),user=self.member,token_binding_sha256='r'*64,expires_at=self.now-timedelta(days=1))
        license=DownloadLicense.objects.create(user=self.member,device=held,entitlement=entitlement,revision=revision,rights_record=right,format='reader',territory='IN',manifest_sha256='a'*64,private_manifest_key='synthetic-retention-only',unit_ids=[str(revision.units.first().pk)],manifest={'edition_revision_id':str(revision.pk),'content_sha256':revision.content_sha256},issued_at=self.now-timedelta(hours=12),expires_at=self.now-timedelta(hours=1))
        self.assertEqual(cleanup_account_retention(limit=1,dry_run=False)['eligible']['devices'],0)
        self.assertEqual(cleanup_account_retention(limit=1,dry_run=False)['eligible']['devices'],1)
        self.assertTrue(Device.objects.filter(pk=held.pk).exists())
        self.assertFalse(Device.objects.filter(pk=removable.pk).exists())
        license.refresh_from_db();self.assertEqual(license.device_id,held.pk)
        checkpoint=OutboxJob.objects.get(dedupe_key='retention:v1')
        self.assertIsNone(checkpoint.payload['cursors']['devices'])

    def test_recorded_account_hold_preserves_tokens_mail_sessions_devices_receipts(self):
        AuditEvent.objects.create(actor=self.member,action='retention.hold',entity_kind='User',entity_id=str(self.member.pk))
        action,job=self.action()
        orphan=OutboxJob.objects.create(kind='email_action',actor=self.member,dedupe_key=uuid.uuid4().hex,payload={'action_id':str(uuid.uuid4())},status='done',completed_at=self.now-timedelta(days=9),not_before=self.now)
        session=Session.objects.create(session_key='held-session',session_data='private',expire_date=self.now-timedelta(days=1))
        device=Device.objects.create(user=self.member,session=session,token_binding_sha256='h'*64,expires_at=self.now-timedelta(days=1))
        receipt=OperationReceipt.objects.create(actor=self.member,operation_id=uuid.uuid4(),kind='progress.update',request_sha256='h'*64,http_status=200,response={},expires_at=self.now-timedelta(days=1))
        OperationReceipt.objects.filter(pk=receipt.pk).update(created_at=self.now-timedelta(days=36))
        result=cleanup_account_retention(dry_run=False)
        self.assertTrue(all(count==0 for count in result['eligible'].values()))
        self.assertTrue(EmailActionToken.objects.filter(pk=action.pk).exists())
        self.assertTrue(Session.objects.filter(pk=session.pk).exists());self.assertTrue(Device.objects.filter(pk=device.pk).exists())
        self.assertTrue(OperationReceipt.objects.filter(pk=receipt.pk).exists())
        job.refresh_from_db();orphan.refresh_from_db()
        self.assertIn('action_id',job.payload);self.assertIn('action_id',orphan.payload)


from threading import Event, Thread
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase
from unittest import skipUnless


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL row locking required')
class RetentionConcurrencyTests(TransactionTestCase):
    def test_claimed_job_lock_prevents_cleanup_of_its_action(self):
        now=timezone.now();user=User.objects.create_user('locking@example.test',is_verified=True)
        action=EmailActionToken.objects.create(user=user,email_normalized=user.email,purpose='verify_email',token_sha256=uuid.uuid4().hex,expires_at=now-timedelta(days=9))
        job=OutboxJob.objects.create(kind='email_action',actor=user,dedupe_key=uuid.uuid4().hex,payload={'action_id':str(action.pk)},status='done',not_before=now)
        locked=Event();release=Event();errors=[]
        def hold():
            close_old_connections()
            try:
                with transaction.atomic():
                    OutboxJob.objects.select_for_update().get(pk=job.pk)
                    locked.set();release.wait(timeout=10)
            except Exception as error:errors.append(error);locked.set()
            finally:connections.close_all()
        worker=Thread(target=hold);worker.start()
        try:
            self.assertTrue(locked.wait(timeout=5));self.assertEqual(errors,[])
            report=cleanup_account_retention(dry_run=False)
            self.assertEqual(report['eligible']['action_tokens'],0)
            self.assertTrue(EmailActionToken.objects.filter(pk=action.pk).exists())
        finally:release.set();worker.join(timeout=10)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['action_tokens'],1)


    def test_concurrent_apply_checkpoint_is_busy_then_resumes(self):
        now=timezone.now();user=User.objects.create_user('busy@example.test',is_verified=True)
        checkpoint=OutboxJob.objects.create(kind='retention_checkpoint',dedupe_key='retention:v1',status='done',not_before=now,payload={'cursors':{}})
        action=EmailActionToken.objects.create(user=user,email_normalized=user.email,purpose='verify_email',token_sha256=uuid.uuid4().hex,expires_at=now-timedelta(days=9))
        locked=Event();release=Event();errors=[]
        def hold():
            close_old_connections()
            try:
                with transaction.atomic():
                    OutboxJob.objects.select_for_update().get(pk=checkpoint.pk)
                    locked.set();release.wait(timeout=10)
            except Exception as error:errors.append(error);locked.set()
            finally:connections.close_all()
        worker=Thread(target=hold);worker.start()
        try:
            self.assertTrue(locked.wait(timeout=5));self.assertEqual(errors,[])
            report=cleanup_account_retention(dry_run=False)
            self.assertTrue(report['busy']);self.assertEqual(report['eligible'],{})
            self.assertTrue(EmailActionToken.objects.filter(pk=action.pk).exists())
            checkpoint.refresh_from_db();self.assertEqual(checkpoint.payload,{'cursors':{}})
        finally:release.set();worker.join(timeout=10)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['action_tokens'],1)
        self.assertFalse(EmailActionToken.objects.filter(pk=action.pk).exists())
