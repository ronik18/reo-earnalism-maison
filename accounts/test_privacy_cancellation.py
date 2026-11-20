"""Queued/held privacy requests can be withdrawn without erasing holds or history."""
import json,tempfile,uuid,hashlib
from datetime import timedelta
from django.test import TestCase,Client,override_settings
from django.utils import timezone
from core.models import OutboxJob,AuditEvent
from core.jobs import run_due_jobs
from reader.models import PersonalList
from library import storage
from .models import User
from .privacy import cleanup_expired_exports

PASS='Original-Privacy-Cancellation-47'
@override_settings(LOCAL=True,MEDIA_STORAGE_BACKEND='local')
class PrivacyCancellationTests(TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.o=override_settings(MEDIA_ROOT=self.tmp.name);self.o.enable();self.addCleanup(self.o.disable)
  self.user=User.objects.create_user('original-cancel-owner@example.test',PASS,is_verified=True)
  self.other=User.objects.create_user('original-cancel-other@example.test',PASS,is_verified=True)
  self.personal=PersonalList.objects.create(user=self.user,name='Keep original private list')
  self.client=Client();self.assertEqual(self.client.post('/api/v1/auth/login',{'email':self.user.email,'password':PASS,'password_purpose_consent':True,'password_purpose_version':'password-account-v1'},content_type='application/json').status_code,200)
 def deletion(self):
  r=self.client.post('/api/v1/me/privacy/requests',{'kind':'delete','confirm':True},content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()));self.assertEqual(r.status_code,202,r.content)
  return OutboxJob.objects.get(pk=r.json()['privacy_request_id'])
 def cancel(self,job,key=None,client=None):
  return (client or self.client).post(f'/api/v1/me/privacy/requests/{job.id}/cancel',{},content_type='application/json',HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()))
 def test_worker_held_deletion_can_be_cancelled_idempotently_without_releasing_hold(self):
  job=self.deletion();marker=AuditEvent.objects.create(actor=self.user,action='legal.hold',entity_kind='User',entity_id=str(self.user.pk))
  self.assertEqual(run_due_jobs(),{'processed':1});job.refresh_from_db();self.assertEqual(job.status,'blocked');self.assertEqual(job.error_code,'privacy_hold')
  self.assertTrue(self.client.get(f'/api/v1/me/privacy/requests/{job.id}').json()['can_cancel'])
  payload=dict(job.payload);result=dict(job.result);key=str(uuid.uuid4())
  first=self.cancel(job,key);self.assertEqual(first.status_code,200,first.content);self.assertEqual(first.json()['status'],'cancelled');self.assertFalse(first.json()['can_cancel']);self.assertIn('no-store',first['Cache-Control'])
  self.assertEqual(self.cancel(job,key).json(),first.json());self.assertEqual(self.cancel(job).json()['status'],'cancelled')
  job.refresh_from_db();self.assertEqual(job.payload,payload);self.assertEqual(job.result,result);self.assertEqual(job.error_code,'privacy_hold')
  self.assertTrue(AuditEvent.objects.filter(pk=marker.pk).exists());self.assertEqual(AuditEvent.objects.filter(actor=self.user,action='privacy.cancelled').count(),1)
  self.assertEqual(run_due_jobs(),{'processed':0});self.user.refresh_from_db();self.assertTrue(self.user.is_active);self.assertTrue(PersonalList.objects.filter(pk=self.personal.pk).exists())
 def test_financial_blocked_deletion_cancellation_preserves_actual_obligation(self):
  from billing.models import Offer,Order
  offer=Offer.objects.create(code='original-cancel-finance',name='Original synthetic pending order',price_minor=100,currency='INR',duration_seconds=3600,terms_version='original')
  order=Order.objects.create(user=self.user,offer=offer,operation_id=uuid.uuid4(),request_sha256='a'*64,offer_snapshot={},status='pending',total_minor=100,currency='INR',expires_at=timezone.now()+timedelta(hours=1))
  job=self.deletion();run_due_jobs();job.refresh_from_db();self.assertEqual(job.status,'blocked');self.assertEqual(job.error_code,'awaiting_resolution')
  response=self.cancel(job);self.assertEqual(response.status_code,200,response.content)
  order.refresh_from_db();self.assertEqual(order.status,'pending');self.user.refresh_from_db();self.assertTrue(self.user.is_active);self.assertTrue(PersonalList.objects.filter(pk=self.personal.pk).exists())
 def test_claimed_and_completed_privacy_requests_remain_uncancellable(self):
  for kind in ['privacy_export','privacy_delete']:
   for status in ['claimed','done']:
    with self.subTest(kind=kind,status=status):
     job=OutboxJob.objects.create(kind=kind,actor=self.user,dedupe_key=uuid.uuid4().hex,status=status,not_before=timezone.now(),completed_at=timezone.now() if status=='done' else None)
     self.assertFalse(self.client.get(f'/api/v1/me/privacy/requests/{job.id}').json()['can_cancel'])
     response=self.cancel(job);self.assertEqual(response.status_code,409,response.content);job.refresh_from_db();self.assertEqual(job.status,status)
 def test_partial_deletion_cleanup_cannot_be_cancelled_even_if_status_is_pending_or_blocked(self):
  for status in ['pending','blocked']:
   for marker in ['payload','result','completion']:
    with self.subTest(status=status,marker=marker):
     job=OutboxJob.objects.create(kind='privacy_delete',actor=self.user,dedupe_key=uuid.uuid4().hex,status=status,not_before=timezone.now(),payload={'delete_export_keys':[]} if marker=='payload' else {},result={'status':'anonymised'} if marker=='result' else {},completed_at=timezone.now() if marker=='completion' else None)
     self.assertFalse(self.client.get(f'/api/v1/me/privacy/requests/{job.id}').json()['can_cancel'])
     response=self.cancel(job);self.assertEqual(response.status_code,409,response.content);job.refresh_from_db();self.assertEqual(job.status,status)
 def test_foreign_owner_and_stale_reauthentication_never_change_the_request(self):
  job=self.deletion();job.status='blocked';job.error_code='privacy_hold';job.save()
  foreign=Client();self.assertEqual(foreign.post('/api/v1/auth/login',{'email':self.other.email,'password':PASS,'password_purpose_consent':True,'password_purpose_version':'password-account-v1'},content_type='application/json').status_code,200)
  self.assertEqual(self.cancel(job,client=foreign).status_code,404)
  session=self.client.session;session['reauthenticated_at']=(timezone.now()-timedelta(minutes=10)).isoformat();session.save()
  self.assertEqual(self.cancel(job).status_code,403);job.refresh_from_db();self.assertEqual(job.status,'blocked')
 def test_cancelled_prepared_export_keeps_keys_and_hold_for_existing_cleanup(self):
  key=f'exports/{self.user.public_id}/original-cancelled-export.json';raw=b'Original private prepared export';storage.put_private(key,raw,'application/json')
  prepared={'storage_key':key,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'content_type':'application/json','expires_at':(timezone.now()-timedelta(seconds=1)).isoformat()}
  job=OutboxJob.objects.create(kind='privacy_export',actor=self.user,dedupe_key=uuid.uuid4().hex,status='blocked',error_code='provider_not_enabled',not_before=timezone.now(),payload={'prepared_export':prepared,'export_keys':[key],'retention_hold':True})
  payload=dict(job.payload);response=self.cancel(job);self.assertEqual(response.status_code,200,response.content);job.refresh_from_db();self.assertEqual(job.payload,payload)
  self.assertEqual(self.client.post(f'/api/v1/me/privacy/requests/{job.id}/download',{},content_type='application/json').status_code,404)
  self.assertEqual(cleanup_expired_exports(),{'cleaned':0,'failed':0});self.assertTrue(storage.private_exists(key))
  # Separate operator review releases only this synthetic hold; cancellation did not.
  job.payload.pop('retention_hold');job.save()
  self.assertEqual(cleanup_expired_exports(),{'cleaned':1,'failed':0});self.assertFalse(storage.private_exists(key))

 def test_availability_serialization_is_pure_and_does_not_lookup_users_per_row(self):
  from .views import privacy_data,privacy_cancellable
  for kind in ['privacy_delete','privacy_export']:
   job=OutboxJob.objects.create(kind=kind,actor=self.user,dedupe_key=uuid.uuid4().hex,status='pending',not_before=timezone.now())
   for status,allowed in [('pending',True),('blocked',True),('claimed',False),('done',False),('cancelled',False),('dead',False)]:
    job.status=status
    with self.assertNumQueries(0):
     self.assertIs(privacy_cancellable(job),allowed);self.assertIs(privacy_data(job)['can_cancel'],allowed)
