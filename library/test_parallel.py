"""Revenue plan Step 3.2: a parallel bn/en pair is offered only when both editions are live,
readable by this member in this territory, structurally aligned, and (after the free rollout) the
member holds an active Pass. Anything else fails closed (None)."""
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, override_settings
from django.utils import timezone

from billing.models import Entitlement
from library.models import Edition, Paragraph, Revision, Rights, Unit, Work
from library.services import parallel_companion, prepare_reader_package

TEXT = {'bn': 'বাংলা অনুচ্ছেদ {u}.{p}', 'en': 'English paragraph {u}.{p}'}


def live_book(work, locale, units=1, kinds=('paragraph', 'paragraph', 'paragraph'), source=None,
              policy=None, method='ai', credit=''):
    edition = Edition.objects.create(work=work, slug=f'pair-{locale}-{uuid.uuid4().hex[:12]}', locale=locale,
                                     translated_from=source, translation_method=method if source else '',
                                     translation_credit=credit if source else '')
    policy = policy or {'reader': 'free'}
    revision = Revision.objects.create(edition=edition, title=f'Pair {locale}', access_policy=policy)
    for n in range(units):
        unit = Unit.objects.create(revision=revision, ordinal=n + 1, title=f'{locale} {n + 1}')
        rows = [Paragraph.objects.create(unit=unit, ordinal=i + 1, kind=kind, text=TEXT[locale].format(u=n + 1, p=i + 1))
                for i, kind in enumerate(kinds)]
        prepare_reader_package(unit, rows).save()
    now = timezone.now()
    Rights.objects.create(revision=revision, format='reader', action='read', territories=['IN'],
                          starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=30), approved=True)
    revision.state = 'live'; revision.published_at = now; revision.save()
    edition.live_revision = revision; edition.save()
    return edition


@override_settings(FREE_ACCESS_ENABLED=True)
class ParallelCompanionTests(TestCase):
    def setUp(self):
        self.work = Work.objects.create(slug='pair-' + uuid.uuid4().hex, title='Pair', house='golpo', creators=['A writer'])
        self.member = get_user_model().objects.create_user('pair@example.test', 'Pair-Reader-Passphrase-26', is_verified=True)

    def pair(self, bn_kwargs=None, en_kwargs=None):
        bn = live_book(self.work, 'bn', **(bn_kwargs or {}))
        en = live_book(self.work, 'en', source=bn, **(en_kwargs or {}))
        return bn, en

    def unit(self, edition, index=0):
        return str(edition.live_revision.units.all()[index].pk)

    def test_aligned_pair_is_offered_from_both_sides(self):
        bn, en = self.pair({'units': 2}, {'units': 2})
        from_original = parallel_companion(self.member, bn.pk, self.unit(bn, 1))
        self.assertEqual(from_original['edition']['edition_id'], str(en.pk))
        self.assertEqual(from_original['edition']['locale'], 'en')
        self.assertTrue(from_original['current_is_original'])
        self.assertEqual(from_original['translation'], {'method': 'ai', 'credit': ''})
        self.assertEqual([p['text'] for p in from_original['paragraphs']],
                         ['English paragraph 2.1', 'English paragraph 2.2', 'English paragraph 2.3'])
        from_translation = parallel_companion(self.member, en.pk, self.unit(en))
        self.assertEqual(from_translation['edition']['locale'], 'bn')
        self.assertFalse(from_translation['current_is_original'])
        self.assertEqual(from_translation['paragraphs'][0]['text'], 'বাংলা অনুচ্ছেদ 1.1')

    def test_edited_translation_carries_its_credit(self):
        bn, en = self.pair(en_kwargs={'method': 'ai_edited', 'credit': 'Asha Rahman'})
        self.assertEqual(parallel_companion(self.member, bn.pk, self.unit(bn))['translation'],
                         {'method': 'ai_edited', 'credit': 'Asha Rahman'})

    def test_footnotes_and_headings_align_by_kind(self):
        kinds = ('heading', 'paragraph', 'note')
        bn, en = self.pair({'kinds': kinds}, {'kinds': kinds})
        companion = parallel_companion(self.member, bn.pk, self.unit(bn))
        self.assertEqual([p['kind'] for p in companion['paragraphs']], list(kinds))

    def test_not_offered_when_paragraph_counts_differ(self):
        bn, en = self.pair(en_kwargs={'kinds': ('paragraph', 'paragraph')})
        self.assertIsNone(parallel_companion(self.member, bn.pk, self.unit(bn)))
        self.assertIsNone(parallel_companion(self.member, en.pk, self.unit(en)))

    def test_not_offered_when_paragraph_kinds_differ(self):
        bn, en = self.pair(en_kwargs={'kinds': ('paragraph', 'note', 'paragraph')})
        self.assertIsNone(parallel_companion(self.member, bn.pk, self.unit(bn)))

    def test_not_offered_when_unit_counts_differ(self):
        bn, en = self.pair({'units': 2}, {'units': 1})
        self.assertIsNone(parallel_companion(self.member, bn.pk, self.unit(bn)))

    def test_not_offered_without_a_translation(self):
        bn = live_book(self.work, 'bn')
        self.assertIsNone(parallel_companion(self.member, bn.pk, self.unit(bn)))

    def test_not_offered_when_the_translation_is_not_live(self):
        bn, en = self.pair()
        Revision.objects.filter(pk=en.live_revision_id).update(state='retired')
        self.assertIsNone(parallel_companion(self.member, bn.pk, self.unit(bn)))

    def test_not_offered_when_the_companion_has_no_rights_in_this_territory(self):
        bn, en = self.pair()
        Rights.objects.filter(revision=en.live_revision).update(territories=['GB'])
        self.assertIsNone(parallel_companion(self.member, bn.pk, self.unit(bn)))
        self.assertIsNone(parallel_companion(self.member, en.pk, self.unit(en)), 'current edition unreadable')

    @override_settings(FREE_ACCESS_ENABLED=False)
    def test_not_offered_when_the_companion_needs_an_entitlement_the_member_lacks(self):
        bn, en = self.pair(en_kwargs={'policy': {'reader': 'paid'}})
        self.pass_entitlement(formats=['audio'])  # a Pass, but it does not open the paid English text
        self.assertIsNone(parallel_companion(self.member, bn.pk, self.unit(bn)))
        self.pass_entitlement(formats=['reader'], scope='edition', edition=en, source='one_time_order')
        self.assertIsNotNone(parallel_companion(self.member, bn.pk, self.unit(bn)))

    def test_anonymous_and_unverified_readers_get_no_pair(self):
        bn, en = self.pair()
        self.assertIsNone(parallel_companion(AnonymousUser(), bn.pk, self.unit(bn)))
        self.member.is_verified = False; self.member.save()
        self.assertIsNone(parallel_companion(self.member, bn.pk, self.unit(bn)))

    def test_unknown_unit_is_not_offered(self):
        bn, en = self.pair()
        self.assertIsNone(parallel_companion(self.member, bn.pk, str(uuid.uuid4())))
        self.assertIsNone(parallel_companion(self.member, bn.pk, self.unit(en)))

    def pass_entitlement(self, formats=('reader', 'audio'), scope='platform', edition=None, source='subscription_invoice'):
        now = timezone.now()
        return Entitlement.objects.create(grant_key=f'pass:{uuid.uuid4()}', user=self.member, source=source, scope=scope,
                                          edition=edition, formats=list(formats), valid_from=now - timedelta(minutes=1),
                                          valid_until=now + timedelta(days=30))

    @override_settings(FREE_ACCESS_ENABLED=False)
    def test_after_the_free_rollout_the_pair_needs_an_active_pass(self):
        bn, en = self.pair()
        self.assertIsNone(parallel_companion(self.member, bn.pk, self.unit(bn)))
        grant = self.pass_entitlement()
        self.assertIsNotNone(parallel_companion(self.member, bn.pk, self.unit(bn)))
        grant.revoked_at = timezone.now(); grant.status = 'revoked'; grant.save()
        self.assertIsNone(parallel_companion(self.member, bn.pk, self.unit(bn)))

    @override_settings(FREE_ACCESS_ENABLED=False)
    def test_an_edition_grant_is_not_a_pass(self):
        bn, en = self.pair()
        self.pass_entitlement(scope='edition', edition=bn, source='one_time_order')
        self.assertIsNone(parallel_companion(self.member, bn.pk, self.unit(bn)))
