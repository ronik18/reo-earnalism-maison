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
                patch('library.storage.private_url') as signer:
            grant = svc.media_grant(self.user, self.request(asset), 'IN')
        valid.assert_called_once()
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
            self.assertEqual(whole.status_code, 206, whole.content[:200])
            self.assertEqual(whole['Content-Range'], f'bytes 0-{len(raw) - 1}/{len(raw)}')
            self.assertEqual(whole['Accept-Ranges'], 'bytes')
            self.assertEqual(whole['Content-Type'], 'video/mp4')
            self.assertIn('no-store', whole['Cache-Control'])
            self.assertEqual(whole.content, raw)
            part = self.client.get(grant['url'], HTTP_RANGE='bytes=10-19')
            self.assertEqual((part.status_code, part.content, part['Content-Range']),
                             (206, raw[10:20], f'bytes 10-19/{len(raw)}'))
            plain = self.client.get(grant['url'])
            self.assertEqual((plain.status_code, plain['Accept-Ranges'], plain.content), (200, 'bytes', raw))
            outside = self.client.get(grant['url'], HTTP_RANGE=f'bytes={len(raw)}-')
            self.assertEqual(outside.status_code, 416)
            multi = self.client.get(grant['url'], HTTP_RANGE='bytes=0-1,4-5')
            self.assertEqual(multi.status_code, 416)

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
