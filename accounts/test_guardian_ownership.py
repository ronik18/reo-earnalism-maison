"""Household privacy and reviewer eligibility, using synthetic local policies."""
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.db import connection,transaction
from django.test import TestCase,override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from core.api import DomainError
from core.models import AuditEvent,OperationReceipt
from . import guardian
from . import test_guardian_journey as fixtures
from .models import GuardianAuthorization,User


@override_settings(LOCAL=True,GUARDIAN_AUTHORIZATION_ENABLED=True,GUARDIAN_AUTHORIZATION_POLICIES=fixtures.POLICIES,STAFF_MFA_REQUIRED=True)
class GuardianOwnershipTests(TestCase):
    setUp=fixtures.GuardianJourneyTests.setUp
    client_for=fixtures.GuardianJourneyTests.client_for
    post=fixtures.GuardianJourneyTests.post
    request=fixtures.GuardianJourneyTests.request

    def foreign_household(self):
        parent=User.objects.create_user('foreign-original-parent@example.test',fixtures.PASS,is_verified=True)
        child=User.objects.create_user('foreign-original-child@example.test',fixtures.PASS,is_verified=True)
        _,digest=guardian._policy('IN','account_processing','notice-v1','synthetic-manual-v1')
        row=GuardianAuthorization.objects.create(guardian=parent,child=child,reviewer=self.reviewer,jurisdiction='IN',purpose='account_processing',notice_version='notice-v1',method='synthetic-manual-v1',policy_sha256=digest,status='authorized',evidence_sha256='a'*64,reviewed_at=timezone.now(),expires_at=timezone.now()+timedelta(hours=1))
        return parent,child,row

    def test_known_foreign_active_inactive_withdrawn_and_unknown_are_identically_not_found(self):
        parent,child,row=self.foreign_household();unknown=uuid.uuid4();job=uuid.uuid4()
        def responses(aid):
            prefix=f'/me/guardian/authorizations/{aid}'
            rows=[]
            with patch.object(guardian,'_locks',side_effect=AssertionError('Foreign household must not be locked')):
                for method,path,data in [
                    ('GET',prefix,None),('POST',prefix+'/withdraw',{'expected_version':1}),
                    ('POST',prefix+'/claim-capability',{}),('POST',prefix+'/claim',{}),
                    ('POST',prefix+'/privacy-requests',{'kind':'export','confirm':True}),
                    ('GET',prefix+f'/privacy-requests/{job}',None),
                    ('POST',prefix+f'/privacy-requests/{job}/download',{}),
                    ('GET',prefix+f'/privacy-requests/{job}/file',None),
                ]:
                    r=self.parent.get('/api/v1'+path) if method=='GET' else self.post(path,data)
                    self.assertEqual(r.status_code,404,(path,r.content))
                    body=r.json();rows.append((body['status'],body['code'],body['detail']))
            return rows
        before=(OperationReceipt.objects.count(),AuditEvent.objects.count())
        expected=responses(unknown)
        for state in ('active','inactive_child','inactive_guardian','withdrawn','expired'):
            User.objects.filter(pk=parent.pk).update(is_active=state!='inactive_guardian')
            User.objects.filter(pk=child.pk).update(is_active=state!='inactive_child')
            GuardianAuthorization.objects.filter(pk=row.pk).update(status='withdrawn' if state=='withdrawn' else 'authorized',expires_at=timezone.now()+timedelta(hours=-1 if state=='expired' else 1))
            with self.subTest(state=state):self.assertEqual(responses(row.pk),expected)
        self.assertEqual((OperationReceipt.objects.count(),AuditEvent.objects.count()),before)
        row.refresh_from_db();self.assertEqual(row.version,1);self.assertEqual(row.evidence_sha256,'a'*64)

    def test_foreign_source_request_does_not_lock_foreign_household(self):
        parent,child,row=self.foreign_household()
        with patch.object(guardian,'_locks',wraps=guardian._locks) as locks:
            r=self.post('/me/guardian/authorizations',{'jurisdiction':'IN','purpose':'privacy_access','notice_version':'notice-v1','method':'synthetic-manual-v1','source_authorization_id':str(row.pk)})
            self.assertEqual(r.status_code,404,r.content)
        for call in locks.call_args_list:
            self.assertNotIn(parent.pk,call.args[1:]);self.assertNotIn(child.pk,call.args[1:])
        self.assertFalse(OperationReceipt.objects.exists())

    def test_unprivileged_review_rejects_before_any_target_lookup(self):
        aid=self.request();unknown=uuid.uuid4()
        no_permission=User.objects.create_user('original-review-without-permission@example.test',fixtures.PASS,is_verified=True,is_staff=True)
        clients=[self.parent,self.client_for(no_permission,True),self.client_for(self.reviewer,False)]
        before=(OperationReceipt.objects.count(),AuditEvent.objects.count())
        with override_settings(STAFF_MFA_REQUIRED=False),patch.object(guardian,'_row',side_effect=AssertionError('Target must not be inspected')):
            for client in clients:
                outcomes=[]
                for target in (aid,unknown):
                    r=self.post(f'/staff/guardian/authorizations/{target}/review',{'approve':True,'evidence_sha256':'a'*64,'expected_version':1},client)
                    self.assertEqual(r.status_code,403,r.content);body=r.json();outcomes.append((body['status'],body['code'],body['detail']))
                self.assertEqual(outcomes[0],outcomes[1])
        self.assertEqual((OperationReceipt.objects.count(),AuditEvent.objects.count()),before)
        self.assertEqual(GuardianAuthorization.objects.get(pk=aid).status,'pending')

    def test_reviewer_precheck_is_current_and_takes_no_row_lock(self):
        request=self.staff.get('/api/v1/session').wsgi_request
        with transaction.atomic(),CaptureQueriesContext(connection) as queries:guardian._review_eligible(request)
        self.assertFalse(any('FOR UPDATE' in row['sql'].upper() for row in queries.captured_queries))
        User.objects.filter(pk=self.reviewer.pk).update(is_staff=False)
        with patch.object(guardian,'_row',side_effect=AssertionError('Revoked reviewer must not inspect target')):
            for aid in (uuid.uuid4(),self.request()):
                with self.assertRaises(DomainError) as denied:guardian.review(request,aid,evidence_sha256='a'*64,approve=True,expected_version=1,operation_id=uuid.uuid4())
                self.assertEqual(denied.exception.code,'permission_denied')

    def test_locked_review_rechecks_permission_after_precheck(self):
        aid=self.request();before=OperationReceipt.objects.count();original=guardian._review_eligible
        def revoke(request):
            original(request);User.objects.filter(pk=self.reviewer.pk).update(is_staff=False)
        with patch.object(guardian,'_review_eligible',side_effect=revoke):
            r=self.post(f'/staff/guardian/authorizations/{aid}/review',{'approve':True,'evidence_sha256':'a'*64,'expected_version':1},self.staff)
        self.assertEqual(r.status_code,403,r.content)
        row=GuardianAuthorization.objects.get(pk=aid);self.assertEqual(row.status,'pending');self.assertEqual(row.evidence_sha256,'');self.assertEqual(row.version,1)
        self.assertEqual(OperationReceipt.objects.count(),before)
