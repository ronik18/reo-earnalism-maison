import io
import json
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from django.core.management import call_command
from django.db import close_old_connections,connection,connections,OperationalError
from django.test import TestCase,TransactionTestCase,override_settings
from django.utils import timezone
from accounts.models import User
from core.api import DomainError
from core.models import OperationReceipt
from library.models import Edition
from library.validation import validate_schema
from .models import Progress,Completion,Annotation
from . import services

EN='20000000-0000-4000-8000-000000000001'
PASS='Local-Reader-Passphrase-47'

class ReaderFixture:
    def seed(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.override=override_settings(MEDIA_ROOT=self.directory.name,MAISON_LOCAL_FIXTURES=True,LOCAL=True);self.override.enable();self.addCleanup(self.override.disable)
        call_command('seed_local_pilot',stdout=io.StringIO())
        self.user=User.objects.create_user('reader@example.test',PASS,is_verified=True)
        self.edition=Edition.objects.select_related('live_revision').get(pk=EN);self.revision=self.edition.live_revision;self.unit=self.revision.units.first();self.para=self.unit.paragraphs.first()
    def data(self,operation=None,offset=2):
        return {'operation_id':str(operation or uuid.uuid4()),'edition_revision_id':str(self.revision.id),'location':{'format':'reader','unit_id':str(self.unit.id),'anchor_id':str(self.para.anchor_id),'offset_chars':offset},'occurred_at':timezone.now().isoformat().replace('+00:00','Z')}

class ReaderAcceptanceTests(ReaderFixture,TestCase):
    def setUp(self):
        self.seed();self.client.post('/api/v1/auth/login',{'email':self.user.email,'password':PASS},content_type='application/json')
    def test_progress_first_v0_replay_conflict_and_strict_contract(self):
        initial=self.client.get(f'/api/v1/me/progress/{EN}/reader');self.assertEqual(initial.json()['version'],0);validate_schema(initial.json(),'Progress')
        data=self.data();path=f'/api/v1/me/progress/{EN}/reader'
        first=self.client.put(path,data,content_type='application/json',HTTP_IF_MATCH='"v0"');self.assertEqual(first.status_code,200,first.content);validate_schema(first.json(),'Progress')
        repeat=self.client.put(path,data,content_type='application/json',HTTP_IF_MATCH='"v0"');self.assertEqual(first.json(),repeat.json())
        stale=self.client.put(path,self.data(),content_type='application/json',HTTP_IF_MATCH='"v0"');self.assertEqual(stale.status_code,412);validate_schema(stale.json(),'Problem')
        changed=self.client.put(path,{**data,'location':{**data['location'],'offset_chars':3}},content_type='application/json',HTTP_IF_MATCH='"v0"');self.assertEqual(changed.status_code,409)
        self.assertEqual(Progress.objects.count(),1);self.assertEqual(OperationReceipt.objects.filter(kind='progress.set').count(),1)
    def test_completion_is_independent_from_progress_and_seek(self):
        self.client.put(f'/api/v1/me/progress/{EN}/reader',self.data(),content_type='application/json',HTTP_IF_MATCH='"v0"')
        path=f'/api/v1/me/completion/{EN}/reader';initial=self.client.get(path);self.assertEqual(initial.json()['version'],0);validate_schema(initial.json(),'Completion')
        done=self.client.put(path,{'operation_id':str(uuid.uuid4()),'is_complete':True},content_type='application/json',HTTP_IF_MATCH='"v0"');self.assertEqual(done.status_code,200,done.content);validate_schema(done.json(),'Completion')
        self.assertEqual(Progress.objects.get().version,1);self.assertTrue(Completion.objects.get().is_complete)
        vault=self.client.get('/api/v1/me/vault');validate_schema(vault.json(),'Vault');self.assertEqual(vault.json()['finished_count'],1);self.assertEqual(len(vault.json()['continue']),0)
        self.assertEqual(vault.json()['finished'][0]['completion']['version'],1)
    def annotation(self):
        return {'annotation_id':str(uuid.uuid4()),'edition_revision_id':str(self.revision.id),'kind':'highlight','range':{'unit_id':str(self.unit.id),'start_anchor_id':str(self.para.anchor_id),'start_offset_chars':0,'end_anchor_id':str(self.para.anchor_id),'end_offset_chars':5,'offset_unit':'unicode_code_point'},'color':'mint','note_text':None}
    def test_annotation_quote_palette_ownership_and_tombstone_replay(self):
        data=self.annotation();key=str(uuid.uuid4());first=self.client.post('/api/v1/me/annotations',data,content_type='application/json',HTTP_IDEMPOTENCY_KEY=key)
        self.assertEqual(first.status_code,201,first.content);validate_schema(first.json(),'Annotation');self.assertEqual(first.json()['quoted_text'],self.para.text[:5])
        self.assertEqual(self.client.post('/api/v1/me/annotations',data,content_type='application/json',HTTP_IDEMPOTENCY_KEY=key).json(),first.json())
        aid=data['annotation_id'];deleted=self.client.delete(f'/api/v1/me/annotations/{aid}',HTTP_IF_MATCH='"v1"',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()));self.assertEqual(deleted.status_code,204)
        self.assertEqual(self.client.post('/api/v1/me/annotations',data,content_type='application/json',HTTP_IDEMPOTENCY_KEY=key).status_code,201)
        self.assertIsNotNone(Annotation.objects.get(pk=aid).deleted_at)
        other=User.objects.create_user('other@example.test',PASS,is_verified=True);self.client.post('/api/v1/auth/login',{'email':other.email,'password':PASS},content_type='application/json')
        self.assertEqual(self.client.get(f'/api/v1/me/annotations/{aid}').status_code,404)
    def test_keyed_actions_reject_missing_idempotency_key(self):
        response=self.client.put(f'/api/v1/me/saved-items/{EN}');self.assertEqual(response.status_code,400);validate_schema(response.json(),'Problem')
    def test_saved_and_lists_round_trip_strict_shapes(self):
        saved=self.client.put(f'/api/v1/me/saved-items/{EN}',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()));self.assertEqual(saved.status_code,200,saved.content);validate_schema(saved.json(),'SavedItem')
        created=self.client.post('/api/v1/me/lists',{'name':'Evening reading'},content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()));self.assertEqual(created.status_code,201,created.content);validate_schema(created.json(),'PersonalList')
        listed=self.client.put(f'/api/v1/me/lists/{created.json()["list_id"]}/items/{EN}',HTTP_IF_MATCH=created['ETag'],HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()));self.assertEqual(listed.status_code,200,listed.content);validate_schema(listed.json(),'PersonalListDetail');self.assertEqual(listed.json()['edition_ids'],[EN])
    def test_partial_sync_database_failure_replays_prior_commit(self):
        device=self.client.get('/api/v1/session').json()['device_id'];a=self.data();b=self.data(offset=3)
        def operation(d,base):return {'kind':'progress.set','base_version':base,'edition_id':EN,**d}
        batch={'device_id':device,'operations':[operation(a,0),operation(b,1)]};real=services.set_progress;calls=0
        def interrupted(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==2:raise OperationalError('synthetic interrupted dependency')
            return real(*args,**kwargs)
        with patch('reader.services.set_progress',side_effect=interrupted):response=self.client.post('/api/v1/me/sync',batch,content_type='application/json')
        self.assertEqual(response.status_code,503,response.content);self.assertEqual(Progress.objects.get().version,1)
        retry=self.client.post('/api/v1/me/sync',batch,content_type='application/json');self.assertEqual(retry.status_code,200,retry.content);validate_schema(retry.json(),'SyncResponse')
        self.assertEqual([x['outcome'] for x in retry.json()['results']],['replayed','applied']);self.assertEqual(Progress.objects.get().version,2)

class ProgressConcurrencyTests(ReaderFixture,TransactionTestCase):
    reset_sequences=True
    def setUp(self):self.seed()
    def race(self,same_operation):
        barrier=Barrier(2);operation=uuid.uuid4();data=self.data(operation)
        def write(index):
            close_old_connections()
            try:
                user=User.objects.get(pk=self.user.pk);request=data if same_operation else {**data,'operation_id':str(uuid.uuid4())}
                barrier.wait(timeout=10)
                try:return services.set_progress(user,EN,'reader',request,0)
                except DomainError as e:return e.status,{'code':e.code}
            finally:connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(write,[0,1]))
    def test_distinct_first_writes_yield_one_v1_and_one_conflict(self):
        self.assertEqual(connection.vendor,'postgresql')
        results=self.race(False);self.assertEqual(sorted(x[0] for x in results),[200,412]);self.assertEqual(Progress.objects.count(),1);self.assertEqual(Progress.objects.get().version,1)
    def test_same_operation_concurrent_replay_returns_identical_receipt(self):
        results=self.race(True);self.assertEqual(results[0],results[1]);self.assertEqual(Progress.objects.get().version,1);self.assertEqual(OperationReceipt.objects.filter(kind='progress.set').count(),1)
