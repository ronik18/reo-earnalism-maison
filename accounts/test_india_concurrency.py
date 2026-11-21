"""Real PostgreSQL ordering of renewal and same-account independence."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
from unittest.mock import patch
from django.db import connections,connection
from django.test import TransactionTestCase,Client,override_settings
from . import guardian,enrollment,test_india_enrollment as fixtures
from .models import GuardianAuthorization


@override_settings(LOCAL=True,INDIA_FIRST_LAUNCH_ENABLED=True,GUARDIAN_AUTHORIZATION_ENABLED=True,GUARDIAN_AUTHORIZATION_POLICIES=fixtures.POLICIES)
class IndiaAuthorityConcurrencyTests(TransactionTestCase):
    setUp=fixtures.IndiaEnrollmentTests.setUp
    client_for=fixtures.IndiaEnrollmentTests.client_for
    post=fixtures.IndiaEnrollmentTests.post
    request_permission=fixtures.IndiaEnrollmentTests.request_permission
    child=fixtures.IndiaEnrollmentTests.child

    def independent(self,child):
        try:
            response=Client().post('/api/v1/auth/account-capacity',{'email':child.email,'password':fixtures.PASS,**fixtures.PASSWORD,**fixtures.ADULT},content_type='application/json')
            return response.status_code
        finally:connections.close_all()

    def renew(self,source,cookies):
        try:
            parent=Client()
            for name,value in cookies.items():parent.cookies[name]=value
            response=self.post('/me/guardian/authorizations',{
                'jurisdiction':'IN','purpose':'account_processing','notice_version':'india-parent-v1','method':'india-parent-electronic-v1',**fixtures.PARENT,'source_authorization_id':source},client=parent)
            return response.status_code
        finally:connections.close_all()

    def test_independence_commits_before_waiting_renewal_then_renewal_is_denied(self):
        source,child,_,_=self.child();child.is_verified=True;child.save(update_fields=['is_verified'])
        cookies={key:value.value for key,value in self.parent.cookies.items()}
        child_held=Event();parent_attempt=Event();release=Event();backend={}
        original_record=enrollment.record_adult;original_locks=guardian._locks
        def pause_record(user,declaration,purpose):
            if purpose=='independent_capacity':
                child_held.set();self.assertTrue(release.wait(5),'Independence was not released')
            return original_record(user,declaration,purpose)
        def observe_parent(request,child_id,guardian_id,review=False):
            if child_id is None:
                backend['renewal']=connection.connection.info.backend_pid;parent_attempt.set()
            return original_locks(request,child_id,guardian_id,review)
        with patch('accounts.enrollment.record_adult',side_effect=pause_record),patch('accounts.guardian._locks',side_effect=observe_parent),ThreadPoolExecutor(max_workers=2) as pool:
            adult=pool.submit(self.independent,child)
            try:
                self.assertTrue(child_held.wait(5),'Independence did not acquire child')
                renewed=pool.submit(self.renew,source,cookies)
                self.assertTrue(parent_attempt.wait(5),'Renewal did not attempt its household lock')
                deadline=time.monotonic()+5;waiting=False
                while time.monotonic()<deadline:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT wait_event_type='Lock' FROM pg_stat_activity WHERE pid=%s",[backend['renewal']]);row=cursor.fetchone()
                    if row and row[0]:waiting=True;break
                    time.sleep(.01)
                self.assertTrue(waiting,'Renewal did not overlap the held independence transaction')
            finally:release.set()
            self.assertEqual(adult.result(timeout=8),202);self.assertEqual(renewed.result(timeout=8),403)
        child.refresh_from_db();self.assertFalse(child.guardian_managed)
        self.assertFalse(GuardianAuthorization.objects.filter(child=child,status='authorized').exists())
        self.assertTrue(self.client_for(child).get('/api/v1/session').json()['authenticated'])

    def test_renewal_commits_first_then_independence_withdraws_the_new_grant_too(self):
        from django.contrib.auth import authenticate
        source,child,_,_=self.child();child.is_verified=True;child.save(update_fields=['is_verified'])
        cookies={key:value.value for key,value in self.parent.cookies.items()}
        grant_held=Event();identity_checked=Event();release=Event();original_audit=guardian.audit
        def pause_grant(actor,action,entity,detail=None):
            if action=='guardian.electronic_permission':
                grant_held.set();self.assertTrue(release.wait(5),'Renewal was not released')
            return original_audit(actor,action,entity,detail)
        def observe_identity(*args,**kwargs):
            user=authenticate(*args,**kwargs);identity_checked.set();return user
        with patch('accounts.guardian.audit',side_effect=pause_grant),patch('django.contrib.auth.authenticate',side_effect=observe_identity),ThreadPoolExecutor(max_workers=2) as pool:
            renewed=pool.submit(self.renew,source,cookies)
            try:
                self.assertTrue(grant_held.wait(5),'Renewal did not hold family rows')
                adult=pool.submit(self.independent,child)
                self.assertTrue(identity_checked.wait(5),'Independence did not authenticate before waiting')
            finally:release.set()
            self.assertEqual(renewed.result(timeout=8),201);self.assertEqual(adult.result(timeout=8),202)
        child.refresh_from_db();self.assertFalse(child.guardian_managed)
        self.assertEqual(GuardianAuthorization.objects.filter(child=child).count(),2)
        self.assertFalse(GuardianAuthorization.objects.filter(child=child,status='authorized').exists())
        self.assertTrue(self.client_for(child).get('/api/v1/session').json()['authenticated'])
