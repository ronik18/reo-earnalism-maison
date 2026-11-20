"""03:00UTC entrypoint: separate backup credentials, no Django web startup.

Run with ``python -m operations.scheduled_export``. Retention previews unless
--apply-retention is explicitly configured after provider approval.
"""
import argparse
import json
import os
import tempfile
from .database_archive import Archive, ArchiveConfig, ArchiveError
from .database_export import export_database, ExportError
from .security_log_archive import run_security_log_archive


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply-retention', action='store_true')
    parser.add_argument('--with-reference', action='store_true', help='Qualification only: fingerprint the exact export snapshot; adds a full table read.')
    args = parser.parse_args(argv)
    try:
        config = ArchiveConfig(endpoint=os.getenv('BACKUP_R2_ENDPOINT', ''), bucket=os.getenv('BACKUP_R2_BUCKET', ''),
                               key_id=os.getenv('BACKUP_R2_KEY_ID', ''), secret=os.getenv('BACKUP_R2_SECRET', ''),
                               held_prefixes=tuple(json.loads(os.getenv('BACKUP_HELD_PREFIXES', '[]'))))
        config.validate()
    except (ArchiveError, ValueError, TypeError, OSError):
        print(json.dumps({'status': 'failed', 'code': 'backup_archive_failed'}))
        return 1
    try:
        with tempfile.TemporaryDirectory(prefix='maison-encrypted-archive-') as directory:
            report = export_database(os.getenv('MAISON_BACKUP_DATABASE_URL', ''), os.getenv('BACKUP_AGE_RECIPIENT', ''), directory,
                                     with_reference=args.with_reference)
            archive = Archive(config)
            uploaded = archive.upload(report, directory)
            retention = archive.retention(apply=args.apply_retention)
        result = {'status': 'verified_archive', 'ciphertext_bytes': report['ciphertext_bytes'],
                  'ciphertext_sha256': report['ciphertext_sha256'], 'archives': uploaded,
                  'retention': retention, 'restore_verified': False}
    except (ArchiveError, ExportError, ValueError, TypeError, OSError):
        result = {'status': 'failed', 'code': 'backup_archive_failed'}
    # Security collection remains available during a DB-export outage. Both
    # stages keep truthful outcomes; either enabled-stage failure fails the cron.
    try:
        result['security_logs'] = run_security_log_archive(config, apply_retention=args.apply_retention)
    except (ArchiveError, ValueError, TypeError, OSError):
        result['security_logs'] = {'status': 'failed', 'code': 'security_log_archive_failed'}
        if result['status'] == 'verified_archive':
            result.update(status='partial_failure', backup_status='verified_archive')
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'verified_archive' else 1


if __name__ == '__main__':
    raise SystemExit(main())
