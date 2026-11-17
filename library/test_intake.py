import uuid,json,io,tempfile
from django.test import TestCase,Client,override_settings
from django.contrib.auth import get_user_model
from .models import Edition,Revision
from .services import revision_hash,validate_revision,_reader_package_coverage
from .intake_api import PACKET

class ClearedDraftJourneyTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.o=override_settings(MEDIA_ROOT=self.tmp.name);self.o.enable();self.addCleanup(self.o.disable)
        self.staff=get_user_model().objects.create_superuser('intake@example.test','Local-Intake-Password-47')
        self.client=Client(enforce_csrf_checks=True)
        token=self.client.get('/api/v1/session').json()['csrf_token']
        self.client.post('/api/v1/auth/login',json.dumps({'email':self.staff.email,'password':'Local-Intake-Password-47'}),content_type='application/json',HTTP_X_CSRFTOKEN=token)
        self.csrf=self.client.get('/api/v1/session').json()['csrf_token']
    def test_draft_intake_review_integrity_replay_and_member_denial(self):
        key=str(uuid.uuid4());body=json.dumps({'manifest_id':'EN-071'})
        def ingest():return self.client.post('/api/v1/staff/books/imports',body,content_type='application/json',HTTP_X_CSRFTOKEN=self.csrf,HTTP_IDEMPOTENCY_KEY=key)
        first=ingest();self.assertEqual(first.status_code,201,first.content);self.assertEqual(first.json(),ingest().json())
        r=Revision.objects.get(pk=first.json()['edition_revision_id']);self.assertEqual(r.state,'draft');self.assertIsNone(r.edition.live_revision_id)
        self.assertEqual(r.content_sha256,revision_hash(r));self.assertTrue(_reader_package_coverage(r,list(r.assets.all())))
        doc=self.client.get(f'/api/v1/staff/drafts/{r.id}/document');self.assertEqual(doc.status_code,200)
        paras=doc.json()['units'][0]['paragraphs'];self.assertEqual([p['text'] for p in paras],json.loads(PACKET.read_text())['paragraphs'])
        self.assertTrue(paras[0]['text'].startswith('EVERY afternoon'));self.assertTrue(paras[-1]['text'].endswith('white blossoms.'))
        self.assertNotIn('gutenberg',doc.content.decode().lower());self.assertNotIn('[Picture:',doc.content.decode())
        guest=Client();self.assertEqual(guest.get(f'/api/v1/staff/drafts/{r.id}/document').status_code,401)
        self.assertNotEqual(self.client.get(f'/api/v1/content/manifests/{r.id}').status_code,200)
        self.assertNotEqual(guest.get(f'/api/v1/catalog/editions/{r.edition_id}').status_code,200)
        report=validate_revision(r);self.assertEqual(report['status'],'fail');self.assertIn('cover',[c['code'] for c in report['checks'] if c['status']=='fail'])
        r.refresh_from_db();self.assertEqual(r.state,'draft')
