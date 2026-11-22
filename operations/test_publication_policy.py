"""Owner amendment 22 Nov 2026: active publication = the nine launch territories."""
import json
from django.conf import settings
from django.test import SimpleTestCase

LAUNCH = ('IN', 'US', 'GB', 'BR', 'SG', 'MY', 'ID', 'PH', 'TH')


class PublicationPolicyTests(SimpleTestCase):
    def policy(self):
        return json.loads((settings.BASE_DIR / 'contracts/publication-policy.json').read_text())

    def test_whitelist_is_the_nine_launch_territories(self):
        self.assertEqual(set(settings.MAISON_PUBLICATION_TERRITORIES), set(LAUNCH))

    def test_deferred_regions_are_not_publication_territories(self):
        deferred = set(self.policy()['deferred'])
        self.assertEqual(len(deferred), 38)
        self.assertFalse(deferred & set(settings.MAISON_PUBLICATION_TERRITORIES))

    def test_deferred_and_whitelist_are_disjoint_from_excluded(self):
        p = self.policy()
        self.assertFalse((set(p['deferred']) | set(p['whitelist'])) & (set(p['out_of_scope']) | set(p['excluded_pending'])))
