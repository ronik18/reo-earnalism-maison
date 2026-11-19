"""Learning list APIs stay bounded and preserve position across earlier inserts."""
import uuid
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase,RequestFactory,override_settings
from django.test.utils import CaptureQueriesContext
from core.api import DomainError
from .models import Track,InterviewQuestion
from . import services


@override_settings(LOCAL=True,FREE_ACCESS_ENABLED=True)
class LearningKeysetTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('original-learning-page@example.test','Original-Learning-Page-47',is_verified=True)
        self.user.request_territory='IN'
        self.other=get_user_model().objects.create_user('original-learning-other@example.test','Original-Learning-Page-47',is_verified=True)
        self.other.request_territory='IN'
        self.factory=RequestFactory()

    def request(self,user=None,**params):
        request=self.factory.get('/api/v1/learning/tracks',params)
        request.user=user or self.user;request.territory='IN'
        return request

    def track(self,index,**extra):
        return Track.objects.create(id=uuid.UUID(int=index),title='Original shared title',locale='en',kind='learning',description='Original bounded fixture',access='free',published=True,**extra)

    def test_track_keyset_has_no_duplicates_after_earlier_insert_and_binds_context(self):
        rows=[self.track(index) for index in (10,20,30)]
        first=services.tracks_page(self.request(limit=2),self.user)
        self.assertEqual([x['track_id'] for x in first['items']],[str(x.pk) for x in rows[:2]])
        self.track(5)
        second=services.tracks_page(self.request(limit=2,cursor=first['next_cursor']),self.user)
        self.assertEqual([x['track_id'] for x in second['items']],[str(rows[2].pk)])
        self.assertFalse(second['has_more']);self.assertIsNone(second['next_cursor'])
        for user,locale,kind,territory in [(self.other,'en','','IN'),(self.user,'bn','','IN'),(self.user,'en','sde_interview','IN'),(self.user,'en','','US')]:
            with self.subTest(locale=locale,kind=kind,territory=territory,user=user.pk):
                request=self.request(user,limit=2,cursor=first['next_cursor']);request.territory=territory
                with self.assertRaises(DomainError) as error:services.tracks_page(request,user,locale,kind)
                self.assertEqual(error.exception.code,'invalid_cursor')

    def test_track_page_honors_kind_and_sql_limit_before_dto(self):
        Track.objects.bulk_create([Track(title=f'Original bounded {i:03}',locale='en',kind='learning',description='Original',access='free',published=True) for i in range(110)])
        interview=Track.objects.create(title='Original interview',locale='en',kind='sde_interview',description='Original',access='free',published=True)
        with CaptureQueriesContext(connection) as queries:
            page=services.tracks_page(self.request(limit=2,kind='learning'),self.user,kind='learning')
        self.assertEqual(len(page['items']),2);self.assertTrue(page['has_more'])
        selects=[q['sql'] for q in queries if 'FROM "maison_track"' in q['sql']]
        self.assertEqual(len(selects),1);self.assertIn('LIMIT 3',selects[0])
        selected=services.tracks_page(self.request(kind='sde_interview'),self.user,kind='sde_interview')
        self.assertEqual([x['track_id'] for x in selected['items']],[str(interview.pk)])
        with self.assertRaises(DomainError):services.tracks_page(self.request(),self.user,kind='unknown')
        self.user.request_territory='AE'
        self.assertEqual(services.tracks_page(self.request(),self.user)['items'],[])

    def test_question_keyset_binds_filters_actor_and_track_and_skips_earlier_insert(self):
        track=self.track(100)
        def question(index,topic='queues'):
            return InterviewQuestion.objects.create(id=uuid.UUID(int=index),track=track,topic=topic,difficulty='foundation',company_style='Original pack',prompt='Original queue invariant',model_answer='Original reviewed answer',rubric=[])
        rows=[question(index) for index in (10,20,30)]
        filters={'topic':'queues','difficulty':'foundation','company_style':'Original pack'}
        first=services.interview_questions_page(self.request(limit=2,**filters),self.user,track.pk,**filters)
        question(5)
        second=services.interview_questions_page(self.request(limit=2,cursor=first['next_cursor'],**filters),self.user,track.pk,**filters)
        self.assertEqual([x['question_id'] for x in first['items']+second['items']],[str(x.pk) for x in rows])
        self.assertFalse(second['has_more'])
        for user,changed in [(self.user,{**filters,'topic':'trees'}),(self.other,filters)]:
            with self.assertRaises(DomainError) as error:
                services.interview_questions_page(self.request(user,limit=2,cursor=first['next_cursor'],**changed),user,track.pk,**changed)
            self.assertEqual(error.exception.code,'invalid_cursor')
        other=self.track(200)
        with self.assertRaises(DomainError):services.interview_questions_page(self.request(limit=2,cursor=first['next_cursor'],**filters),self.user,other.pk,**filters)
        track.published=False;track.save()
        with self.assertRaises(DomainError) as error:services.interview_questions_page(self.request(),self.user,track.pk)
        self.assertEqual(error.exception.status,404)

    def test_http_tracks_preserves_page_shape_kind_filter_and_private_cache(self):
        self.track(10)
        Track.objects.create(title='Original SDE only',locale='en',kind='sde_interview',description='Original',access='free',published=True)
        self.assertEqual(self.client.post('/api/v1/auth/login',{'email':self.user.email,'password':'Original-Learning-Page-47'},content_type='application/json').status_code,200)
        response=self.client.get('/api/v1/learning/tracks',{'locale':'en','kind':'sde_interview','limit':1})
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(set(response.json()),{'items','next_cursor','has_more'})
        self.assertEqual(response.json()['items'][0]['kind'],'sde_interview')
        self.assertIn('no-store',response['Cache-Control'])


    def test_single_question_uses_exact_track_identity_and_rechecks_authority(self):
        track=self.track(10);other=self.track(20)
        row=InterviewQuestion.objects.create(track=track,topic='queues',difficulty='foundation',prompt='Original prompt',model_answer='Original answer',rubric=[])
        with CaptureQueriesContext(connection) as queries:
            result=services.interview_question(self.user,track.pk,row.pk)
        self.assertEqual(result['question_id'],str(row.pk))
        selects=[q['sql'] for q in queries if 'FROM "maison_interview_question"' in q['sql']]
        self.assertEqual(len(selects),1);self.assertIn('LIMIT 1',selects[0])
        for track_id,question_id in [(other.pk,row.pk),(track.pk,uuid.uuid4()),(track.pk,'invalid')]:
            with self.assertRaises(DomainError) as error:services.interview_question(self.user,track_id,question_id)
            self.assertEqual(error.exception.status,404)
        self.user.request_territory='AE'
        with self.assertRaises(DomainError) as error:services.interview_question(self.user,track.pk,row.pk)
        self.assertEqual(error.exception.code,'region_unavailable')
