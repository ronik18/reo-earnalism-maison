import io,json,uuid
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase,RequestFactory
from django.utils import timezone
from core.api import DomainError
from core.pagination import paginate_queryset
from library.models import Work,Edition,Revision
from .models import SavedItem,PersonalList,Progress,Completion
from .services import vault_data

class PrivatePaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user=get_user_model().objects.create_user('paging@example.test','Local-test-password-47',is_verified=True)
        cls.other=get_user_model().objects.create_user('foreign-paging@example.test','Local-test-password-47',is_verified=True)
        work=Work.objects.create(slug='paging-fixture',title='Paging fixture',house='learn')
        cls.editions=[Edition.objects.create(work=work,slug=f'paging-{n}',locale='en') for n in range(125)]
        SavedItem.objects.bulk_create([SavedItem(user=cls.user,edition=e) for e in cls.editions])
        SavedItem.objects.all().update(created_at=timezone.now())
        PersonalList.objects.bulk_create([PersonalList(user=cls.user,name=f'List {n:03}') for n in range(25)])
    def request(self,query=None,user=None,territory='IN'):
        r=RequestFactory().get('/api/v1/me/saved-items',query or {});r.user=user or self.user;r.territory=territory;return r
    def test_more_than100_ties_complete_stable_and_private_binding(self):
        rows=SavedItem.objects.filter(user=self.user)
        first=paginate_queryset(self.request({'limit':'100'}),rows,'saved-items')
        self.assertEqual(len(first['items']),100);self.assertTrue(first['has_more'])
        cursor=first['next_cursor'];second=paginate_queryset(self.request({'limit':'100','cursor':cursor}),rows,'saved-items')
        self.assertEqual(len(second['items']),25);self.assertFalse(second['has_more'])
        self.assertEqual(len({r.id for r in first['items']+second['items']}),125)
        for request in [self.request({'limit':'99','cursor':cursor}),self.request({'limit':'100','cursor':cursor},user=self.other),self.request({'limit':'100','cursor':cursor},territory='GB'),self.request({'limit':'100','cursor':'tampered'})]:
            with self.assertRaises(DomainError):paginate_queryset(request,rows,'saved-items')
        with patch('django.core.signing.time.time',return_value=timezone.now().timestamp()+3601):
            with self.assertRaises(DomainError):paginate_queryset(self.request({'limit':'100','cursor':cursor}),rows,'saved-items')
    def test_name_order_and_bounded_filtered_scan(self):
        req=self.request({'limit':'20'})
        page=paginate_queryset(req,PersonalList.objects.filter(user=self.user),'lists',ordering='name')
        self.assertEqual([r.name for r in page['items']],[f'List {n:03}' for n in range(20)])
        page2=paginate_queryset(self.request({'limit':'20','cursor':page['next_cursor']}),PersonalList.objects.filter(user=self.user),'lists',ordering='name')
        self.assertEqual(len(page2['items']),5)
        first=paginate_queryset(self.request({'limit':'20'}),SavedItem.objects.filter(user=self.user),'filtered',serialize=lambda row:None,scan_limit=100)
        self.assertEqual(first['items'],[]);self.assertTrue(first['has_more'])
        final=paginate_queryset(self.request({'limit':'20','cursor':first['next_cursor']}),SavedItem.objects.filter(user=self.user),'filtered',serialize=lambda row:str(row.id),scan_limit=100)
        self.assertEqual(len(final['items']),20);self.assertTrue(final['has_more'])
    def test_vault_sections_beyond20_and_default_summary_unchanged(self):
        value=vault_data(self.user,territory='IN',request=self.request({'section':'lists','limit':'20'}))
        self.assertEqual(value['continue'],[]);self.assertEqual(len(value['lists']),20)
        next_value=vault_data(self.user,territory='IN',request=self.request({'section':'lists','limit':'20','cursor':value['next_cursor']}))
        self.assertEqual(len(next_value['lists']),5);self.assertFalse(next_value['has_more'])
        summary=vault_data(self.user,territory='IN',request=self.request())
        self.assertNotIn('next_cursor',summary);self.assertLessEqual(len(summary['lists']),20)
    def test_saved_api_marks_territory_withdrawn_unavailable(self):
        from reader.views import saved_items
        request=self.request({'limit':'100'},territory='GB')
        with patch('library.services.catalog_card',side_effect=DomainError('rights_unavailable','Unavailable.',403)):
            response=saved_items(request)
        self.assertEqual(response.status_code,200)
        self.assertTrue(all(not row['available'] for row in json.loads(response.content)['items']))
        self.assertIn('no-store',response['Cache-Control'])
    def test_annotation_bad_revision_filter_returns422(self):
        from reader.views import annotations
        response=annotations(self.request({'edition_revision_id':'bad'}))
        self.assertEqual(response.status_code,422)

    def test_finished_section_pages_beyond20_with_trusted_territory(self):
        now=timezone.now()
        for edition in self.editions[:25]:
            revision=Revision.objects.create(edition=edition,title='Original paging fixture',state='live',published_at=now)
            edition.live_revision=revision;edition.save()
            Completion.objects.create(user=self.user,edition=edition,revision=revision,format='reader',is_complete=True,completed_at=now)
        Completion.objects.all().update(updated_at=now)
        with patch('library.services.catalog_card',side_effect=lambda edition,**kw:{'edition_id':str(edition.id),'formats':['reader']}) as cards:
            first=vault_data(self.user,territory='GB',request=self.request({'section':'finished','limit':'20'},territory='GB'))
            second=vault_data(self.user,territory='GB',request=self.request({'section':'finished','limit':'20','cursor':first['next_cursor']},territory='GB'))
        self.assertEqual(len(first['finished']),20);self.assertEqual(len(second['finished']),5)
        self.assertFalse(second['has_more']);self.assertTrue(all(call.kwargs['territory']=='GB' for call in cards.call_args_list))
        self.assertEqual(len({row['card']['edition_id'] for row in first['finished']+second['finished']}),25)

    def test_summary_scan_is_bounded_and_explicit_section_reaches_later_items(self):
        now=timezone.now()
        for edition in self.editions[:26]:
            revision=Revision.objects.create(edition=edition,title='Original summary fixture',state='live',published_at=now)
            edition.live_revision=revision;edition.save()
            Completion.objects.create(user=self.user,edition=edition,revision=revision,format='reader',is_complete=True,completed_at=now)
        rows=list(Completion.objects.filter(user=self.user).order_by('-updated_at','-id'))
        target=rows[-1].edition_id
        def card(edition,**kwargs):
            if edition.id!=target:raise DomainError('rights_unavailable','Unavailable.',403)
            return {'edition_id':str(edition.id),'formats':['reader']}
        with patch('reader.services.VAULT_SUMMARY_SCAN_LIMIT',25),patch('library.services.catalog_card',side_effect=card) as cards:
            summary=vault_data(self.user,territory='GB',request=self.request(territory='GB'))
            self.assertEqual(summary['finished'],[])
            self.assertEqual(cards.call_count,25)
            explicit=vault_data(self.user,territory='GB',request=self.request({'section':'finished'},territory='GB'))
            self.assertEqual([x['card']['edition_id'] for x in explicit['finished']],[str(target)])

    def test_private_staff_draft_completion_survives_vault_without_customer_exposure(self):
        from django.contrib.auth.models import Permission
        from library.models import Rights
        self.user.is_staff=True;self.user.save(update_fields=['is_staff'])
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='library',codename='publish_revision'))
        edition=self.editions[0]
        revision=Revision.objects.create(edition=edition,title='Private original draft',content_sha256='a'*64)
        now=timezone.now()
        Rights.objects.create(revision=revision,format='reader',action='read',territories=['IN'],starts_at=now-timedelta(days=1),ends_at=now+timedelta(days=1),approved=True,test_only=True)
        for user in (self.user,self.other):
            Completion.objects.create(user=user,edition=edition,revision=revision,format='reader',is_complete=True,completed_at=now)
        staff=vault_data(self.user,territory='IN',request=self.request({'section':'finished'}))
        self.assertEqual([row['card']['edition_id'] for row in staff['finished']],[str(edition.id)])
        ordinary=vault_data(self.other,territory='IN',request=self.request({'section':'finished'},user=self.other))
        self.assertEqual(ordinary['finished'],[])
        foreign=vault_data(self.user,territory='GB',request=self.request({'section':'finished'},territory='GB'))
        self.assertEqual(foreign['finished'],[])
        edition.refresh_from_db();self.assertIsNone(edition.live_revision_id)
        revision.refresh_from_db();self.assertEqual(revision.state,'draft')
