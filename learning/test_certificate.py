"""Completion certificates: earned only by finishing every lesson; public by link; owner-controlled."""
import json
import tempfile
import time
import uuid

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from core.api import DomainError
from . import services
from .models import Certificate, Lesson, Quiz, QuizAttempt, Track

PASSWORD = 'Certificate-Passphrase-2026'


@override_settings(FREE_ACCESS_ENABLED=True)
class CertificateTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('learner@example.test', PASSWORD, is_verified=True, display_name='Asha')
        self.user.request_territory = 'IN'
        self.track = Track.objects.create(title='Reading বিচারক', locale='bn', description='Fixture', access='free', published=True)
        self.lessons = [Lesson.objects.create(track=self.track, title=f'Lesson {n}', ordinal=n) for n in (1, 2)]

    def sign_in(self, user):
        """The real sign-in form, so the member session carries its device binding."""
        self.client.logout()
        self.client.get('/en/sign-in/')
        return self.client.post('/en/sign-in/', {'email': user.email, 'password': PASSWORD, 'return_to': '/en/learn/',
                                                 'password_purpose_consent': 'on', 'password_purpose_version': 'password-account-v1'})

    def finish(self, lessons=None):
        for lesson in lessons or self.lessons:
            services.complete_lesson(self.user, lesson.pk)

    def test_unfinished_track_cannot_issue_and_finished_track_issues_once(self):
        self.finish(self.lessons[:1])
        self.assertFalse(services.track_detail(self.user, self.track.pk)['certificate']['eligible'])
        with self.assertRaises(DomainError) as caught:
            services.issue_certificate(self.user, self.track.pk, 'Asha')
        self.assertEqual(caught.exception.code, 'completion_rule_unmet')
        self.finish(self.lessons[1:])
        self.assertTrue(services.track_detail(self.user, self.track.pk)['certificate']['eligible'])
        first = services.issue_certificate(self.user, self.track.pk, '  Asha   Roy ')
        self.assertEqual((first.display_name, first.lessons_completed), ('Asha Roy', 2))
        self.assertEqual(services.issue_certificate(self.user, self.track.pk, 'Other'), first)
        self.assertEqual(services.track_detail(self.user, self.track.pk)['certificate']['certificate_id'], str(first.pk))

    def test_quiz_lessons_must_be_passed_at_the_current_version(self):
        quiz_lesson = Lesson.objects.create(track=self.track, title='Quiz', ordinal=3, completion_rule='quiz_pass', pass_score=80)
        quiz = Quiz.objects.create(lesson=quiz_lesson)
        self.finish()
        QuizAttempt.objects.create(user=self.user, quiz=quiz, quiz_version=quiz.version, status='submitted', score=90, submitted_at=timezone.now())
        services.complete_lesson(self.user, quiz_lesson.pk)
        Quiz.objects.filter(pk=quiz.pk).update(version=quiz.version + 1)  # the quiz changed after it was passed
        with self.assertRaises(DomainError):
            services.issue_certificate(self.user, self.track.pk, 'Asha')

    def test_names_are_bounded_and_guardian_managed_accounts_get_none(self):
        self.finish()
        for bad in ('', '   ', 'x' * 101, 'Asha\x00Roy'):
            with self.subTest(bad=bad), self.assertRaises(DomainError):
                services.issue_certificate(self.user, self.track.pk, bad)
        self.user.guardian_managed = True
        self.assertFalse(services.track_detail(self.user, self.track.pk)['certificate']['eligible'])
        with self.assertRaises(DomainError) as caught:
            services.issue_certificate(self.user, self.track.pk, 'Asha')
        self.assertEqual(caught.exception.code, 'certificate_unavailable')

    def test_database_enforces_one_named_certificate_per_track(self):
        Certificate.objects.create(user=self.user, track=self.track, display_name='Asha', lessons_completed=2)
        for row in ({'display_name': 'Again', 'lessons_completed': 2},):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Certificate.objects.create(user=self.user, track=self.track, **row)
        other = get_user_model().objects.create_user('other@example.test', PASSWORD)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Certificate.objects.create(user=other, track=self.track, display_name='', lessons_completed=2)

    def test_public_page_owner_withdrawal_and_html_escaping(self):
        self.finish()
        self.sign_in(self.user)
        page = self.client.get(f'/en/tracks/{self.track.pk}/')
        self.assertContains(page, f'action="/en/tracks/{self.track.pk}/certificate/"')
        self.assertContains(page, 'value="Asha"')
        response = self.client.post(f'/en/tracks/{self.track.pk}/certificate/', {'display_name': '<b>Asha</b>'})
        cert = Certificate.objects.get()
        self.assertRedirects(response, f'/en/certificates/{cert.pk}/', fetch_redirect_response=False)
        mine = self.client.get(f'/en/certificates/{cert.pk}/')
        self.assertContains(mine, '&lt;b&gt;Asha&lt;/b&gt;')
        self.assertContains(mine, f'action="/en/certificates/{cert.pk}/withdraw/"')
        self.assertNotContains(mine, 'learner@example.test')
        public = Client().get(f'/en/certificates/{cert.pk}/')  # a visitor with no account
        self.assertContains(public, 'Certificate of completion')
        self.assertContains(public, 'Reading বিচারক')
        self.assertNotContains(public, f'action="/en/certificates/{cert.pk}/withdraw/"')
        self.assertEqual(self.client.get(f'/en/certificates/{uuid.uuid4()}/').status_code, 404)
        stranger = get_user_model().objects.create_user('stranger@example.test', PASSWORD, is_verified=True)
        self.sign_in(stranger)
        self.client.post(f'/en/certificates/{cert.pk}/withdraw/')
        self.assertTrue(Certificate.objects.filter(pk=cert.pk).exists())
        self.sign_in(self.user)
        self.client.post(f'/en/certificates/{cert.pk}/withdraw/')
        self.assertFalse(Certificate.objects.exists())

    def test_export_includes_and_account_deletion_removes_certificates(self):
        from accounts.privacy import _write_export, delete_account
        from core.models import OutboxJob
        self.finish()
        cert = services.issue_certificate(self.user, self.track.pk, 'Asha')
        with tempfile.TemporaryFile() as handle:
            _write_export(self.user, handle, time.monotonic() + 30)
            exported = json.loads(handle.read())
        self.assertEqual([row['display_name'] for row in exported['certificates']], ['Asha'])
        job = OutboxJob.objects.create(kind='privacy_delete', actor=self.user, dedupe_key=uuid.uuid4().hex, payload={}, not_before=timezone.now())
        delete_account(job)
        self.assertFalse(Certificate.objects.filter(pk=cert.pk).exists())
