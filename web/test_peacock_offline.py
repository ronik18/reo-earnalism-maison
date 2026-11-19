"""The offline shell must retain the active theme, not just its older base CSS."""
import hashlib
from pathlib import Path
from django.conf import settings
from django.test import SimpleTestCase,RequestFactory
from .views import service_worker

class PeacockOfflineShellTests(SimpleTestCase):
    def test_shell_precaches_the_actual_theme_styles_and_navigation_art(self):
        source=service_worker(RequestFactory().get('/service-worker.js')).content.decode()
        css=Path(settings.BASE_DIR)/'static/maison/peacock/maison-theme.css'
        self.assertIn('maison/peacock/maison-theme.css?v='+hashlib.sha256(css.read_bytes()).hexdigest()[:12],source)
        self.assertIn('maison/peacock/tokens.css',source)
        for name in ['peacock-crest.svg','alpana-halo.svg','jali-panel.svg','kantha-tile.svg']:
            self.assertIn('maison/peacock/svg/'+name,source)
        for name in ['house.svg','compass.svg','book-open.svg','stack.svg','archive.svg','gear.svg']:
            self.assertIn('maison/peacock/icons/'+name,source)
        self.assertNotIn('docs/design',source)
