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

 def test_question_page_shows_escaped_sponsor_line(self):
  approver=get_user_model().objects.create_user('ssr-sponsor-approver@example.test','Original-Paging-Fixture-48',is_verified=True)
  t=Track.objects.create(title='Original sponsored interview',locale='en',kind='sde_interview',access='free',published=True,sponsor_name='Acme <b>Labs</b>',sponsor_url='https://sponsor.example.test/',sponsor_approved_by=approver)
  q=InterviewQuestion.objects.create(id=uuid.UUID(int=30),track=t,topic='queues',difficulty='foundation',prompt='Original sponsored prompt',model_answer='Original answer',rubric=[])
  html=views.question(self.request('/en/question/'),locale='en',track_id=t.id,question_id=q.id).content.decode()
  self.assertIn('<p class="fine">Sponsored by <a href="https://sponsor.example.test/" rel="sponsored noopener"',html);self.assertIn('Acme &lt;b&gt;Labs&lt;/b&gt;',html);self.assertNotIn('<b>Labs</b>',html)
  t.sponsor_name='';t.sponsor_url='';t.sponsor_approved_by=None;t.save()
  self.assertNotIn('rel="sponsored',views.question(self.request('/en/question/'),locale='en',track_id=t.id,question_id=q.id).content.decode())


@override_settings(FREE_ACCESS_ENABLED=True)
class SignedOutTrackTests(TestCase):
 """During free access a track needs an account: a signed-out visitor is sent to sign in and back."""
 def test_signed_out_track_redirects_to_sign_in_with_return(self):
  t=Track.objects.create(title='Original signed-out track',locale='en',kind='learning',access='free',published=True)
  response=self.client.get(f'/en/tracks/{t.id}/')
  self.assertEqual(response.status_code,302)
  self.assertTrue(response['Location'].startswith('/en/sign-in/?return_to='))
  self.assertIn(f'%2Fen%2Ftracks%2F{t.id}%2F',response['Location'])

 def test_signed_out_post_still_gets_the_error_page(self):
  from django.test import RequestFactory
  from django.contrib.auth.models import AnonymousUser
  from core.api import DomainError
  def boom(request,locale,**kw): raise DomainError('authentication_required','Sign in to continue.',401)
  r=RequestFactory().post('/en/x/');r.user=AnonymousUser()
  self.assertEqual(views.domain_view(boom)(r,'en').status_code,401)
