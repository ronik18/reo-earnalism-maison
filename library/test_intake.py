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
        self.assertEqual(self.client.get(f'/api/v1/content/manifests/{r.id}').status_code,200)
        self.assertNotEqual(guest.get(f'/api/v1/catalog/editions/{r.edition_id}').status_code,200)
        report=validate_revision(r);self.assertEqual(report['status'],'fail');self.assertIn('cover',[c['code'] for c in report['checks'] if c['status']=='fail'])
        r.refresh_from_db();self.assertEqual(r.state,'draft')

    def test_staff_full_reader_keeps_draft_private_and_persisted_pointer_empty(self):
        self.test_draft_intake_review_integrity_replay_and_member_denial()
        r=Revision.objects.get();unit=r.units.first()
        url=f'/en/read/{r.edition_id}/{unit.id}/'
        page=self.client.get(url);self.assertEqual(page.status_code,200,page.content)
        self.assertContains(page,'Staff draft review')
        self.assertContains(page,'all covered with white blossoms.')
        self.assertEqual(Client().get(url).status_code,404)
        member=get_user_model().objects.create_user('member-review@example.test','Local-Member-Password-47',is_verified=True)
        c=Client();c.post('/api/v1/auth/login',{'email':member.email,'password':'Local-Member-Password-47'},content_type='application/json')
        self.assertEqual(c.get(url).status_code,404)
        self.assertNotEqual(c.get(f'/api/v1/content/manifests/{r.id}').status_code,200)
        u=r.units.first();p=u.paragraphs.first();from django.utils import timezone
        key=str(uuid.uuid4());body={'operation_id':key,'edition_revision_id':str(r.id),'location':{'format':'reader','unit_id':str(u.id),'anchor_id':str(p.anchor_id),'offset_chars':0},'occurred_at':timezone.now().isoformat().replace('+00:00','Z')}
        result=self.client.put(f'/api/v1/me/progress/{r.edition_id}/reader',json.dumps(body),content_type='application/json',HTTP_X_CSRFTOKEN=self.csrf,HTTP_IF_MATCH='"v0"')
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(c.get(f'/api/v1/me/progress/{r.edition_id}/reader').status_code,404)
        r.refresh_from_db();self.assertEqual(r.state,'draft');r.edition.refresh_from_db();self.assertIsNone(r.edition.live_revision_id)

    def test_current_cover_pair_is_private_and_replaces_older_selection(self):
        self.test_draft_intake_review_integrity_replay_and_member_denial()
        from .models import Asset
        from .services import digest,asset_path,_cover
        r=Revision.objects.get();images=[]
        for name in ['front','back']:
            raw=(PACKET.parent/'covers'/(name+'.jpg')).read_bytes();identifier=uuid.uuid4();key=f'revisions/{r.id}/{identifier}'
            path=asset_path(key);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            images.append(Asset.objects.create(id=identifier,revision=r,kind='cover',state='ready',storage_key=key,sha256=digest(raw),bytes=len(raw),content_type='image/jpeg'))
        r.validation_evidence={'cover_pair':{'front':{'asset_id':str(images[1].id)}}};r.save()
        self.assertIn(str(images[1].id),_cover(r)['url'])
        url=f'/api/v1/staff/draft-covers/{images[1].id}'
        result=self.client.get(url);self.assertEqual(result.status_code,200);self.assertEqual(result['Cache-Control'],'private, no-store')
        self.assertEqual(digest(result.content),images[1].sha256)
        self.assertEqual(Client().get(url).status_code,401)
        member=get_user_model().objects.create_user('ordinary-cover@example.test','Ordinary-Password-47',is_verified=True)
        c=Client();c.post('/api/v1/auth/login',{'email':member.email,'password':'Ordinary-Password-47'},content_type='application/json')
        self.assertEqual(c.get(url).status_code,403)
        self.assertEqual(c.get(f'/api/v1/staff/draft-editions/{r.edition_id}').status_code,403)
        page=self.client.get(f'/en/titles/{r.edition_id}/');self.assertContains(page,'Reader · draft edition')

        from .services import clone_revision
        clone=clone_revision(r.id)
        selected=clone.validation_evidence['cover_pair']['front']['asset_id']
        self.assertNotEqual(selected,str(images[1].id));self.assertIn(selected,_cover(clone)['url'])
        self.assertEqual(clone.assets.get(pk=selected).sha256,images[1].sha256)
        self.assertNotIn('browser',clone.validation_evidence)
        self.assertFalse(clone.rights.filter(approved=True).exists())
