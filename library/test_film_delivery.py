"""Private R2 film assets, synced captions and the short-lived film grant (PostgreSQL)."""
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Device
from billing.models import Entitlement
from core.api import DomainError
from . import services as svc
from .models import Asset, Edition, Revision, Rights, Unit, Work

FILM_MS = 5_400_000
SIGNED = 'https://private-test.invalid/film?signature=synthetic'


def parse(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


@override_settings(LOCAL=True, MAISON_LOCAL_FIXTURES=False, FREE_ACCESS_ENABLED=False,
                   FEATURES={'video': True}, VIDEO_PROVIDER='r2')
class FilmDeliveryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('film-member@example.test', 'Synthetic-Film-Passphrase-47',
                                                         is_verified=True)
        self.device = Device.objects.create(user=self.user, token_binding_sha256='0' * 64,
                                            expires_at=timezone.now() + timedelta(days=1))
        key = uuid.uuid4().hex
        self.work = Work.objects.create(slug='synthetic-film-' + key, title='Synthetic film')
        self.edition = Edition.objects.create(work=self.work, slug=self.work.slug, locale='en')
        self.revision = Revision.objects.create(edition=self.edition, title=self.work.title, access_policy={'video': 'paid'})
        self.unit = Unit.objects.create(revision=self.revision, ordinal=1, title='Synthetic film', duration_ms=FILM_MS)
        now = timezone.now()
        Rights.objects.create(revision=self.revision, format='video', action='read', territories=['IN'],
                              starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=1),
                              approved=True, test_only=False)

    def film(self, *, raw=False, **fields):
        values = dict(revision=self.revision, unit=self.unit, kind='video', provider='r2', state='ready',
                      storage_key=f'revisions/{self.revision.pk}/film/{uuid.uuid4().hex}.mp4', sha256='a' * 64,
                      bytes=734_003_200, content_type='video/mp4', duration_ms=FILM_MS)
        values.update(fields)
        return Asset.objects.bulk_create([Asset(**values)])[0] if raw else Asset.objects.create(**values)

    def captions(self, *, raw=False, **fields):
        values = dict(revision=self.revision, unit=self.unit, kind='video_captions', provider='r2', state='ready',
                      storage_key=f'revisions/{self.revision.pk}/film/{uuid.uuid4().hex}.vtt', sha256='b' * 64,
                      bytes=40_000, content_type='text/vtt')
        values.update(fields)
        return Asset.objects.bulk_create([Asset(**values)])[0] if raw else Asset.objects.create(**values)

    def publish(self):
        self.revision.state = 'live'
        self.revision.published_at = timezone.now()
        self.revision.save()
        self.edition.live_revision = self.revision
        self.edition.save()

    def entitle(self):
        now = timezone.now()
        Entitlement.objects.create(grant_key='synthetic-film-' + uuid.uuid4().hex, user=self.user, edition=self.edition,
                                   formats=['video'], source='one_time_order', scope='edition',
                                   valid_from=now - timedelta(seconds=1), valid_until=now + timedelta(hours=1))

    def request(self, asset, **extra):
        return {'asset_id': str(asset.pk), 'device_id': str(self.device.pk), 'purpose': 'online', **extra}

    def test_r2_video_requires_unit_mp4_duration_and_cap(self):
        # bulk_create bypasses model validation: the database constraint itself must refuse.
        for fields in ({'content_type': 'video/quicktime'}, {'duration_ms': None}, {'bytes': 1073741825}, {'unit': None}):
            with self.subTest(fields=fields):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    self.film(raw=True, **fields)
                with self.assertRaises(ValidationError):
                    self.film(**fields)
        self.assertEqual(self.film(bytes=1073741824).bytes, 1073741824)

    def test_video_captions_bounds(self):
        for fields in ({'content_type': 'text/plain'}, {'bytes': 1048577}, {'unit': None},
                       {'provider': 'stream', 'storage_key': uuid.uuid4().hex}):
            with self.subTest(fields=fields):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    self.captions(raw=True, **fields)
                with self.assertRaises(ValidationError):
                    self.captions(**fields)
        self.assertEqual(self.captions(bytes=1048576).content_type, 'text/vtt')

    def test_video_captions_are_never_deliverable(self):
        self.assertIn('video_captions', Asset.KINDS)
        self.assertNotIn('video_captions', svc.DELIVERABLE_KINDS)

    def r2_grant(self, asset):
        with override_settings(MEDIA_STORAGE_BACKEND='r2', R2_PRIVATE_BUCKET='private-test'), \
                patch('library.storage.private_url', return_value=SIGNED) as signer:
            grant = svc.media_grant(self.user, self.request(asset), 'IN')
        return grant, signer

    def test_film_grant_shape(self):
        asset = self.film()
        self.publish()
        self.entitle()
        grant, signer = self.r2_grant(asset)
        self.assertEqual(grant['transport'], 'r2_s3_presigned')
        self.assertEqual(grant['url'], SIGNED)
        self.assertEqual(grant['content_type'], 'video/mp4')
        self.assertIs(grant['range_supported'], True)
        self.assertIsNone(grant['quality_kbps'])
        self.assertEqual(grant['sha256'], asset.sha256)
        self.assertEqual(grant['duration_ms'], FILM_MS)
        self.assertEqual(grant['asset_id'], str(asset.pk))
        self.assertEqual(grant['edition_revision_id'], str(self.revision.pk))
        uuid.UUID(grant['grant_id'])
        self.assertLessEqual(parse(grant['expires_at']) - parse(grant['issued_at']), timedelta(seconds=120))
        signer.assert_called_once()
        key, seconds, content_type = signer.call_args.args
        self.assertEqual(key, asset.storage_key)
        self.assertTrue(1 <= seconds <= 120)
        self.assertEqual(content_type, 'video/mp4')

    def test_film_grant_range_supported(self):
        asset = self.film()
        self.publish()
        self.entitle()
        grant, _ = self.r2_grant(asset)
        self.assertIs(grant['range_supported'], True)

    def test_film_grant_local_uses_account_bound_signed_route(self):
        asset = self.film()
        self.publish()
        self.entitle()
        with override_settings(MEDIA_STORAGE_BACKEND='local'), patch('library.services._asset_valid') as valid, \
                patch('library.storage.verify_local_size') as present, patch('library.storage.private_url') as signer:
            grant = svc.media_grant(self.user, self.request(asset), 'IN')
        valid.assert_not_called()  # a film is never loaded into memory or re-hashed to be granted
        present.assert_called_once_with(asset.storage_key, asset.bytes)
        signer.assert_not_called()
        self.assertEqual(grant['transport'], 'local_signed')
        self.assertTrue(grant['url'].startswith(f'/api/v1/content/local-assets/{asset.pk}?token='))

    def test_local_film_url_serves_bounded_ranges_for_browser_video(self):
        import hashlib, tempfile
        from . import storage
        raw = bytes(range(256)) * 4
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        with override_settings(MEDIA_STORAGE_BACKEND='local', MEDIA_ROOT=directory.name):
            asset = self.film(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
            storage.put_private(asset.storage_key, raw, 'video/mp4')
            self.publish()
            self.entitle()
            login = self.client.post('/api/v1/auth/login', {
                'email': self.user.email, 'password': 'Synthetic-Film-Passphrase-47', 'password_purpose_consent': True,
                'password_purpose_version': 'password-account-v1'}, content_type='application/json')
            self.assertEqual(login.status_code, 200, login.content)
            grant = svc.media_grant(self.user, {**self.request(asset), 'device_id': login.json()['device_id']}, 'IN')
            self.assertEqual(grant['transport'], 'local_signed')
            whole = self.client.get(grant['url'], HTTP_RANGE='bytes=0-')
            self.assertEqual(whole.status_code, 206, whole.status_code)
            self.assertEqual(whole['Content-Range'], f'bytes 0-{len(raw) - 1}/{len(raw)}')
            self.assertEqual(whole['Accept-Ranges'], 'bytes')
            self.assertEqual(whole['Content-Type'], 'video/mp4')
            self.assertIn('no-store', whole['Cache-Control'])
            self.assertEqual(whole.getvalue(), raw)
            part = self.client.get(grant['url'], HTTP_RANGE='bytes=10-19')
            self.assertEqual((part.status_code, part.getvalue(), part['Content-Range']),
                             (206, raw[10:20], f'bytes 10-19/{len(raw)}'))
            plain = self.client.get(grant['url'])
            self.assertEqual((plain.status_code, plain['Accept-Ranges'], plain.getvalue()), (200, 'bytes', raw))
            outside = self.client.get(grant['url'], HTTP_RANGE=f'bytes={len(raw)}-')
            self.assertEqual(outside.status_code, 416)
            multi = self.client.get(grant['url'], HTTP_RANGE='bytes=0-1,4-5')
            self.assertEqual(multi.status_code, 416)

    def test_local_large_film_grant_and_open_range_stream_without_loading_or_hashing(self):
        """A 700 MiB film (sparse file) far above MAX_INLINE_BYTES: granted by recorded size, served by seek+read."""
        import tempfile
        from pathlib import Path
        from . import storage
        size = 734_003_200
        self.assertGreater(size, storage.MAX_INLINE_BYTES)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        with override_settings(MEDIA_STORAGE_BACKEND='local', MEDIA_ROOT=directory.name):
            asset = self.film(bytes=size)
            path = Path(directory.name) / asset.storage_key
            path.parent.mkdir(parents=True)
            with path.open('wb') as stream:
                stream.write(b'ftyp-head')
                stream.truncate(size)
                stream.seek(size - 9)
                stream.write(b'moov-tail')
            self.publish()
            self.entitle()
            login = self.client.post('/api/v1/auth/login', {
                'email': self.user.email, 'password': 'Synthetic-Film-Passphrase-47', 'password_purpose_consent': True,
                'password_purpose_version': 'password-account-v1'}, content_type='application/json')
            self.assertEqual(login.status_code, 200, login.content)
            device = login.json()['device_id']
            with patch('library.storage.verify_private', side_effect=AssertionError('film re-hashed per request')):
                grant = svc.media_grant(self.user, {**self.request(asset), 'device_id': device}, 'IN')
                self.assertEqual(grant['transport'], 'local_signed')
                whole = self.client.get(grant['url'], HTTP_RANGE='bytes=0-')
                self.assertEqual(whole.status_code, 206)
                self.assertEqual(whole['Content-Range'], f'bytes 0-{size - 1}/{size}')
                self.assertEqual(whole['Content-Length'], str(size))
                self.assertEqual((whole['Accept-Ranges'], whole['Content-Type']), ('bytes', 'video/mp4'))
                self.assertEqual(whole['Cache-Control'], 'private, no-store, max-age=0')
                chunks = iter(whole.streaming_content)
                first = next(chunks)
                self.assertLessEqual(len(first), storage.CHUNK_BYTES)
                self.assertTrue(first.startswith(b'ftyp-head'))
                del chunks, whole  # never read the remaining ~700 MiB; the generator closes its file when collected
                tail = self.client.get(grant['url'], HTTP_RANGE=f'bytes={size - 9}-')
                self.assertEqual((tail.status_code, tail.getvalue(), tail['Content-Range']),
                                 (206, b'moov-tail', f'bytes {size - 9}-{size - 1}/{size}'))
                outside = self.client.get(grant['url'], HTTP_RANGE=f'bytes={size}-')
                self.assertEqual(outside.status_code, 416)
            # A film whose stored size differs from its recorded size is never granted.
            with path.open('r+b') as stream:
                stream.truncate(size - 1)
            with self.assertRaises(DomainError) as refused:
                svc.media_grant(self.user, {**self.request(asset), 'device_id': device}, 'IN')
            self.assertEqual((refused.exception.code, refused.exception.status), ('asset_integrity_failed', 503))

    def test_film_grant_refuses_outside_whitelist_and_without_entitlement(self):
        asset = self.film()
        self.publish()
        with override_settings(MEDIA_STORAGE_BACKEND='r2', R2_PRIVATE_BUCKET='private-test'), \
                patch('library.storage.private_url', return_value=SIGNED) as signer:
            with self.assertRaises(DomainError) as unentitled:
                svc.media_grant(self.user, self.request(asset), 'IN')
            self.entitle()
            with self.assertRaises(DomainError) as outside:
                svc.media_grant(self.user, self.request(asset), 'AE')
            signer.assert_not_called()
        self.assertEqual((unentitled.exception.code, unentitled.exception.status), ('entitlement_required', 403))
        self.assertEqual((outside.exception.code, outside.exception.status), ('rights_unavailable', 403))

    def test_film_grant_refuses_revoked_device_and_offline_purpose(self):
        asset = self.film()
        self.publish()
        self.entitle()
        with self.assertRaises(DomainError) as offline:
            svc.media_grant(self.user, self.request(asset, purpose='offline'), 'IN')
        self.assertEqual(offline.exception.code, 'asset_not_deliverable')
        self.device.revoked_at = timezone.now()
        self.device.save()
        with patch('library.storage.private_url', return_value=SIGNED), self.assertRaises(DomainError) as revoked:
            svc.media_grant(self.user, self.request(asset), 'IN')
        self.assertEqual(revoked.exception.code, 'device_revoked')

    def test_film_grant_feature_disabled(self):
        asset = self.film()
        self.publish()
        self.entitle()
        with override_settings(FEATURES={'video': False}), self.assertRaises(DomainError) as disabled:
            svc.media_grant(self.user, self.request(asset), 'IN')
        self.assertEqual((disabled.exception.code, disabled.exception.status), ('feature_disabled', 503))

    def test_film_grant_refuses_provider_other_than_configured(self):
        asset = self.film()
        self.publish()
        self.entitle()
        with override_settings(VIDEO_PROVIDER='stream'), patch('library.stream.grant') as stream_grant, \
                self.assertRaises(DomainError) as refused:
            svc.media_grant(self.user, self.request(asset), 'IN')
        stream_grant.assert_not_called()
        self.assertEqual((refused.exception.code, refused.exception.status), ('provider_not_configured', 503))

    def test_stream_video_grant_unchanged(self):
        asset = Asset.objects.create(revision=self.revision, unit=self.unit, kind='video', provider='stream',
                                     state='ready', storage_key=uuid.uuid4().hex, sha256='0' * 64, bytes=0,
                                     content_type='application/vnd.apple.mpegurl', duration_ms=FILM_MS)
        sentinel = {'transport': 'stream_signed'}
        with override_settings(VIDEO_PROVIDER='stream'), \
                patch('library.stream.grant', return_value=sentinel) as stream_grant:
            self.assertIs(svc.media_grant(self.user, self.request(asset), 'IN'), sentinel)
        stream_grant.assert_called_once()
        self.assertEqual(stream_grant.call_args.args[1].pk, asset.pk)
        self.assertEqual(stream_grant.call_args.args[2:], (str(self.device.pk), 'IN'))
        with patch('library.stream.grant') as stream_grant, self.assertRaises(DomainError) as refused:
            svc.media_grant(self.user, self.request(asset), 'IN')
        stream_grant.assert_not_called()
        self.assertEqual(refused.exception.code, 'provider_not_configured')

    def test_captions_cannot_be_granted_or_resolved(self):
        captions = self.captions()
        with self.assertRaises(DomainError) as refused:
            svc.media_grant(self.user, self.request(captions), 'IN')
        self.assertEqual(refused.exception.code, 'asset_not_deliverable')
        with self.assertRaises(DomainError) as signed:
            svc._asset_grant(self.user, captions, str(self.device.pk), 'IN')
        self.assertEqual(signed.exception.code, 'asset_not_deliverable')

    def test_video_format_available_for_r2_film(self):
        self.film()
        self.publish()
        revision = Revision.objects.get(pk=self.revision.pk)
        self.assertEqual(svc.available_formats(revision, 'IN'), ['video'])
        self.assertTrue(svc.video_formats_present(svc.ready_assets(revision)))
        with override_settings(VIDEO_PROVIDER='stream'):
            self.assertFalse(svc.video_formats_present(svc.ready_assets(Revision.objects.get(pk=self.revision.pk))))
            self.assertEqual(svc.available_formats(Revision.objects.get(pk=self.revision.pk), 'IN'), [])

    def media_check(self):
        with patch('library.storage.verify_asset'):
            report = svc.validate_revision(self.revision.pk, 'IN')
        return next(c for c in report['checks'] if c['code'] == 'media')

    def test_validation_requires_captions_for_r2_film(self):
        self.film()
        self.assertEqual(self.media_check()['status'], 'fail')
        self.captions(state='processing')
        self.assertEqual(self.media_check()['status'], 'fail')
        Asset.objects.filter(kind='video_captions').update(state='ready')
        self.assertEqual(self.media_check()['status'], 'pass')


VTT = b'WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nSynthetic caption line.\n'


@override_settings(LOCAL=True, MAISON_LOCAL_FIXTURES=False, FREE_ACCESS_ENABLED=False,
                   FEATURES={'video': True}, VIDEO_PROVIDER='r2')
class FilmCaptionsEndpointTests(TestCase):
    """Same-origin captions: the film authorization path, never cached, raw VTT bytes."""

    film = FilmDeliveryTests.film
    captions = FilmDeliveryTests.captions
    publish = FilmDeliveryTests.publish
    entitle = FilmDeliveryTests.entitle

    def setUp(self):
        FilmDeliveryTests.setUp(self)
        self.video = self.film()
        self.vtt = self.captions(bytes=len(VTT))
        self.live = False
        self.login()

    def login(self):
        response = self.client.post('/api/v1/auth/login', {
            'email': self.user.email, 'password': 'Synthetic-Film-Passphrase-47', 'password_purpose_consent': True,
            'password_purpose_version': 'password-account-v1'}, content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)

    def url(self, asset=None):
        return f'/api/v1/content/video-captions/{(asset or self.video).pk}'

    def get(self, asset=None):
        if not self.live:  # Revision children freeze at publication: arrange assets first.
            self.live = True
            self.publish()
            self.entitle()
        with patch('library.storage.read_verified', return_value=VTT) as read:
            response = self.client.get(self.url(asset))
        return response, read

    def test_captions_served_no_store(self):
        response, read = self.get()
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertEqual(response['Content-Type'], 'text/vtt; charset=utf-8')
        self.assertEqual(response.content, VTT)
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(read.call_args.args[0].pk, self.vtt.pk)

    def test_captions_guest_401(self):
        self.client.logout()
        response, read = self.get()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['code'], 'authentication_required')
        read.assert_not_called()

    def test_captions_outside_whitelist_403(self):
        with patch('library.views.context', return_value=('en', 'AE')):
            response, read = self.get()
        self.assertEqual((response.status_code, response.json()['code']), (403, 'rights_unavailable'))
        read.assert_not_called()

    def test_captions_without_entitlement_403(self):
        self.live = True
        self.publish()
        response, read = self.get()
        self.assertEqual((response.status_code, response.json()['code']), (403, 'entitlement_required'))
        read.assert_not_called()

    def test_captions_missing_404(self):
        self.vtt.delete()
        response, read = self.get()
        self.assertEqual((response.status_code, response.json()['code']), (404, 'not_found'))
        read.assert_not_called()

    def test_captions_not_ready_or_other_unit_404(self):
        Asset.objects.filter(pk=self.vtt.pk).update(state='processing')
        self.assertEqual(self.get()[0].status_code, 404)

    def test_captions_for_other_unit_404(self):
        other = Unit.objects.create(revision=self.revision, ordinal=2, title='Other', duration_ms=FILM_MS)
        Asset.objects.filter(pk=self.vtt.pk).update(unit=other)
        self.assertEqual(self.get()[0].status_code, 404)

    def test_captions_for_non_film_asset_404(self):
        self.assertEqual(self.get(self.vtt)[0].status_code, 404)
        self.assertEqual(self.client.get(f'/api/v1/content/video-captions/{uuid.uuid4()}').status_code, 404)

    def test_captions_wrong_provider_404(self):
        with override_settings(VIDEO_PROVIDER='stream'):
            self.assertEqual(self.get()[0].status_code, 404)

    def test_captions_feature_disabled_503(self):
        with override_settings(FEATURES={'video': False}):
            response, read = self.get()
        self.assertEqual((response.status_code, response.json()['code']), (503, 'feature_disabled'))
        read.assert_not_called()


MIB = 1024 * 1024
ZERO_MIB = bytes(MIB)


def zeros_sha256(mib):
    import hashlib
    hasher = hashlib.sha256()
    for _ in range(mib):
        hasher.update(ZERO_MIB)
    return hasher.hexdigest()


class SlowLargeObject:
    """A provider body of `mib` zero MiB whose every read advances a fake clock: models a large, slow film."""

    def __init__(self, mib, clock, seconds_per_read):
        self.left = mib * MIB
        self.clock = clock
        self.seconds_per_read = seconds_per_read

    def read(self, n):
        self.clock[0] += self.seconds_per_read
        size = min(n, self.left, MIB)
        self.left -= size
        return ZERO_MIB[:size]

    def close(self):
        pass


@override_settings(LOCAL=True, MAISON_LOCAL_FIXTURES=False, FREE_ACCESS_ENABLED=False,
                   FEATURES={'video': True}, VIDEO_PROVIDER='r2')
class FilmVerificationBudgetTests(TestCase):
    """Controller ruling: full sha256 for films, with max(8, ceil(bytes/16 MiB)) seconds; other kinds keep 8 s."""

    film = FilmDeliveryTests.film
    captions = FilmDeliveryTests.captions

    def setUp(self):
        FilmDeliveryTests.setUp(self)

    def slow_open(self, mib, seconds_per_read, content_type='video/mp4'):
        clock = [0.0]
        opened = patch('library.storage._open', side_effect=lambda key: (
            SlowLargeObject(mib, clock, seconds_per_read), mib * MIB, content_type))
        ticking = patch('library.storage.time.monotonic', side_effect=lambda: clock[0])
        return opened, ticking

    def test_video_budget_formula(self):
        from . import storage
        self.assertEqual(storage.verification_budget_seconds('video', 1), 8)
        self.assertEqual(storage.verification_budget_seconds('video', 128 * MIB), 8)
        self.assertEqual(storage.verification_budget_seconds('video', 128 * MIB + 1), 9)
        self.assertEqual(storage.verification_budget_seconds('video', 1073741824), 64)
        self.assertEqual(storage.verification_budget_seconds('audio_chapter', 1073741824), 8)
        self.assertEqual(storage.verification_budget_seconds('video_captions', 1048576), 8)

    def test_validation_verifies_large_slow_film_within_scaled_budget(self):
        mib = 400  # 400 MiB film -> 25 s budget; at 40 ms per 1 MiB read it takes 16 s (> the old 8 s)
        self.film(bytes=mib * MIB, sha256=zeros_sha256(mib))
        opened, ticking = self.slow_open(mib, 0.04)
        with opened, ticking:
            self.assertIs(svc.prepare_revision_validation(self.revision.pk)['integrity'], True)

    def test_validation_large_film_integrity_mismatch_still_fails(self):
        mib = 400
        self.film(bytes=mib * MIB, sha256='c' * 64)
        opened, ticking = self.slow_open(mib, 0.04)
        from . import storage
        real = storage.verify_private
        seen = []

        def spy(*args, **kwargs):
            try:
                return real(*args, **kwargs)
            except DomainError as exc:
                seen.append(exc.code)
                raise
        with opened, ticking, patch('library.storage.verify_private', side_effect=spy):
            self.assertIs(svc.prepare_revision_validation(self.revision.pk)['integrity'], False)
        self.assertEqual(seen, ['asset_integrity_failed'])

    def test_validation_film_slower_than_scaled_budget_times_out(self):
        mib = 400  # 25 s budget; 100 ms per read needs 40 s
        self.film(bytes=mib * MIB, sha256=zeros_sha256(mib))
        opened, ticking = self.slow_open(mib, 0.1)
        with opened, ticking:
            self.assertIs(svc.prepare_revision_validation(self.revision.pk)['integrity'], False)

    def test_validation_non_video_assets_keep_eight_seconds(self):
        self.film(bytes=1073741824)
        self.captions()
        with patch('library.storage.verify_asset') as verify:
            svc.prepare_revision_validation(self.revision.pk)
        budgets = {call.args[0].kind: call.kwargs['max_seconds'] for call in verify.call_args_list}
        self.assertEqual(budgets, {'video': 64, 'video_captions': 8})

    def test_clone_copies_film_with_scaled_budget(self):
        self.film(bytes=1073741824)
        self.captions()
        with patch('library.storage.copy_verified') as copy, patch('library.services.prepare_reader_package') as package:
            package.side_effect = lambda unit, paragraphs: Asset(
                id=uuid.uuid4(), revision=unit.revision, unit=unit, kind='reader_package', state='ready',
                storage_key=f'revisions/{unit.revision.id}/{uuid.uuid4()}', sha256='d' * 64, bytes=10,
                content_type='application/json')
            try:
                svc.clone_revision(self.revision.pk)
            except Exception:
                pass  # persistence of the synthetic clone is out of scope; the copy budgets are the claim
        budgets = {call.args[0].kind: call.kwargs.get('max_seconds', 8) for call in copy.call_args_list}
        self.assertEqual(budgets, {'video': 64, 'video_captions': 8})

    def test_copy_verified_large_slow_film_mismatch_fails_within_scaled_budget(self):
        from . import storage
        mib = 200  # 13 s budget; 50 ms per read takes 10 s, so the read completes and the hash decides
        source = self.film(bytes=mib * MIB, sha256='e' * 64)
        opened, ticking = self.slow_open(mib, 0.05)
        with opened, ticking, patch('library.storage.private_exists', return_value=False), \
                patch('library.storage.put_private_file') as upload, self.assertRaises(DomainError) as refused:
            storage.copy_verified(source, f'revisions/{self.revision.pk}/copy',
                                  max_seconds=storage.verification_budget_seconds('video', source.bytes))
        upload.assert_not_called()
        self.assertEqual(refused.exception.code, 'asset_integrity_failed')
