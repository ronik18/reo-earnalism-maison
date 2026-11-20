"""Post-lock request authority checks using actual PostgreSQL lock contention."""
import queue
import threading
import time
import uuid
from datetime import timedelta
from django.db import connection, connections, transaction
from django.test import TransactionTestCase, Client, override_settings
from django.utils import timezone
from accounts.models import User, Device
from core.api import DomainError
from core.models import OperationReceipt
from core.services import apply_operation


@override_settings(LOCAL=True)
class OperationAuthorityTests(TransactionTestCase):
    def setUp(self):
        self.user=User.objects.create_user('authority@example.test','Original-Authority-Fixture-47',is_verified=True)
        self.client=Client()
        result=self.client.post('/api/v1/auth/login',{'email':self.user.email,'password':'Original-Authority-Fixture-47',
            'password_purpose_consent':True,'password_purpose_version':'password-account-v1'},content_type='application/json')
        self.assertEqual(result.status_code,200,result.content)
        self.device=Device.objects.get(pk=result.json()['device_id'])
        self.actor=self.client.get('/api/v1/session').wsgi_request.user
        self.assertEqual(self.actor._maison_operation_authority,
            (self.user.session_epoch,self.device.pk,self.device.session_id,self.device.token_binding_sha256))

    def test_active_authority_mutates_and_replays_without_second_callback(self):
        calls=[];key=uuid.uuid4()
        def callback():calls.append(True);return 200,{'ok':True},1
        self.assertFalse(apply_operation(self.actor,key,'original.test',{},callback).replayed)
        self.assertTrue(apply_operation(self.actor,key,'original.test',{},callback).replayed)
        self.assertEqual(calls,[True]);self.assertEqual(OperationReceipt.objects.count(),1)

    def test_internal_active_service_call_without_request_snapshot_is_supported(self):
        result=apply_operation(self.user,uuid.uuid4(),'original.internal',{},lambda:(200,{'ok':True},1))
        self.assertEqual(result[0],200)

    def queued(self,change):
        result=queue.Queue();started=queue.Queue();calls=[];key=uuid.uuid4()
        def mutate():calls.append(True);return 200,{'ok':True},1
        def worker():
            try:
                connections.close_all()
                with connection.cursor() as cursor:cursor.execute('SELECT pg_backend_pid()');started.put(cursor.fetchone()[0])
                try:apply_operation(self.actor,key,'original.queued',{},mutate)
                except DomainError as error:result.put(error.code)
                else:result.put('unexpected_success')
            except BaseException as error:result.put(error)
            finally:connections.close_all()
        with transaction.atomic():
            current=User.objects.select_for_update().get(pk=self.user.pk)
            thread=threading.Thread(target=worker);thread.start();pid=started.get(timeout=5)
            deadline=time.monotonic()+5;blocked=False
            while time.monotonic()<deadline:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s',[pid]);row=cursor.fetchone()
                if row and row[0]=='Lock':blocked=True;break
                time.sleep(.01)
            self.assertTrue(blocked,'Mutation must really be queued on the User lock')
            change(current)
        thread.join(timeout=5);self.assertFalse(thread.is_alive())
        self.assertEqual(result.get(timeout=1),'authentication_required')
        self.assertEqual(calls,[]);self.assertFalse(OperationReceipt.objects.filter(operation_id=key).exists())

    def test_queued_mutation_after_privacy_deactivation_never_calls_callback_or_creates_receipt(self):
        def deletion(user):
            user.is_active=False;user.is_verified=False;user.session_epoch+=1
            user.save(update_fields=['is_active','is_verified','session_epoch'])
        self.queued(deletion)

    def test_queued_mutation_after_password_epoch_reset_never_calls_callback_or_creates_receipt(self):
        def reset(user):user.session_epoch+=1;user.save(update_fields=['session_epoch'])
        self.queued(reset)

    def test_queued_mutation_after_device_revocation_never_calls_callback_or_creates_receipt(self):
        self.queued(lambda user:Device.objects.filter(pk=self.device.pk).update(revoked_at=timezone.now()))

    def test_replay_is_rejected_after_authority_revocation(self):
        key=uuid.uuid4();callback=lambda:(200,{'private':'receipt'},1)
        apply_operation(self.actor,key,'original.test',{},callback)
        Device.objects.filter(pk=self.device.pk).update(revoked_at=timezone.now())
        with self.assertRaises(DomainError):apply_operation(self.actor,key,'original.test',{},callback)

    def test_stale_account_endpoints_and_get_defaults_do_not_recreate_erased_rows(self):
        from django.test import RequestFactory
        from accounts import views,services
        from accounts.models import Preferences,Consent
        User.objects.filter(pk=self.user.pk).update(is_active=False,session_epoch=2)
        Preferences.objects.filter(user=self.user).delete();Consent.objects.filter(user=self.user).delete()
        factory=RequestFactory()
        for endpoint,method,body in [(views.profile,'patch',{'display_name':'Must not write'}),
            (views.preferences,'patch',{'theme':'dark'}),(views.consents,'put',{'necessary_notice_version':'v1','analytics_opt_in':False,'marketing_email_opt_in':False}),
            (views.profile,'get',None),(views.preferences,'get',None),(views.consents,'get',None),
            (views.reauthenticate,'post',{'password':'Original-Authority-Fixture-47','password_purpose_consent':True,'password_purpose_version':'password-account-v1'}),
            (views.change_password,'post',{'current_password':'Original-Authority-Fixture-47','new_password':'New-Authority-Fixture-49','password_purpose_consent':True,'password_purpose_version':'password-account-v1'})]:
            with self.subTest(endpoint=endpoint.__name__,method=method):
                request=getattr(factory,method)('/original-fixture',data=body or {},content_type='application/json',HTTP_IF_MATCH='"v1"')
                request.user=self.actor;request.session=self.client.session
                self.assertEqual(endpoint(request).status_code,401)
        request=factory.get('/api/v1/session');request.user=self.actor;request.session=self.client.session
        with self.assertRaises(DomainError):services.session_data(request)
        self.assertFalse(Preferences.objects.filter(user=self.user).exists());self.assertFalse(Consent.objects.filter(user=self.user).exists())
        self.user.refresh_from_db();self.assertEqual(self.user.display_name,'');self.assertTrue(self.user.check_password('Original-Authority-Fixture-47'))

    @override_settings(STAFF_MFA_REQUIRED=False)
    def test_admin_password_rotation_preserves_current_device_and_account_mutations(self):
        staff=User.objects.create_superuser('authority-staff@example.test','Original-Authority-Fixture-47')
        client=Client();choice={'password_purpose_consent':True,'password_purpose_version':'password-account-v1'}
        response=client.post('/admin/login/',{'username':staff.email,'password':'Original-Authority-Fixture-47','next':'/admin/',**choice})
        self.assertEqual(response.status_code,302)
        old_actor=client.get('/api/v1/session').wsgi_request.user
        other=Client();self.assertEqual(other.post('/api/v1/auth/login',{'email':staff.email,'password':'Original-Authority-Fixture-47',**choice},content_type='application/json').status_code,200)
        other_device=Device.objects.get(pk=other.session['device_id'])
        response=client.post('/admin/password_change/',{'old_password':'Original-Authority-Fixture-47','new_password1':'Changed-Authority-Password-53','new_password2':'Changed-Authority-Password-53',**choice})
        self.assertEqual(response.status_code,302,response.content)
        other_device.refresh_from_db();self.assertIsNotNone(other_device.revoked_at)
        self.assertFalse(other.get('/api/v1/session').json()['authenticated'])
        session=client.get('/api/v1/session');self.assertEqual(session.status_code,200,session.content);self.assertTrue(session.json()['authenticated'])
        prefs=client.get('/api/v1/me/preferences');self.assertEqual(prefs.status_code,200,prefs.content)
        response=client.patch('/api/v1/me/preferences',{'theme':'dark'},content_type='application/json',HTTP_IF_MATCH=prefs['ETag'])
        self.assertEqual(response.status_code,200,response.content)
        with self.assertRaises(DomainError):apply_operation(old_actor,uuid.uuid4(),'original.old-admin',{},lambda:(200,{},1))
