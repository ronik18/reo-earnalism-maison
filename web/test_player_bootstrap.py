"""The player page hands the client what the lock screen needs: author and cover."""
from django.test import TestCase
from django.utils import timezone
from library import test_media_providers as fixtures


class PlayerBootstrapTests(TestCase):
    def setUp(self):
        fixtures.MeasuredAudioTests.setUp(self)
        self.revision.state = 'live'; self.revision.published_at = timezone.now(); self.revision.save()
        self.revision.edition.live_revision = self.revision; self.revision.edition.save()
        self.client.post('/en/sign-in/', {'email': self.user.email, 'password': 'Test-Only-Password-47', 'password_purpose_consent': 'on', 'password_purpose_version': 'password-account-v1'})

    def boot(self):
        response = self.client.get(f'/en/listen/{self.revision.edition_id}/')
        self.assertEqual(response.status_code, 200)
        return response.context['bootstrap']

    def test_player_bootstrap_carries_author_from_work_creators(self):
        work = self.revision.edition.work
        work.creators = ['First Author', 'Second Author']; work.save()
        self.assertEqual(self.boot()['author'], 'First Author, Second Author')

    def test_player_bootstrap_omits_author_without_creators(self):
        work = self.revision.edition.work
        work.creators = []; work.save()
        self.assertNotIn('author', self.boot())

    def test_cover_dimensions_travel_with_cover_url(self):
        boot = self.boot()
        if 'cover_url' in boot:
            self.assertGreater(boot['cover_width'], 0)
            self.assertGreater(boot['cover_height'], 0)


class PlayerFocusStyleTests(TestCase):
    def test_player_controls_get_the_gold_ring_on_the_dark_focused_surface(self):
        from pathlib import Path
        from django.conf import settings
        css = (Path(settings.BASE_DIR) / 'static/maison/room/room.css').read_text()
        self.assertIn('.room-focused .player-panel :focus-visible{outline-color:var(--gold-on-dark)}', css)
        self.assertIn('.icon-button svg{width:24px;height:24px}', css)
