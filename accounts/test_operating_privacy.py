"""Operating privacy boundaries: held material, truthful outcomes and safe portable data."""
import io,json,time,tempfile,uuid
from datetime import timedelta
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase,RequestFactory,override_settings
from django.utils import timezone
from core.api import DomainError
from core.models import AuditEvent,OutboxJob
from library import storage
from reader.models import PersonalList
from .models import User,Device,Preferences
from .privacy import delete_account,cleanup_expired_exports,_write_export
from .views import contact,privacy_data

@override_settings(LOCAL=True,MEDIA_STORAGE_BACKEND='local')
class OperatingPrivacyTests(TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.settings_override=override_settings(MEDIA_ROOT=self.tmp.name);self.settings_override.enable();self.addCleanup(self.settings_override.disable)
  self.user=User.objects.create_user('held-original@example.test','Original-Held-Account-47',is_verified=True)
  self.other=User.objects.create_user('foreign-original@example.test','Original-Held-Account-47',is_verified=True)
  self.personal=PersonalList.objects.create(user=self.user,name='Retain original list')
  self.pref=Preferences.objects.create(user=self.user)
  self.device=Device.objects.create(user=self.user,token_binding_sha256='a'*64,expires_at=timezone.now()+timedelta(days=1))
  self.key=f'exports/{self.user.public_id}/original-retained.json';storage.put_private(self.key,b'Original private export','application/json')
  self.export=OutboxJob.objects.create(kind='privacy_export',actor=self.user,dedupe_key=uuid.uuid4().hex,status='done',not_before=timezone.now(),result={'storage_key':self.key,'expires_at':(timezone.now()-timedelta(seconds=1)).isoformat()})
  self.support=OutboxJob.objects.create(kind='contact_support',actor=self.user,dedupe_key=uuid.uuid4().hex,status='done',not_before=timezone.now(),payload={'email':self.user.email,'message':'Original retained support text'},result={'status':'submitted','smtp_submission_accepted':True})
  self.deletion=OutboxJob.objects.create(kind='privacy_delete',actor=self.user,dedupe_key=uuid.uuid4().hex,not_before=timezone.now())
 def assert_preserved(self):
  self.user.refresh_from_db();self.device.refresh_from_db();self.support.refresh_from_db()
  self.assertTrue(self.user.is_active);self.assertEqual(self.user.email,'held-original@example.test')
  self.assertIsNone(self.device.revoked_at);self.assertTrue(PersonalList.objects.filter(pk=self.personal.pk).exists());self.assertTrue(Preferences.objects.filter(pk=self.pref.pk).exists())
  self.assertEqual(self.support.payload['message'],'Original retained support text');self.assertTrue(storage.private_exists(self.key))
 def test_account_hold_blocks_every_destructive_step(self):
  AuditEvent.objects.create(actor=self.user,action='legal.hold',entity_kind='User',entity_id=str(self.user.pk))
  with self.assertRaises(DomainError) as caught:delete_account(self.deletion)
  self.assertEqual(caught.exception.code,'privacy_hold');self.assert_preserved()
 def test_deletion_job_hold_blocks_before_payload_or_personal_data_changes(self):
  self.deletion.payload={'legal_hold':True,'reason':'Existing original operator hold'};self.deletion.save()
  with self.assertRaises(DomainError) as caught:delete_account(self.deletion)
  self.assertEqual(caught.exception.code,'privacy_hold');self.deletion.refresh_from_db();self.assertTrue(self.deletion.payload['legal_hold']);self.assert_preserved()
 def test_owned_support_or_export_row_holds_cannot_be_erased_by_account_deletion(self):
  for row in [self.support,self.export]:
   with self.subTest(kind=row.kind):
    marker=AuditEvent.objects.create(action='retention.hold',entity_kind='OutboxJob',entity_id=str(row.pk))
    with self.assertRaises(DomainError) as caught:delete_account(self.deletion)
    self.assertEqual(caught.exception.code,'privacy_hold');self.assert_preserved();marker.delete()
 def test_expired_export_holds_preserve_object_and_metadata(self):
  original=dict(self.export.result)
  for mode in ['account','payload','marker']:
   with self.subTest(mode=mode):
    marker=None
    if mode=='account':marker=AuditEvent.objects.create(actor=self.user,action='legal.hold',entity_kind='User',entity_id=str(self.user.pk))
    elif mode=='payload':self.export.payload={'retention_hold':True};self.export.save()
    else:marker=AuditEvent.objects.create(action='retention.hold',entity_kind='OutboxJob',entity_id=str(self.export.pk))
    self.assertEqual(cleanup_expired_exports(),{'cleaned':0,'failed':0});self.export.refresh_from_db();self.assertEqual(self.export.result,original);self.assertTrue(storage.private_exists(self.key))
    if marker:marker.delete()
    self.export.payload={};self.export.save()
  self.assertEqual(cleanup_expired_exports(),{'cleaned':1,'failed':0});self.assertFalse(storage.private_exists(self.key))
 def test_unconfigured_production_contact_rejects_before_collecting_or_queueing(self):
  from unittest.mock import patch
  request=RequestFactory().post('/api/v1/contact',{'email':'original-contact@example.test','locale':'en','category':'privacy','message':'Original support inquiry'},content_type='application/json');request.user=AnonymousUser()
  before=OutboxJob.objects.count()
  with override_settings(LOCAL=False,SUPPORT_EMAIL=''),patch('accounts.services.check_rate') as rate:
   response=contact(request)
  self.assertEqual(response.status_code,503);self.assertEqual(json.loads(response.content)['code'],'support_not_configured');self.assertEqual(OutboxJob.objects.count(),before);rate.assert_not_called()
 def test_deletion_with_no_financial_rows_reports_no_financial_retention(self):
  result=delete_account(self.deletion);self.assertEqual(result.get('retained_categories'),['account_security_records'])
  self.deletion.status='done';self.deletion.result=result
  self.assertEqual(privacy_data(self.deletion)['retained_categories'],['account_security_records'])
 def test_actual_retained_financial_history_is_reported_without_inventing_pending_retention(self):
  from billing.models import Order,Offer
  offer=Offer.objects.create(code='retained-original',name='Original retained fixture',price_minor=100,currency='INR',duration_seconds=100,terms_version='original')
  Order.objects.create(user=self.user,offer=offer,total_minor=100,currency='INR',status='paid',offer_snapshot={},operation_id=uuid.uuid4(),request_sha256='a'*64,expires_at=timezone.now()+timedelta(hours=1))
  self.assertEqual(privacy_data(self.deletion)['retained_categories'],[])
  result=delete_account(self.deletion);self.assertEqual(result.get('retained_categories'),['account_security_records','financial_obligations'])
  self.deletion.status='done';self.deletion.result=result;self.assertEqual(privacy_data(self.deletion)['retained_categories'],['account_security_records','financial_obligations'])
  self.deletion.status='blocked';self.deletion.error_code='privacy_hold';self.assertEqual(privacy_data(self.deletion)['retained_categories'],['legal_or_retention_hold'])
 def test_portable_export_streams_only_owned_device_and_support_fields(self):
  own_device=Device.objects.create(user=self.user,label='Original owned device',token_binding_sha256='b'*64,expires_at=timezone.now()+timedelta(days=1))
  foreign_device=Device.objects.create(user=self.other,label='FOREIGN-DEVICE',token_binding_sha256='c'*64,expires_at=timezone.now()+timedelta(days=1))
  for i in range(201):OutboxJob.objects.create(kind='contact_support',actor=self.user,dedupe_key=uuid.uuid4().hex,not_before=timezone.now(),payload={'email':self.user.email,'locale':'en','category':'privacy','message':f'Original owned support {i}','order_id':str(uuid.uuid4()),'provider_token':'PRIVATE-PROVIDER-SENTINEL'},result={'operator_secret':'PRIVATE-OPERATOR-SENTINEL'})
  OutboxJob.objects.create(kind='contact_support',actor=self.other,dedupe_key=uuid.uuid4().hex,not_before=timezone.now(),payload={'message':'FOREIGN-SUPPORT'})
  OutboxJob.objects.create(kind='contact_support',dedupe_key=uuid.uuid4().hex,not_before=timezone.now(),payload={'email':self.user.email,'message':'ANONYMOUS-SUPPORT'})
  output=io.BytesIO();_write_export(self.user,output,time.monotonic()+30);raw=output.read();body=json.loads(raw)
  self.assertEqual(len(body['devices']),2);self.assertEqual(len(body['support_requests']),202)
  self.assertIn(str(own_device.id),[row['id'] for row in body['devices']]);self.assertNotIn(str(foreign_device.id),raw.decode())
  for value in ['PRIVATE-PROVIDER-SENTINEL','PRIVATE-OPERATOR-SENTINEL','FOREIGN-SUPPORT','ANONYMOUS-SUPPORT','FOREIGN-DEVICE','token_binding_sha256','session_key','lease_owner','storage_key']:
   self.assertNotIn(value,raw.decode())
 def test_held_deletion_worker_is_blocked_with_a_visible_pending_review_status(self):
  from core.jobs import run_due_jobs
  AuditEvent.objects.create(actor=self.user,action='legal.hold',entity_kind='User',entity_id=str(self.user.pk))
  self.assertEqual(run_due_jobs(limit=1),{'processed':1});self.deletion.refresh_from_db()
  self.assertEqual(self.deletion.status,'blocked');self.assertEqual(self.deletion.error_code,'privacy_hold');self.assertIsNone(self.deletion.completed_at)
  self.assertEqual(privacy_data(self.deletion)['status'],'awaiting_resolution');self.assert_preserved()
 def test_legacy_completed_retention_details_are_explicitly_unknown(self):
  self.deletion.status='done';self.deletion.result={'status':'anonymised_financial_records_retained'}
  self.assertEqual(privacy_data(self.deletion)['retained_categories'],['retention_details_unavailable'])
  self.deletion.result={'retained_categories':[{'secret':'never serialize'},'financial_obligations']}
  self.assertEqual(privacy_data(self.deletion)['retained_categories'],['financial_obligations'])
 def test_malformed_legacy_support_nested_values_are_not_exported_as_credentials(self):
  self.support.payload={'message':{'signed_url':'NESTED-PRIVATE-CAPABILITY'},'email':['NESTED-PRIVATE-EMAIL'],'category':'privacy'};self.support.save()
  output=io.BytesIO();_write_export(self.user,output,time.monotonic()+10);raw=output.read();body=json.loads(raw)
  self.assertIsNone(body['support_requests'][0]['message']);self.assertIsNone(body['support_requests'][0]['email']);self.assertNotIn('NESTED-PRIVATE',raw.decode())
 def test_export_cleanup_advances_past_held_prefix_and_wraps_after_release(self):
  # Fixed UUID ordering puts two held artifacts before the eligible suffix.
  old=self.export;old.status='cancelled';old.result={};old.payload={};old.save()
  rows=[]
  for i in [1,2,3]:
   key=f'exports/{self.user.public_id}/ordered-{i}.json';storage.put_private(key,b'Original ordered artifact','application/json')
   row=OutboxJob.objects.create(id=uuid.UUID(int=i),kind='privacy_export',actor=self.user,dedupe_key=uuid.uuid4().hex,status='done',not_before=timezone.now(),payload={'legal_hold':True} if i<3 else {},result={'storage_key':key,'expires_at':(timezone.now()-timedelta(days=1)).isoformat()});rows.append((row,key))
  self.assertEqual(cleanup_expired_exports(limit=2),{'cleaned':0,'failed':0})
  checkpoint=OutboxJob.objects.get(dedupe_key='retention:privacy-exports:v1');self.assertIsNone(checkpoint.actor_id);self.assertEqual(checkpoint.payload['after'],str(rows[1][0].id))
  self.assertEqual(cleanup_expired_exports(limit=2),{'cleaned':1,'failed':0});self.assertFalse(storage.private_exists(rows[2][1]));self.assertTrue(storage.private_exists(rows[0][1]));checkpoint.refresh_from_db();self.assertIsNone(checkpoint.payload['after'])
  rows[0][0].payload={};rows[0][0].save();self.assertEqual(cleanup_expired_exports(limit=2),{'cleaned':1,'failed':0});self.assertFalse(storage.private_exists(rows[0][1]));self.assertTrue(storage.private_exists(rows[1][1]))
 def test_export_checkpoint_lock_is_not_held_during_provider_io(self):
  from django.db import connection
  from unittest.mock import patch
  original=storage.delete_private;baseline_depth=len(connection.atomic_blocks)
  def delete(key):
   # Provider latency never owns any extra checkpoint/export row transaction.
   self.assertEqual(len(connection.atomic_blocks),baseline_depth)
   return original(key)
  with patch('library.storage.delete_private',side_effect=delete):self.assertEqual(cleanup_expired_exports(),{'cleaned':1,'failed':0})
 def test_malformed_export_metadata_is_conservatively_preserved(self):
  self.export.payload=[];self.export.save()
  self.assertEqual(cleanup_expired_exports(),{'cleaned':0,'failed':0})
  self.export.refresh_from_db();self.assertEqual(self.export.payload,[]);self.assertTrue(storage.private_exists(self.key))
