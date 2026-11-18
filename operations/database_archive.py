"""Separate, bounded private R2 backup archive; no media-bucket configuration.

An uploaded manifest commits a verified ciphertext. Retention only handles these
generated pairs, never arbitrary bucket contents or provider lifecycle rules.
"""
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = 'backups/v1/'
STEM = r'maison-\d{8}T\d{6}Z-[0-9a-f]{12}'
DAILY = re.compile(ROOT + r'daily/(\d{4}-\d{2}-\d{2})/(' + STEM + r')\.manifest\.json\Z')
MONTHLY = re.compile(ROOT + r'monthly/(\d{4}-\d{2})/manifest\.json\Z')
CIPHERTEXT = re.compile(ROOT + r'(?:daily/\d{4}-\d{2}-\d{2}|monthly/\d{4}-\d{2})/(' + STEM + r')\.dump\.age\Z')
HEX = re.compile(r'[0-9a-f]{64}\Z')
HELD_PREFIX = re.compile(ROOT + r'(?:daily/\d{4}-\d{2}-\d{2}|monthly/\d{4}-\d{2})/\Z')


class ArchiveError(Exception):
    pass


@dataclass(frozen=True)
class ArchiveConfig:
    endpoint: str
    bucket: str
    key_id: str
    secret: str
    held_prefixes: tuple = ()
    max_bytes: int = 2 * 1024**3
    max_seconds: int = 300
    max_objects: int = 1000

    def validate(self):
        parsed = urlsplit(self.endpoint)
        if (parsed.scheme != 'https' or not parsed.hostname or not re.fullmatch(r'[a-f0-9]{32}\.r2\.cloudflarestorage\.com', parsed.hostname)
                or parsed.username or parsed.password or parsed.port or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ArchiveError('A dedicated verified HTTPS R2 endpoint is required.')
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', self.bucket) or not self.key_id or not self.secret:
            raise ArchiveError('Dedicated archive bucket credentials are required.')
        if any(not HELD_PREFIX.fullmatch(p) for p in self.held_prefixes):
            raise ArchiveError('Holds must name an exact generated daily/monthly backup prefix.')
        if not 0 < self.max_bytes <= 20 * 1024**3 or not 0 < self.max_seconds <= 1800 or not 1 <= self.max_objects <= 10000:
            raise ArchiveError('Archive bounds are invalid.')


def archive_client(config):
    config.validate()
    import boto3
    from botocore.config import Config
    return boto3.client('s3', endpoint_url=config.endpoint, region_name='auto',
                       aws_access_key_id=config.key_id, aws_secret_access_key=config.secret,
                       config=Config(signature_version='s3v4', connect_timeout=3, read_timeout=5,
                                     retries={'total_max_attempts': 1}, s3={'addressing_style': 'path'},
                                     request_checksum_calculation='when_required', response_checksum_validation='when_required'))


class Archive:
    def __init__(self, config, client=None):
        config.validate()
        self.config = config
        self.client = client if client is not None else archive_client(config)
        self.deadline = time.monotonic() + config.max_seconds

    def call(self, method, **kwargs):
        if time.monotonic() >= self.deadline:
            raise ArchiveError('Archive exceeded its time budget.')
        try:
            return getattr(self.client, method)(Bucket=self.config.bucket, **kwargs)
        except ArchiveError:
            raise
        except Exception:
            # Never expose SDK exceptions, signed URLs or credential values.
            raise ArchiveError('Archive provider operation failed.') from None

    def get(self, key, max_bytes):
        response = self.call('get_object', Key=key)
        size = response.get('ContentLength')
        if type(size) is not int or not 0 < size <= max_bytes:
            response['Body'].close()
            raise ArchiveError('Archive object size is invalid.')
        body = response['Body']; digest = hashlib.sha256(); count = 0; chunks = []
        try:
            while True:
                if time.monotonic() >= self.deadline:
                    raise ArchiveError('Archive exceeded its time budget.')
                chunk = body.read(min(1024**2, max_bytes + 1 - count))
                if not chunk:
                    break
                count += len(chunk)
                if count > max_bytes:
                    raise ArchiveError('Archive object exceeds its bound.')
                digest.update(chunk)
                if max_bytes <= 65536:
                    chunks.append(chunk)
        except ArchiveError:
            raise
        except Exception:
            raise ArchiveError('Archive readback failed.') from None
        finally:
            try:
                body.close()
            except Exception:
                pass
        if count != size:
            raise ArchiveError('Archive object is truncated.')
        return digest.hexdigest(), count, b''.join(chunks)

    def put_verified(self, key, body, content_type, digest, size):
        if time.monotonic() >= self.deadline:
            raise ArchiveError('Archive exceeded its time budget.')
        try:
            self.client.put_object(Bucket=self.config.bucket, Key=key, Body=body, ContentType=content_type,
                                   Metadata={'sha256': digest, 'maison-backup': 'v1'}, IfNoneMatch='*')
        except Exception as error:
            code = str(getattr(error, 'response', {}).get('Error', {}).get('Code', ''))
            if code not in ('412', 'PreconditionFailed'):
                raise ArchiveError('Archive provider operation failed.') from None
            # Lost-response retry: verify the immutable existing object instead
            # of overwriting it or assuming the previous PUT succeeded.
        actual, count, _ = self.get(key, min(self.config.max_bytes, max(size, 1)))
        if actual != digest or count != size:
            raise ArchiveError('Archive readback checksum mismatch.')

    def inventory(self, prefix):
        response = self.call('list_objects_v2', Prefix=prefix, MaxKeys=self.config.max_objects)
        if response.get('IsTruncated'):
            raise ArchiveError('Archive inventory exceeds the bounded scan; no retention applied.')
        return response.get('Contents', [])

    def keys(self, prefix):
        return [row['Key'] for row in self.inventory(prefix)]

    def manifest(self, key):
        digest, _, raw = self.get(key, 65536)
        metadata = self.head(key).get('Metadata', {})
        if metadata.get('maison-backup') != 'v1' or metadata.get('sha256') != digest:
            raise ArchiveError('Archive manifest ownership/checksum is invalid; no retention applied.')
        try:
            value = json.loads(raw)
            timestamp = datetime.fromisoformat(value['completed_at'].replace('Z', '+00:00'))
            if timestamp.tzinfo is None or value['archive_version'] != 1:
                raise ValueError()
            daily = DAILY.fullmatch(key); monthly = MONTHLY.fullmatch(key)
            if daily:
                if value['retention_class'] != 'daily' or daily.group(1) != timestamp.strftime('%Y-%m-%d'):
                    raise ValueError()
            elif monthly:
                if value['retention_class'] != 'monthly' or monthly.group(1) != timestamp.strftime('%Y-%m'):
                    raise ValueError()
            else:
                raise ValueError()
            expected_prefix = key.rsplit('/', 1)[0] + '/'
            ciphertext = value['ciphertext_key']
            filename = ciphertext.removeprefix(expected_prefix)
            if not ciphertext.startswith(expected_prefix) or not re.fullmatch(STEM + r'\.dump\.age', filename):
                raise ValueError()
            if not HEX.fullmatch(value['ciphertext_sha256']) or type(value['ciphertext_bytes']) is not int or not 0 < value['ciphertext_bytes'] <= self.config.max_bytes:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ArchiveError('Archive manifest is invalid; no retention applied.') from None
        return value

    def held(self, manifest_key, manifest):
        if manifest.get('legal_hold') or manifest.get('retention_hold'):
            return True
        if any(manifest_key.startswith(p) for p in self.config.held_prefixes):
            return True
        for key in (manifest_key, manifest['ciphertext_key']):
            metadata = self.head(key).get('Metadata', {})
            if any(metadata.get(name, '').casefold() in ('true', '1', 'yes') for name in ('legal-hold', 'retention-hold')):
                return True
        return False

    def head(self, key):
        if time.monotonic() >= self.deadline:
            raise ArchiveError('Archive exceeded its time budget.')
        try:
            return self.client.head_object(Bucket=self.config.bucket, Key=key)
        except Exception as error:
            code = str(getattr(error, 'response', {}).get('Error', {}).get('Code', ''))
            if code in ('404', 'NoSuchKey', 'NotFound'):
                return {}
            raise ArchiveError('Archive provider operation failed.') from None

    def upload(self, report, output_dir):
        try:
            completed = datetime.fromisoformat(report['completed_at'].replace('Z', '+00:00'))
            if completed.tzinfo is None:
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            raise ArchiveError('Export completion timestamp is invalid.') from None
        now = completed.astimezone(timezone.utc)
        path = Path(output_dir) / report['ciphertext_file']
        if path.is_symlink() or not re.fullmatch(STEM + r'\.dump\.age', path.name):
            raise ArchiveError('Only a generated encrypted dump is accepted.')
        if path.stat().st_size != report['ciphertext_bytes'] or not 0 < path.stat().st_size <= self.config.max_bytes:
            raise ArchiveError('Local ciphertext size mismatch.')
        with path.open('rb') as stream:
            header = b'age-encryption.org/v1\n->'
            if stream.read(len(header)) != header:
                raise ArchiveError('A standard age encrypted dump is required.')
            stream.seek(0)
            if hashlib.file_digest(stream, 'sha256').hexdigest() != report['ciphertext_sha256']:
                raise ArchiveError('Local ciphertext checksum mismatch.')
        daily_prefix = ROOT + 'daily/' + now.strftime('%Y-%m-%d') + '/'
        monthly_prefix = ROOT + 'monthly/' + now.strftime('%Y-%m') + '/'
        monthly_key = monthly_prefix + 'manifest.json'
        # Existing committed month remains immutable; a new daily export cannot
        # replace it. An uncommitted orphan ciphertext is never treated as success.
        monthly_exists = monthly_key in self.keys(monthly_prefix)
        classes = [('daily', daily_prefix, daily_prefix + path.name.replace('.dump.age', '.manifest.json'))]
        if not monthly_exists:
            classes.append(('monthly', monthly_prefix, monthly_key))
        receipts = []
        for kind, prefix, manifest_key in classes:
            ciphertext_key = prefix + path.name
            with path.open('rb') as stream:
                self.put_verified(ciphertext_key, stream, 'application/octet-stream', report['ciphertext_sha256'], report['ciphertext_bytes'])
            value = {**report, 'archive_version': 1, 'ciphertext_key': ciphertext_key,
                     'retention_class': kind, 'provider_uploaded': True, 'restore_verified': False}
            raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
            self.put_verified(manifest_key, raw, 'application/json', hashlib.sha256(raw).hexdigest(), len(raw))
            receipts.append({'class': kind, 'manifest_key': manifest_key, 'ciphertext_sha256': report['ciphertext_sha256']})
        if monthly_exists:
            value = self.manifest(monthly_key)
            digest, size, _ = self.get(value['ciphertext_key'], self.config.max_bytes)
            if (digest, size) != (value['ciphertext_sha256'], value['ciphertext_bytes']):
                raise ArchiveError('Existing monthly archive checksum mismatch.')
        return receipts

    def retention(self, now=None, apply=False, max_pairs=32):
        now = now or datetime.now(timezone.utc)
        if type(apply) is not bool or not 1 <= max_pairs <= 100:
            raise ArchiveError('Retention bounds are invalid.')
        rows = self.inventory(ROOT + 'daily/') + self.inventory(ROOT + 'monthly/')
        daily = [row['Key'] for row in rows if DAILY.fullmatch(row['Key'])]
        monthly = sorted([row['Key'] for row in rows if MONTHLY.fullmatch(row['Key'])], reverse=True)
        manifests = {key: self.manifest(key) for key in daily + monthly}
        referenced = {value['ciphertext_key'] for value in manifests.values()}
        candidates = []
        # A missing/corrupt reference must not count toward12 retained snapshots
        # and cause removal of a valid older one. Upload already verified full
        # ciphertext GET/SHA; this bounded inventory checks immutable metadata.
        for key in monthly[:12]:
            value = manifests[key]
            head = self.head(value['ciphertext_key'])
            if (head.get('ContentLength') != value['ciphertext_bytes']
                    or head.get('Metadata', {}).get('sha256') != value['ciphertext_sha256']
                    or datetime.fromisoformat(value['completed_at'].replace('Z', '+00:00')) > now):
                raise ArchiveError('Retained monthly archive is incomplete; no retention applied.')
        for key in daily:
            value = manifests[key]
            if datetime.fromisoformat(value['completed_at'].replace('Z', '+00:00')) <= now - timedelta(days=30):
                candidates.append((key, value))
        # One committed manifest per month. Preserve exactly the newest12
        # completed calendar snapshots, not an approximate365-day duration.
        for key in monthly[12:]:
            candidates.append((key, manifests[key]))
        eligible = [(key, value) for key, value in candidates if not self.held(key, value)]
        for _, value in eligible:
            head = self.head(value['ciphertext_key'])
            # Missing ciphertext can be a prior interrupted deletion. An
            # existing unexpected replacement must never be silently deleted.
            if head and (head.get('Metadata', {}).get('maison-backup') != 'v1'
                         or head.get('Metadata', {}).get('sha256') != value['ciphertext_sha256']):
                raise ArchiveError('Archive ciphertext ownership is invalid; no retention applied.')
        selected = sorted(eligible, key=lambda pair: pair[0])[:max_pairs]
        # An interrupted upload can leave ciphertext before its manifest commits.
        # Only our generated, unreferenced,30-day-old objects qualify; metadata
        # and holds are rechecked, and unknown objects/manifests are untouched.
        orphans = []; held_orphans = 0
        for row in rows:
            key = row['Key']; modified = row.get('LastModified')
            if key in referenced or not CIPHERTEXT.fullmatch(key) or not isinstance(modified, datetime) or modified.tzinfo is None:
                continue
            if modified > now - timedelta(days=30):
                continue
            try:
                folder = key.split('/')[3]
                datetime.strptime(folder, '%Y-%m-%d' if '/daily/' in key else '%Y-%m')
                datetime.strptime(key.rsplit('/', 1)[-1].split('-')[1], '%Y%m%dT%H%M%SZ')
            except ValueError:
                continue
            head = self.head(key); metadata = head.get('Metadata', {})
            current_modified = head.get('LastModified')
            if not isinstance(current_modified, datetime) or current_modified.tzinfo is None or current_modified > now - timedelta(days=30):
                continue
            if metadata.get('maison-backup') != 'v1' or not HEX.fullmatch(metadata.get('sha256', '')):
                continue
            if self.held(key, {'ciphertext_key': key}):
                held_orphans += 1
            else:
                orphans.append(key)
        selected_orphans = sorted(orphans)[:max(0, max_pairs - len(selected))]
        removed = 0
        removed_orphans = 0
        if apply:
            for key, value in selected:
                # Recheck metadata/config holds immediately before deleting only
                # the generated pair. Delete ciphertext first; a partial failure
                # never pretends success and leaves the manifest for investigation.
                if self.held(key, value):
                    continue
                self.call('delete_object', Key=value['ciphertext_key'])
                self.call('delete_object', Key=key)
                if self.head(value['ciphertext_key']) or self.head(key):
                    raise ArchiveError('Archive deletion readback failed.')
                removed += 1
            for key in selected_orphans:
                if self.held(key, {'ciphertext_key': key}):
                    continue
                modified = self.head(key).get('LastModified')
                if not isinstance(modified, datetime) or modified.tzinfo is None or modified > now - timedelta(days=30):
                    continue
                self.call('delete_object', Key=key)
                if self.head(key):
                    raise ArchiveError('Archive deletion readback failed.')
                removed_orphans += 1
        return {'dry_run': not apply, 'eligible_pairs': len(eligible), 'selected_pairs': len(selected),
                'removed_pairs': removed, 'held_pairs': len(candidates) - len(eligible),
                'eligible_orphans': len(orphans), 'removed_orphans': removed_orphans, 'held_orphans': held_orphans,
                'more': len(eligible) > len(selected) or len(orphans) > len(selected_orphans),
                'targets': [key for key, _ in selected], 'orphan_targets': selected_orphans}
