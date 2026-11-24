"""Classroom licence pilot: teacher-only projection, usage counting, worksheets, audited role."""
import io
from unittest import mock
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from core.api import DomainError
from core.models import AuditEvent
from reader.test_journey import make_book
from . import classroom, worksheet
from .models import ClassroomSession, Lesson, Question, QuestionOption, Quiz, Track

PASSWORD = 'Classroom-Passphrase-2026'


def quiz_track(locale='en'):
    track = Track.objects.create(title='Reading together' if locale == 'en' else 'একসঙ্গে পড়া', locale=locale,
                                 description='Fixture', access='free', published=True)
    lesson = Lesson.objects.create(track=track, title='The garden' if locale == 'en' else 'বাগান', ordinal=1,
                                   completion_rule='quiz_pass', pass_score=50)
    quiz = Quiz.objects.create(lesson=lesson)
    question = Question.objects.create(quiz=quiz, ordinal=1, explanation='The giant was away.' if locale == 'en' else 'দৈত্য দূরে ছিল।',
                                       prompt='Who played in the garden?' if locale == 'en' else 'বাগানে কারা খেলত?')
    for text, correct in (('The children', True), ('The giant', False)) if locale == 'en' else (('শিশুরা', True), ('দৈত্য', False)):
        QuestionOption.objects.create(question=question, text=text, is_correct=correct)
    return track


@override_settings(FREE_ACCESS_ENABLED=True)
class ClassroomTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user('staff@example.test', PASSWORD, is_staff=True, is_verified=True)
        self.teacher = User.objects.create_user('teacher@example.test', PASSWORD, is_verified=True)
        self.reader = User.objects.create_user('reader@example.test', PASSWORD, is_verified=True)
        self.edition, self.revision = make_book(units=2, paragraphs=3)
        self.units = list(self.revision.units.order_by('ordinal'))

    def grant(self, email='teacher@example.test'):
        call_command('classroom_teacher', 'grant', email, '--by', 'staff@example.test', '--reason', 'Pilot agreement P-01', stdout=io.StringIO())

    def sign_in(self, user):
        self.client.get('/en/sign-in/')
        self.client.post('/en/sign-in/', {'email': user.email, 'password': PASSWORD, 'return_to': '/en/learn/',
                                          'password_purpose_consent': 'on', 'password_purpose_version': 'password-account-v1'})

    def classroom_url(self, unit=0):
        return f'/en/classroom/{self.edition.pk}/{self.units[unit].pk}/'

    def test_role_is_granted_by_staff_with_an_audit_and_never_to_unverified_accounts(self):
        unverified = get_user_model().objects.create_user('new@example.test', PASSWORD)
        with self.assertRaises(CommandError):
            self.grant('new@example.test')
        with self.assertRaises(CommandError):
            call_command('classroom_teacher', 'grant', 'teacher@example.test', '--by', 'reader@example.test', '--reason', 'x')
        self.grant()
        self.teacher = get_user_model().objects.get(pk=self.teacher.pk)
        self.assertTrue(classroom.is_teacher(self.teacher))
        self.assertFalse(classroom.is_teacher(unverified))
        self.assertTrue(AuditEvent.objects.filter(action='classroom.teacher_grant', entity_id=str(self.teacher.pk), actor=self.staff).exists())
        call_command('classroom_teacher', 'revoke', 'teacher@example.test', '--by', 'staff@example.test', '--reason', 'Pilot ended', stdout=io.StringIO())
        self.assertFalse(classroom.is_teacher(get_user_model().objects.get(pk=self.teacher.pk)))

    def test_projection_is_teacher_only_and_follows_reader_rights(self):
        self.sign_in(self.reader)
        self.assertEqual(self.client.get(self.classroom_url()).status_code, 403)
        self.grant()
        self.sign_in(self.teacher)
        page = self.client.get(self.classroom_url())
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'data-step', count=3)
        self.assertContains(page, 'id="classroom-next"')
        self.assertContains(page, 'type="module"')
        self.assertContains(page, f'/en/classroom/{self.edition.pk}/{self.units[1].pk}/')  # next chapter
        teacher = get_user_model().objects.get(pk=self.teacher.pk)
        with self.assertRaises(DomainError) as caught:
            classroom.open_classroom(teacher, self.edition.pk, self.units[0].pk, 'GB')  # rights are IN only
        self.assertIn(caught.exception.code, {'rights_unavailable', 'content_unavailable'})
        self.assertEqual(ClassroomSession.objects.filter(teacher=teacher).count(), 1)  # the denied open is not counted
        with mock.patch('library.services.get_reader_document', return_value={'edition': {'published_at': None}}):
            with self.assertRaises(DomainError) as caught:
                classroom.open_classroom(teacher, self.edition.pk, self.units[0].pk, 'IN')
        self.assertEqual(caught.exception.code, 'content_unavailable')  # drafts are never projected

    def test_sessions_count_once_per_half_hour_and_report_by_week(self):
        self.grant()
        teacher = get_user_model().objects.get(pk=self.teacher.pk)
        for _ in range(3):
            classroom.open_classroom(teacher, self.edition.pk, self.units[0].pk, 'IN')
        classroom.open_classroom(teacher, self.edition.pk, self.units[1].pk, 'IN')
        self.assertEqual(ClassroomSession.objects.count(), 2)
        ClassroomSession.objects.update(started_at=timezone.now() - timedelta(minutes=31))
        classroom.open_classroom(teacher, self.edition.pk, self.units[0].pk, 'IN')
        self.assertEqual(ClassroomSession.objects.count(), 3)
        out = io.StringIO()
        call_command('classroom_report', '--weeks', '2', stdout=out)
        self.assertIn('teacher@example.test\t3\t1', out.getvalue())

    def test_worksheets_are_teacher_only_and_render_in_both_languages(self):
        track = quiz_track('en')
        self.sign_in(self.reader)
        self.assertNotContains(self.client.get(f'/en/tracks/{track.pk}/'), '/worksheet.pdf')
        self.assertEqual(self.client.get(f'/en/tracks/{track.pk}/worksheet.pdf').status_code, 403)
        self.grant()
        self.sign_in(self.teacher)
        self.assertContains(self.client.get(f'/en/tracks/{track.pk}/'), f'/en/tracks/{track.pk}/worksheet.pdf?answers=1')
        response = self.client.get(f'/en/tracks/{track.pk}/worksheet.pdf')
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        bengali = quiz_track('bn')
        self.assertTrue(worksheet.render(bengali.pk, answers=True).startswith(b'%PDF'))
        _, lessons = worksheet.worksheet_content(track.pk)
        self.assertEqual(lessons[0]['questions'][0]['options'][lessons[0]['questions'][0]['correct'][0]], 'The children')

    def test_track_without_quiz_has_no_worksheet(self):
        track = Track.objects.create(title='Plain', locale='en', description='x', access='free', published=True)
        Lesson.objects.create(track=track, title='One', ordinal=1)
        with self.assertRaises(DomainError) as caught:
            worksheet.render(track.pk)
        self.assertEqual(caught.exception.code, 'worksheet_unavailable')

    def test_title_page_offers_classroom_mode_only_to_teachers(self):
        self.sign_in(self.reader)
        self.assertNotContains(self.client.get(f'/en/titles/{self.edition.pk}/'), '/en/classroom/')
        self.grant()
        self.sign_in(self.teacher)
        self.assertContains(self.client.get(f'/en/titles/{self.edition.pk}/'), self.classroom_url())
