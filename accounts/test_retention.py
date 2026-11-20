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


class SecurityAndSupportRetentionTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.user = User.objects.create_user('security-retention@example.test', is_verified=True)
        self.operator = User.objects.create_user('operator-retention@example.test', is_staff=True, is_verified=True)

    def audit(self, action='account.password_reset', days=181, actor=True, detail=None, kind='User'):
        target = str(self.user.pk)
        if kind == 'Device':
            target = str(Device.objects.create(user=self.user, token_binding_sha256=uuid.uuid4().hex,
                                               expires_at=self.now+timedelta(days=1)).pk)
        row = AuditEvent.objects.create(actor=self.user if actor else None, action=action,
                                       entity_kind=kind, entity_id=target, detail=detail or {})
        AuditEvent.objects.filter(pk=row.pk).update(created_at=self.now-timedelta(days=days))
        return row

    def support(self, days=91, resolved=True, status='done', outcome='submitting', **changes):
        case = {'schema_version':1, 'resolved_at':(self.now-timedelta(days=days)).isoformat(),
                'resolved_by':str(self.operator.public_id), 'resolution_ref':'CASE-123', 'obligations_reviewed':True}
        result = {'status':'submitted', 'smtp_submission_accepted':True, 'delivery_confirmed':False,
                  'message_id':'private-message-id'}
        if resolved: result['retention_case'] = case
        row = OutboxJob.objects.create(kind='contact_support', actor=self.user, dedupe_key=uuid.uuid4().hex,
                                       status=status, not_before=self.now, completed_at=self.now-timedelta(days=120),
                                       payload={'email':'private@example.test', 'message':'private message',
                                                'category':'account', 'email_outcome':outcome}, result=result)
        for field, value in changes.items(): setattr(row, field, value)
        if changes: row.save()
        return row

    def test_exact_allowlist_cutoff_preview_and_other_evidence_preserved(self):
        from .retention import ROUTINE_SECURITY_ACTIONS
        eligible = [self.audit(action=action, kind='Device' if action=='device.revoked' else 'User') for action in ROUTINE_SECURITY_ACTIONS]
        preserve = [self.audit(action=action) for action in [
            'content.publish', 'book.draft_import', 'asset.complete', 'payment.capture_applied',
            'consent.changed', 'privacy.account_anonymised', 'unknown.future_security_action']]
        preserve += [self.audit(days=179), self.audit(actor=False), self.audit(detail={'incident':'open'}), self.audit(kind='Unexpected')]
        before = AuditEvent.objects.count()
        preview = cleanup_account_retention()
        self.assertEqual(preview['eligible']['audit_outcomes'], len(eligible))
        self.assertEqual(AuditEvent.objects.count(), before)
        result = cleanup_account_retention(dry_run=False)
        self.assertEqual(result['eligible']['audit_outcomes'], len(eligible))
        self.assertFalse(AuditEvent.objects.filter(pk__in=[row.pk for row in eligible]).exists())
        self.assertEqual(AuditEvent.objects.filter(pk__in=[row.pk for row in preserve]).count(), len(preserve))

    def test_user_subject_mismatch_and_missing_mismatched_or_held_device_preserved(self):
        subject=User.objects.create_user('held-subject@example.test',is_verified=True)
        AuditEvent.objects.create(action='legal.hold',entity_kind='User',entity_id=str(subject.pk))
        mismatch=self.audit();mismatch.entity_id=str(subject.pk);mismatch.save()
        wrong_device=self.audit(action='device.revoked',kind='Device')
        Device.objects.filter(pk=wrong_device.entity_id).update(user=subject)
        missing=self.audit(action='device.revoked',kind='Device')
        Device.objects.filter(pk=missing.entity_id).delete()
        malformed=self.audit(action='device.revoked',kind='Device');malformed.entity_id='not-a-device';malformed.save()
        held=self.audit(action='device.revoked',kind='Device')
        AuditEvent.objects.create(action='retention.hold',entity_kind='Device',entity_id=held.entity_id)
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['audit_outcomes'],0)
        for row in [mismatch,wrong_device,missing,malformed,held]:
            self.assertTrue(AuditEvent.objects.filter(pk=row.pk).exists())

    def test_actor_row_and_exact_entity_holds_are_never_expired(self):
        row = self.audit(detail={'retention_hold':True, 'review_at':'2000-01-01T00:00:00Z'})
        targeted = self.audit()
        marker = AuditEvent.objects.create(action='legal.hold', entity_kind='AuditEvent', entity_id=str(targeted.pk),
                                          detail={'review_at':'2000-01-01T00:00:00Z'})
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['audit_outcomes'], 0)
        row.detail = {}; row.save()
        AuditEvent.objects.create(action='retention.hold', entity_kind='User', entity_id=str(self.user.pk))
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['audit_outcomes'], 0)
        self.assertTrue(AuditEvent.objects.filter(pk=marker.pk).exists())

    def test_support_requires_actual_resolution_and_90days_then_scrubs_only_content(self):
        old = self.support(); recent = self.support(days=89); unresolved = self.support(resolved=False)
        preview = cleanup_account_retention()
        self.assertEqual(preview['eligible']['support_payloads'], 1)
        old.refresh_from_db(); self.assertIn('message',old.payload)
        result = cleanup_account_retention(dry_run=False)
        self.assertEqual(result['eligible']['support_payloads'], 1)
        old.refresh_from_db(); recent.refresh_from_db(); unresolved.refresh_from_db()
        self.assertEqual(old.payload, {'retention_cleaned':True})
        self.assertEqual(set(old.result), {'status','retention_case'})
        self.assertEqual(old.result['retention_case']['resolution_ref'], 'CASE-123')
        self.assertIn('message',recent.payload); self.assertIn('message',unresolved.payload)
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['support_payloads'], 0)

    def test_support_preserves_unknown_malformed_unreviewed_and_held_cases(self):
        rows = [self.support(status='pending'), self.support(outcome='unknown'), self.support(days=-1)]
        unreviewed = self.support(); unreviewed.result['retention_case']['obligations_reviewed']=False; unreviewed.save(); rows.append(unreviewed)
        malformed = self.support(); malformed.result['retention_case']['resolved_at']='bad'; malformed.save(); rows.append(malformed)
        naive = self.support(); naive.result['retention_case']['resolved_at']='2020-01-01T00:00:00'; naive.save(); rows.append(naive)
        held = self.support(); held.payload['legal_hold']=True; held.save(); rows.append(held)
        exact = self.support(); AuditEvent.objects.create(action='retention.hold',entity_kind='OutboxJob',entity_id=str(exact.pk)); rows.append(exact)
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['support_payloads'], 0)
        for row in rows:
            row.refresh_from_db(); self.assertIn('message',row.payload)

    def test_actor_hold_and_result_hold_preserve_support_until_explicit_review(self):
        actor_held=self.support()
        AuditEvent.objects.create(actor=self.user,action='legal.hold',entity_kind='User',entity_id=str(self.user.pk),
                                  detail={'review_at':'2000-01-01T00:00:00Z'})
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['support_payloads'],0)
        actor_held.refresh_from_db();self.assertIn('message',actor_held.payload)
        other=User.objects.create_user('other-held@example.test',is_verified=True)
        result_held=self.support(actor=other)
        result_held.result['retention_hold']=True;result_held.save()
        extra=self.support(actor=other)
        extra.result['retention_case']['unexpected_private_detail']='preserve unknown resolution metadata';extra.save()
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['support_payloads'],0)
        for row in [result_held,extra]:
            row.refresh_from_db();self.assertIn('message',row.payload)

    def test_held_prefix_does_not_starve_eligible_audit_or_support(self):
        held_audit=self.audit(); eligible_audit=self.audit()
        AuditEvent.objects.filter(pk=held_audit.pk).update(id=uuid.UUID(int=100))
        AuditEvent.objects.filter(pk=eligible_audit.pk).update(id=uuid.UUID(int=101))
        AuditEvent.objects.create(action='retention.hold',entity_kind='AuditEvent',entity_id=str(uuid.UUID(int=100)))
        held_support=self.support(); eligible_support=self.support()
        OutboxJob.objects.filter(pk=held_support.pk).update(id=uuid.UUID(int=200))
        OutboxJob.objects.filter(pk=eligible_support.pk).update(id=uuid.UUID(int=201))
        AuditEvent.objects.create(action='retention.hold',entity_kind='OutboxJob',entity_id=str(uuid.UUID(int=200)))
        first=cleanup_account_retention(limit=1,dry_run=False)['eligible']
        second=cleanup_account_retention(limit=1,dry_run=False)['eligible']
        self.assertEqual((first['audit_outcomes'],first['support_payloads']),(0,0))
        self.assertEqual((second['audit_outcomes'],second['support_payloads']),(1,1))

    def test_exact_90day_support_boundary_keeps_security_records(self):
        from unittest.mock import patch
        audit=self.audit(days=90); support=self.support(days=90)
        with patch('accounts.retention.timezone.now',return_value=self.now):
            report=cleanup_account_retention(dry_run=False)['eligible']
        self.assertEqual((report['audit_outcomes'],report['support_payloads']),(0,1))

    def test_security_minimum_180day_predicate_preserves_90_179_and_just_under_boundary(self):
        from unittest.mock import patch
        keep=[self.audit(days=90),self.audit(days=179),self.audit(days=180)]
        AuditEvent.objects.filter(pk=keep[-1].pk).update(created_at=self.now-timedelta(days=180)+timedelta(microseconds=1))
        exact=self.audit(days=180);older=self.audit(days=181)
        support=self.support(days=90)
        before=AuditEvent.objects.count()
        with patch('accounts.retention.timezone.now',return_value=self.now):
            preview=cleanup_account_retention()
            self.assertEqual(preview['eligible']['audit_outcomes'],2)
            self.assertEqual(preview['eligible']['support_payloads'],1)
            self.assertEqual(AuditEvent.objects.count(),before)
            actual=cleanup_account_retention(dry_run=False)['eligible']
        self.assertEqual((actual['audit_outcomes'],actual['support_payloads']),(2,1))
        self.assertEqual(AuditEvent.objects.filter(pk__in=[row.pk for row in keep]).count(),3)
        self.assertFalse(AuditEvent.objects.filter(pk__in=[exact.pk,older.pk]).exists())
        support.refresh_from_db();self.assertEqual(support.payload,{'retention_cleaned':True})


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL row locking required')
class SupportRetentionConcurrencyTests(TransactionTestCase):
    def test_support_cleanup_skips_operator_locked_case_then_resumes(self):
        now=timezone.now();user=User.objects.create_user('support-locking@example.test',is_verified=True)
        case={'schema_version':1,'resolved_at':(now-timedelta(days=91)).isoformat(),
              'resolved_by':str(user.public_id),'resolution_ref':'CASE-LOCK','obligations_reviewed':True}
        job=OutboxJob.objects.create(kind='contact_support',actor=user,dedupe_key=uuid.uuid4().hex,status='done',
            not_before=now,payload={'message':'private','email_outcome':'submitting'},
            result={'status':'submitted','smtp_submission_accepted':True,'retention_case':case})
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
            self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['support_payloads'],0)
            job.refresh_from_db();self.assertIn('message',job.payload)
        finally:release.set();worker.join(timeout=10)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['support_payloads'],1)

    def test_allauth_verified_or_secondary_address_prevents_abandoned_cleanup(self):
        from allauth.account.models import EmailAddress
        user=User.objects.create_user('secondary-address@example.test')
        User.objects.filter(pk=user.pk).update(date_joined=timezone.now()-timedelta(days=10))
        EmailAddress.objects.create(user=user,email='secondary@example.test',verified=False,primary=False)
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['abandoned_signups'],0)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
