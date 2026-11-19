"""SSR learning lists preserve bounded cursors and exact question lookup."""
import uuid
from django.contrib.auth import get_user_model
from django.test import TestCase,RequestFactory,override_settings
from learning.models import Track,InterviewQuestion
from web import views

@override_settings(FREE_ACCESS_ENABLED=True)
class LearningPageNavigationTests(TestCase):
 def setUp(self):
  self.user=get_user_model().objects.create_user('ssr-page-original@example.test','Original-Paging-Fixture-47',is_verified=True)
  self.user.request_territory='IN';self.factory=RequestFactory()
 def request(self,path):
  r=self.factory.get(path);r.user=self.user;r.territory='IN';return r
 def test_learn_and_interview_reach_later_tracks(self):
  for kind,view,path in [('learning',views.learn,'/en/learn/'),('sde_interview',views.interview,'/en/interview/')]:
   rows=[Track.objects.create(id=uuid.uuid4(),title=f'Original {kind} {i}',locale='en',kind=kind,access='free',published=True) for i in range(2)]
   response=view(self.request(path+'?limit=1'),'en');html=response.content.decode()
   self.assertIn(rows[0].title,html);self.assertNotIn(rows[1].title,html);self.assertIn('cursor=',html)
   import re,html as h
   target=h.unescape(re.search(r'href="([^\"]*cursor=[^\"]*)"',html)[1])
   later=view(self.request(target),'en').content.decode();self.assertIn(rows[1].title,later);self.assertNotIn(rows[0].title,later)
 def test_track_questions_reach_next_page_and_exact_detail(self):
  t=Track.objects.create(title='Original interview',locale='en',kind='sde_interview',access='free',published=True)
  rows=[InterviewQuestion.objects.create(id=uuid.UUID(int=i),track=t,topic='queues',difficulty='foundation',prompt=f'Original prompt {i}',model_answer='Original answer',rubric=[]) for i in [10,20]]
  response=views.track(self.request(f'/en/learn/{t.id}/?limit=1'),locale='en',track_id=t.id);html=response.content.decode()
  self.assertIn(rows[0].prompt,html);self.assertNotIn(rows[1].prompt,html);self.assertIn('cursor=',html)
  response=views.question(self.request('/en/question/'),locale='en',track_id=t.id,question_id=rows[1].id)
  self.assertEqual(response.status_code,200);self.assertIn(rows[1].prompt,response.content.decode())
