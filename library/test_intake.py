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

    def test_reviewed_country_rights_enforce_draft_and_format_boundaries(self):
        self.test_draft_intake_review_integrity_replay_and_member_denial()
        from .services import current_right,authorize_revision
        from core.api import DomainError
        r=Revision.objects.get()
        approved={'TW', 'LK', 'FR', 'OM', 'AM', 'MV', 'KZ', 'ID', 'QA', 'MM', 'US', 'JP', 'IQ', 'AZ', 'LA', 'NP', 'TH', 'BT', 'GB', 'NL', 'SG', 'BD', 'MY', 'KH', 'BR', 'IL', 'SA', 'BN', 'TR', 'CY', 'DK', 'PH', 'IN', 'MO', 'CA', 'GE', 'DE', 'YE', 'JO', 'HK', 'PK', 'UZ', 'NZ', 'KR', 'BH', 'RU', 'LB'}
        self.assertEqual(r.rights.count(),2)
        for right in r.rights.all():
            self.assertEqual(set(right.territories),approved)
            self.assertFalse(right.test_only)
        member=get_user_model().objects.create_user('country-member@example.test','Local-Member-47',is_verified=True)
        for country in approved:
            with self.subTest(country=country):
                self.assertIsNotNone(current_right(r,action='preview',territory=country))
                self.assertEqual(authorize_revision(self.staff,r,territory=country).pk,r.pk)
                with self.assertRaises(DomainError):authorize_revision(member,r,territory=country)
                for fmt,action in [('reader','download'),('audio','read'),('video','read')]:
                    self.assertIsNone(current_right(r,format=fmt,action=action,territory=country))
                    with self.assertRaises(DomainError):authorize_revision(self.staff,r,format=fmt,action=action,territory=country)
        for country in ['AE', 'AF', 'CN', 'EG', 'IR', 'KG', 'KP', 'KW', 'MN', 'PS', 'SY', 'TJ', 'TL', 'TM', 'VN', 'ZZ', 'SN', 'FO', 'GL', '*', 'London', 'Scotland']:
            with self.subTest(denied=country):
                self.assertIsNone(current_right(r,territory=country))
                with self.assertRaises(DomainError):authorize_revision(self.staff,r,territory=country)
        r.refresh_from_db();r.edition.refresh_from_db()
        self.assertEqual(r.state,'draft');self.assertIsNone(r.edition.live_revision_id)

    def test_intake_country_review_rejects_changed_text_or_unreviewed_grant(self):
        import copy
        from .intake_api import reviewed_territories,RIGHTS_REVIEW
        from core.api import DomainError
        packet=json.loads(PACKET.read_text());review=json.loads(RIGHTS_REVIEW.read_text())
        expected=review['paragraphs_sha256']
        self.assertEqual(reviewed_territories(packet,expected),packet['rights']['territories'])
        self.assertEqual(review['requested_place_aliases'],{'London':'GB','Scotland':'GB'})
        asia={row['territory'] for row in review['geographic_scope']['asian_jurisdictions']}
        self.assertEqual(len(asia),53)
        self.assertTrue({'CN','HK','MO','TW','RU','EG','PS','TL','KP'}.issubset(asia))
        self.assertEqual(set(review['historical_requested_territories']),asia|{'BR','US','NZ','GB','FR','DE','NL','DK','CA'})
        from django.conf import settings
        self.assertEqual(set(review['requested_territories']),set(settings.MAISON_PUBLICATION_TERRITORIES))
        self.assertEqual(review['held_territories'],[])
        self.assertEqual(set(review['out_of_scope_territories']),{'AE','CN'})
        self.assertFalse(set(review['requested_territories']) & set(review['excluded_pending_territories']))
        self.assertEqual(set(review['runtime_approved_territories'])|set(review['held_territories']),set(review['requested_territories']))
        self.assertTrue({'BR','HK','MO','TW','JP','KR','BD'}.issubset(review['runtime_approved_territories']))
        with self.assertRaises(DomainError):reviewed_territories(packet,'0'*64)
        changed=copy.deepcopy(packet);changed['paragraphs'][0]+=' Changed.'
        with self.assertRaises(DomainError):reviewed_territories(changed,expected)
        for grant in [['*'],['IN','CN'],['IN'],['IN','IN']]:
            altered=copy.deepcopy(packet);altered['rights']['territories']=grant
            with self.subTest(grant=grant),self.assertRaises(DomainError):reviewed_territories(altered,expected)

    def test_publication_checks_entire_whitelist_and_hash_bound_legal_evidence(self):
        self.test_draft_intake_review_integrity_replay_and_member_denial()
        from django.conf import settings
        r=Revision.objects.get()
        def checks():return {c['code']:c['status'] for c in validate_revision(r)['checks']}
        self.assertEqual(checks()['publication_regions'],'pass')
        self.assertEqual(checks()['publication_clearance'],'fail')
        # Synthetic evidence tests the boundary; it is never applied to the actual draft.
        r.validation_evidence={'publication_clearance':{'status':'pass','sha256':r.content_sha256,
            'territories':list(settings.MAISON_PUBLICATION_TERRITORIES),'formats':['reader'],
            'asset_sha256':{str(a.id):a.sha256 for a in r.assets.filter(state='ready')},
            'evidence_ref':'synthetic-test-only/legal-review'}};r.save()
        self.assertEqual(checks()['publication_clearance'],'pass')
        right=r.rights.get(action='read');original=right.territories
        right.territories=[c for c in original if c!='BR'];right.save()
        current=checks();self.assertEqual(current['rights'],'pass');self.assertEqual(current['publication_regions'],'fail')
        right.territories=original;right.save()
        for field,value in [('territories',['IN']),('formats',['reader','audio']),('sha256','0'*64),('asset_sha256',{}),('evidence_ref','')]:
            original_value=r.validation_evidence['publication_clearance'][field]
            r.validation_evidence['publication_clearance'][field]=value;r.save()
            with self.subTest(field=field):self.assertEqual(checks()['publication_clearance'],'fail')
            r.validation_evidence['publication_clearance'][field]=original_value
        r.save();self.assertEqual(checks()['publication_clearance'],'pass')
        r.refresh_from_db();self.assertEqual(r.state,'draft');self.assertIsNone(r.edition.live_revision_id)

    def test_nonwhitelisted_countries_denied_even_with_accidental_explicit_grant(self):
        self.test_draft_intake_review_integrity_replay_and_member_denial()
        from .services import current_right
        from .intake_api import RIGHTS_REVIEW
        r=Revision.objects.get();review=json.loads(RIGHTS_REVIEW.read_text())
        excluded=review['out_of_scope_territories']+review['excluded_pending_territories']
        right=r.rights.get(action='read');right.territories=excluded+['IN'];right.save()
        self.assertIsNotNone(current_right(r,territory='IN'))
        for country in excluded:
            with self.subTest(country=country):self.assertIsNone(current_right(r,territory=country))
        right.territories=['*'];right.save()
        for country in excluded+['ZZ']:
            with self.subTest(wildcard_country=country):self.assertIsNone(current_right(r,territory=country))
