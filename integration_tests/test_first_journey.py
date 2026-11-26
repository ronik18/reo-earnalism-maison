"""Cross-lane first journey. Uses original test-only EN/BN editions, not launch content."""
import hashlib
from email import message_from_string, policy
import io
import json
import re
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs, unquote
from django.conf import settings
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from library import services as library_services
from library.models import Edition
from library.validation import validate_schema
from core.api import DomainError

EN='20000000-0000-4000-8000-000000000001'
BN='20000000-0000-4000-8000-000000000002'

class FirstBookJourneyTests(TestCase):
    def setUp(self):
        self.directory=TemporaryDirectory(prefix='maison-integrated-journey-')
        self.addCleanup(self.directory.cleanup)
        self.overrides=override_settings(MEDIA_ROOT=Path(self.directory.name)/'media',EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',EMAIL_FILE_PATH=Path(self.directory.name)/'mail')
        self.overrides.enable();self.addCleanup(self.overrides.disable)
        call_command('seed_local_pilot',stdout=io.StringIO())
        self.client=Client(enforce_csrf_checks=True)
        self.csrf=self.client.get('/api/v1/session').json()['csrf_token']

    def send(self,path,data=None,method='post',version=None,key=None):
        headers={'HTTP_X_CSRFTOKEN':self.csrf}
        if version is not None:headers['HTTP_IF_MATCH']=f'"v{version}"'
        if key is not None:headers['HTTP_IDEMPOTENCY_KEY']=str(key)
        return getattr(self.client,method)(path,data=json.dumps(data or {}),content_type='application/json',**headers)

    def assertStatus(self,response,status,schema=None):
        self.assertEqual(response.status_code,status,response.content[:2000])
        if schema:
            try:validate_schema(response.json(),schema)
            except DomainError as error:self.fail(f'{schema}: {error.details}')
        return response.json() if status!=204 else None

    def test_preview_verify_read_save_resume_and_logout(self):
        edition=Edition.objects.select_related('live_revision').get(pk=EN)
        unit=edition.live_revision.units.first();paragraph=unit.paragraphs.order_by('ordinal').first()
        # Owner decision 26 Nov 2026: the preview is about a quarter of the story (400 to 1,500 words, never the
        # ending). The fixture story is ~200 words; a lower floor proves the page still stops before the rest.
        with patch.object(library_services,'PREVIEW_MIN_WORDS',60):
            preview=self.client.get(f'/en/read/{EN}/{unit.id}/')
        self.assertEqual(preview.status_code,200)
        self.assertIn(paragraph.text,preview.content.decode())
        self.assertNotIn(unit.paragraphs.order_by('ordinal').last().text,preview.content.decode())
        self.assertStatus(self.send('/api/v1/auth/register',{'email':'journey@example.test','password':'Journey-Original-Passphrase-47','password_purpose_consent':True,'password_purpose_version':'password-account-v1','display_name':'Local journey','locale':'bn','return_path':f'/bn/read/{EN}/{unit.id}/'}),202)
        call_command('run_maintenance',stdout=io.StringIO())
        messages=list((Path(self.directory.name)/'mail').glob('*'))
        self.assertEqual(len(messages),1,'Verification must reach the configured local outbox')
        message=message_from_string(messages[0].read_text(),policy=policy.default)
        link=re.search(r'http://127\.0\.0\.1:8008/auth/verify/\?[^\s]+',message.get_content())
        self.assertIsNotNone(link,'Verification delivery must contain its real local confirmation link')
        url=urlsplit(link.group(0));query=parse_qs(url.query);token=query['token'][0]
        self.assertEqual(query['return_to'][0],f'/bn/read/{EN}/{unit.id}/')
        # GET only shows confirmation and never consumes the token.
        self.assertIn(self.client.get(url.path+'?'+url.query).status_code,[200,302])
        self.assertStatus(self.send('/api/v1/auth/email-verifications/confirm',{'token':token}),200)
        self.csrf=self.client.get('/api/v1/session').json()['csrf_token']
        self.assertStatus(self.send('/api/v1/auth/login',{'email':'journey@example.test','password':'Journey-Original-Passphrase-47','password_purpose_consent':True,'password_purpose_version':'password-account-v1'}),200,'Session')
        self.csrf=self.client.get('/api/v1/session').json()['csrf_token']
        session=self.client.get('/api/v1/session').json()
        # Historic Bengali account/link reaches the shared English controls and unchanged edition.
        reader=self.client.get(f'/bn/read/{EN}/{unit.id}/',follow=True)
        self.assertEqual(reader.status_code,200,reader.content[:1000])
        self.assertContains(reader,unit.paragraphs.order_by('ordinal').last().text)
        self.assertContains(reader,'lang="en"')
        manifest=self.assertStatus(self.client.get(f'/api/v1/content/manifests/{edition.live_revision_id}'),200,'ReaderManifest')
        grant=self.assertStatus(self.send('/api/v1/content/packages/grants',{'edition_revision_id':str(edition.live_revision_id),'unit_ids':[str(unit.id)],'device_id':session['device_id'],'purpose':'online'}),200,'PackageGrant')
        descriptor=grant['assets'][0];url=urlsplit(descriptor['url']);asset_path=url.path+'?'+url.query
        package=self.client.get(asset_path);self.assertEqual(package.status_code,200)
        self.assertEqual(hashlib.sha256(package.content).hexdigest(),descriptor['sha256'])
        progress_path=f'/api/v1/me/progress/{EN}/reader'
        empty=self.assertStatus(self.client.get(progress_path),200,'Progress');self.assertEqual(empty['version'],0)
        operation=str(uuid.uuid4());body={'operation_id':operation,'edition_revision_id':str(edition.live_revision_id),'location':{'format':'reader','unit_id':str(unit.id),'anchor_id':str(paragraph.anchor_id),'offset_chars':0},'occurred_at':timezone.now().isoformat().replace('+00:00','Z')}
        saved=self.assertStatus(self.send(progress_path,body,'put',version=0,key=operation),200,'Progress');self.assertEqual(saved['version'],1)
        replay=self.assertStatus(self.send(progress_path,body,'put',version=0,key=operation),200,'Progress');self.assertEqual(saved,replay)
        stale={**body,'operation_id':str(uuid.uuid4())}
        self.assertStatus(self.send(progress_path,stale,'put',version=0),412)
        note_id=str(uuid.uuid4());annotation={'annotation_id':note_id,'edition_revision_id':str(edition.live_revision_id),'kind':'note','range':{'unit_id':str(unit.id),'start_anchor_id':str(paragraph.anchor_id),'start_offset_chars':0,'end_anchor_id':str(paragraph.anchor_id),'end_offset_chars':len(paragraph.text),'offset_unit':'unicode_code_point'},'color':'gold','note_text':'Original local journey note'}
        self.assertStatus(self.send('/api/v1/me/annotations',annotation,key=note_id),201,'Annotation')
        completion_path=f'/api/v1/me/completion/{EN}/reader'
        completion=self.assertStatus(self.client.get(completion_path),200,'Completion');self.assertEqual(completion['version'],0)
        complete_id=str(uuid.uuid4())
        complete=self.assertStatus(self.send(completion_path,{'operation_id':complete_id,'is_complete':True},'put',version=0,key=complete_id),200,'Completion')
        self.assertTrue(complete['is_complete'])
        self.assertEqual(self.client.get(progress_path).json()['version'],saved['version'],'Completion has its own persisted version')
        self.assertStatus(self.send(f'/api/v1/me/saved-items/{EN}',method='put',key=uuid.uuid4()),200)
        vault=self.assertStatus(self.client.get('/api/v1/me/vault'),200,'Vault')
        self.assertEqual(vault['saved_count'],1);self.assertEqual(len(vault['finished']),1)
        self.assertEqual(self.client.get(progress_path).json()['location'],saved['location'])
        self.assertStatus(self.send('/api/v1/session',method='delete'),204)
        self.assertEqual(self.client.get(asset_path).status_code,401)
        self.assertEqual(self.client.get(progress_path).status_code,401)
        with patch.object(library_services,'PREVIEW_MIN_WORDS',60):  # after logout, back to the bounded preview
            self.assertNotIn(unit.paragraphs.order_by('ordinal').last().text,self.client.get(f'/en/read/{EN}/{unit.id}/').content.decode())
