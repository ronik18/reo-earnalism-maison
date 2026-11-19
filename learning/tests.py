import io
import tempfile
import uuid
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase,override_settings
from core.api import DomainError
from core.services import apply_operation
from library.validation import validate_schema
from .models import Track,Quiz,QuestionOption,LessonCompletion
from . import services as svc

class LearningAcceptanceTests(TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.override=override_settings(MEDIA_ROOT=self.directory.name,MAISON_LOCAL_FIXTURES=True,LOCAL=True);self.override.enable();self.addCleanup(self.override.disable)
        call_command('seed_local_pilot',stdout=io.StringIO())
        self.user=get_user_model().objects.create_user('learner@example.test','Local-Learner-Strong47',is_verified=True)
        self.other=get_user_model().objects.create_user('other@example.test','Local-Other-Strong47',is_verified=True)
        self.quiz=Quiz.objects.first();self.track=self.quiz.lesson.track

    def test_sde_questions_answers_and_rubrics_are_real_p0_detail(self):
        data=svc.interview_questions(self.user,self.track.id)
        self.assertEqual(len(data),1);validate_schema(data[0],'InterviewQuestion')
        self.assertIn('circular buffer',data[0]['model_answer']);self.assertEqual(len(data[0]['rubric']),3)
        self.assertEqual(svc.interview_questions(self.user,self.track.id,topic='unknown'),[])

    def test_quiz_dto_has_no_answer_key_or_explanation_before_submit(self):
        public=svc.quiz_public(self.user,self.quiz.id);validate_schema(public,'Quiz')
        self.assertEqual(set(public['questions'][0]['options'][0]),{'option_id','text'})
        raw=str(public);self.assertNotIn('is_correct',raw);self.assertNotIn('explanation',raw);self.assertNotIn('correct_option_id',raw)
        attempt=svc.start_attempt(self.user,self.quiz.id,self.quiz.version);dto=svc.attempt_dto(attempt);validate_schema(dto,'QuizAttempt')
        self.assertIsNone(dto['score']);self.assertIsNone(dto['result']);self.assertNotIn('scoring_snapshot',dto)

    def test_server_grades_attempt_snapshot_and_ignores_later_key_changes(self):
        attempt=svc.start_attempt(self.user,self.quiz.id,self.quiz.version)
        q=attempt.scoring_snapshot[0];correct=q['correct_option_id']
        QuestionOption.objects.filter(pk=correct).update(is_correct=False)
        other=QuestionOption.objects.filter(question_id=q['question_id']).exclude(pk=correct).first();other.is_correct=True;other.save()
        result=svc.submit_attempt(self.user,attempt.id,[{'question_id':q['question_id'],'option_id':correct}],1)
        self.assertEqual(result.score,100);self.assertTrue(result.result[0]['correct']);validate_schema(svc.attempt_dto(result),'QuizAttempt')

    def test_attempt_ownership_bad_options_stale_version_and_duplicate_submission(self):
        attempt=svc.start_attempt(self.user,self.quiz.id,self.quiz.version);q=attempt.scoring_snapshot[0]
        with self.assertRaises(DomainError): svc.own_attempt(self.other,attempt.id)
        with self.assertRaises(DomainError): svc.submit_attempt(self.user,attempt.id,[{'question_id':q['question_id'],'option_id':str(uuid.uuid4())}],1)
        with self.assertRaises(DomainError) as err: svc.submit_attempt(self.user,attempt.id,[{'question_id':q['question_id'],'option_id':q['correct_option_id']}],2)
        self.assertEqual(err.exception.status,412)
        submitted=svc.submit_attempt(self.user,attempt.id,[{'question_id':q['question_id'],'option_id':q['correct_option_id']}],1)
        with self.assertRaises(DomainError): svc.submit_attempt(self.user,attempt.id,submitted.answers,submitted.version)

    def test_idempotent_start_and_submit_are_durable_receipts(self):
        operation=uuid.uuid4();payload={'quiz_id':str(self.quiz.id),'quiz_version':self.quiz.version}
        def start():
            attempt=svc.start_attempt(self.user,self.quiz.id,self.quiz.version)
            return 201,svc.attempt_dto(attempt),attempt.version
        first=apply_operation(self.user,operation,'quiz.start',payload,start)
        self.assertEqual(apply_operation(self.user,operation,'quiz.start',payload,start),first)
        self.assertEqual(self.quiz.attempts.count(),1)
        with self.assertRaises(DomainError): apply_operation(self.user,operation,'quiz.start',{**payload,'quiz_version':2},start)

    def test_free_deny_paid_and_completion_isolation(self):
        detail=svc.lesson_detail(self.user,self.quiz.lesson_id);validate_schema(detail,'Lesson')
        self.assertFalse(detail['completed'])
        svc.complete_lesson(self.user,self.quiz.lesson_id);svc.complete_lesson(self.user,self.quiz.lesson_id)
        self.assertEqual(LessonCompletion.objects.filter(user=self.user).count(),1)
        self.assertFalse(svc.lesson_detail(self.other,self.quiz.lesson_id)['completed'])
        self.track.access='paid';self.track.save()
        with self.assertRaises(DomainError): svc.lesson_detail(self.user,self.quiz.lesson_id)
        self.track.access='deny';self.track.save()
        with self.assertRaises(DomainError): svc.quiz_public(self.user,self.quiz.id)

    def test_configured_prerequisite_and_current_quiz_completion_are_enforced(self):
        from .models import Lesson
        first=self.quiz.lesson;first.completion_rule='quiz_pass';first.pass_score=100;first.save()
        later=Lesson.objects.create(track=self.track,title='Next lesson',ordinal=first.ordinal+100,requires_previous=True)
        with self.assertRaises(DomainError) as error:svc.lesson_detail(self.user,later.id)
        self.assertEqual(error.exception.code,'prerequisite_unmet')
        with self.assertRaises(DomainError) as error:svc.complete_lesson(self.user,first.id)
        self.assertEqual(error.exception.code,'completion_rule_unmet')
        attempt=svc.start_attempt(self.user,self.quiz.id,self.quiz.version)
        answers=[{'question_id':q['question_id'],'option_id':q['correct_option_id']} for q in attempt.scoring_snapshot]
        svc.submit_attempt(self.user,attempt.id,answers,1)
        svc.complete_lesson(self.user,first.id)
        self.assertEqual(svc.lesson_detail(self.user,later.id)['lesson_id'],str(later.id))
        # A changed key requires the current revision's quiz rather than silently carrying mastery.
        self.quiz.version+=1;self.quiz.save()
        with self.assertRaises(DomainError):svc.complete_lesson(self.other,first.id)


    def test_changed_quiz_requires_explicit_current_completion_and_allows_revision_restart(self):
        from .models import Lesson
        first=self.quiz.lesson;first.completion_rule='quiz_pass';first.save()
        self.quiz.max_attempts=1;self.quiz.save()
        later=Lesson.objects.create(track=self.track,title='Next revision-bound lesson',ordinal=first.ordinal+10,requires_previous=True)
        def pass_current():
            quiz=Quiz.objects.get(pk=self.quiz.pk)
            attempt=svc.start_attempt(self.user,quiz.id,quiz.version)
            svc.submit_attempt(self.user,attempt.id,[{'question_id':q['question_id'],'option_id':q['correct_option_id']} for q in attempt.scoring_snapshot],1)
        pass_current();svc.complete_lesson(self.user,first.id)
        self.assertTrue(svc.lesson_detail(self.user,first.id)['completed'])
        self.assertEqual(svc.lesson_detail(self.user,later.id)['lesson_id'],str(later.id))
        self.quiz.refresh_from_db();self.quiz.version+=1;self.quiz.save()
        self.assertFalse(svc.lesson_detail(self.user,first.id)['completed'])
        with self.assertRaises(DomainError) as error:svc.lesson_detail(self.user,later.id)
        self.assertEqual(error.exception.code,'prerequisite_unmet')
        pass_current()
        self.assertFalse(svc.lesson_detail(self.user,first.id)['completed'])
        svc.complete_lesson(self.user,first.id)
        self.assertTrue(svc.lesson_detail(self.user,first.id)['completed'])
        self.assertEqual(LessonCompletion.objects.filter(user=self.user,lesson=first).count(),1)

    def test_lesson_media_cannot_silently_use_another_track_edition(self):
        from library.models import Edition
        lesson=self.quiz.lesson
        edition=Edition.objects.get(pk='20000000-0000-4000-8000-000000000002')
        self.track.edition=Edition.objects.get(pk='20000000-0000-4000-8000-000000000001');self.track.save()
        lesson.unit=edition.live_revision.units.first();lesson.save()
        with self.assertRaises(DomainError) as error:svc.lesson_detail(self.user,lesson.id)
        self.assertEqual(error.exception.code,'lesson_not_ready')
