"""Restore an already-downloaded Maison archive into a new local PG18 target.

No cloud calls. No private identity bytes are read by Python or printed. age
streams directly to pg_restore; no plaintext dump is written. Exact source
comparison requires the qualification export's consistent table_reference.

Run in the existing tools image/network with QUALIFICATION_TARGET_DATABASE_URL
pointing only to the existing loopback PG18 admin connection. Mount the owner's
identity file read-only. No original development or cloud database is restored
over, and only this run's newly generated target can be removed.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

from operations.database_export import ExportError, _stop, database_environment, database_reference


class RestoreError(Exception):
    pass


def validate_reference(manifest):
    reference = manifest.get('table_reference')
    if (not isinstance(reference, dict) or reference.get('format') != 'postgres-jsonb-C-SHA256-lengthprefixed-v1'
            or reference.get('schema') != 'public' or not isinstance(reference.get('tables'), dict)
            or not 1 <= len(reference['tables']) <= 1000):
        raise RestoreError('Exact comparison needs a consistent --with-reference qualification export.')
    for table, data in reference['tables'].items():
        if (not isinstance(table, str) or not table or not isinstance(data, dict)
                or type(data.get('rows')) is not int or data['rows'] < 0
                or not all(isinstance(data.get(key), str) and re.fullmatch(r'[a-f0-9]{64}', data[key]) for key in ('sha256', 'columns_sha256'))):
            raise RestoreError('The table reference is invalid.')
    return reference


def restore_archive(ciphertext, manifest_file, identity_file, target_url, *, max_seconds=900, keep_target=False,
                    age='age', pg_restore='pg_restore', createdb='createdb', dropdb='dropdb'):
    if not 0 < max_seconds <= 3600 or type(keep_target) is not bool:
        raise RestoreError('Restore bounds are invalid.')
    deadline = time.monotonic() + max_seconds
    cipher = Path(ciphertext); manifest_path = Path(manifest_file); identity = Path(identity_file)
    if (any(path.is_symlink() or not path.is_file() for path in (cipher, manifest_path, identity))
            or identity.stat().st_mode & 0o077 or manifest_path.stat().st_size > 65536):
        raise RestoreError('Use local regular files and an owner-private identity file.')
    try:
        manifest = json.loads(manifest_path.read_text())
        reference = validate_reference(manifest)
        size = manifest['ciphertext_bytes']; expected = manifest['ciphertext_sha256']
        if type(size) is not int or not 0 < size <= 20 * 1024**3 or cipher.stat().st_size != size:
            raise RestoreError('Ciphertext size does not match the manifest.')
        with cipher.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise RestoreError('Ciphertext checksum does not match the manifest.')
        env = database_environment(target_url, local=True)
        if env['PGHOST'] not in {'127.0.0.1', 'localhost'} or env['PGSSLMODE'] not in {'disable', 'verify-full'}:
            raise RestoreError('Restore target must be the explicit local PostgreSQL instance.')
        import psycopg
        def connect(database):
            return psycopg.connect(host=env['PGHOST'], port=env['PGPORT'], user=env['PGUSER'], password=env['PGPASSWORD'],
                                   dbname=database, sslmode=env['PGSSLMODE'], connect_timeout=3, autocommit=True,
                                   **({'sslrootcert': env['PGSSLROOTCERT']} if 'PGSSLROOTCERT' in env else {}),
                                   options=f'-c statement_timeout={max(1, int((deadline-time.monotonic())*1000))} -c lock_timeout=2000')
        with connect(env['PGDATABASE']) as connection:
            if int(connection.execute('SHOW server_version_num').fetchone()[0]) // 10000 != 18:
                raise RestoreError('Local restore requires PostgreSQL18.')
        version = subprocess.run([pg_restore, '--version'], check=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, timeout=min(5, max_seconds), text=True).stdout
        if not re.search(r'\b18\.', version):
            raise RestoreError('pg_restore18 is required.')
    except (RestoreError, ExportError):
        raise
    except Exception:
        raise RestoreError('Restore preflight failed.') from None

    target = 'maison_restore_archive_' + uuid.uuid4().hex[:12]
    created = False; decrypting = restoring = None; result = None
    child_env = {**env, 'PGOPTIONS': '-c statement_timeout=' + str(max(1, int((deadline-time.monotonic())*1000))) + ' -c lock_timeout=2000'}
    age_env = {key: value for key, value in env.items() if key in {'PATH', 'HOME', 'LANG', 'LC_ALL'}}
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RestoreError('Restore exceeded its time budget.')
        subprocess.run([createdb, '--maintenance-db=' + env['PGDATABASE'], target], env=child_env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=remaining)
        created = True
        decrypting = subprocess.Popen([age, '--decrypt', '--identity', str(identity), str(cipher)], env=age_env,
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
        restoring = subprocess.Popen([pg_restore, '--no-owner', '--no-acl', '--exit-on-error', '--single-transaction', '--dbname=' + target],
                                     env=child_env, stdin=decrypting.stdout, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
        decrypting.stdout.close()
        while decrypting.poll() is None or restoring.poll() is None:
            if time.monotonic() >= deadline:
                raise RestoreError('Restore exceeded its time budget.')
            if decrypting.poll() not in (None, 0) or restoring.poll() not in (None, 0):
                raise RestoreError('Decrypt/restore pipeline failed.')
            time.sleep(.05)
        if decrypting.returncode or restoring.returncode:
            raise RestoreError('Decrypt/restore pipeline failed.')
        with connect(target) as connection:
            connection.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            try:
                actual = database_reference(connection, deadline)
            finally:
                connection.rollback()
        matches = actual == reference
        result = {'status': 'pass' if matches else 'failed', 'scope': 'exact exported-snapshot logical archive restore; not PITR/HA',
                  'ciphertext_sha256': expected, 'tables_compared': len(reference['tables']),
                  'row_counts_content_and_column_hashes_match': matches, 'plaintext_dump_written': False,
                  'source_comparison': 'same REPEATABLE READ snapshot imported by pg_dump',
                  'target': target, 'target_preserved': keep_target, 'private_identity_emitted': False}
        if not matches:
            raise RestoreError('Restored table fingerprints differ from the exported snapshot.')
        return result
    except (RestoreError, ExportError):
        raise
    except Exception:
        raise RestoreError('Restore qualification failed.') from None
    finally:
        _stop(decrypting); _stop(restoring)
        if created and not keep_target:
            try:
                subprocess.run([dropdb, '--maintenance-db=' + env['PGDATABASE'], target], env=child_env,
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            except Exception:
                error = RestoreError('The isolated generated restore target needs local cleanup.')
                error.cleanup_target = target
                raise error from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ciphertext', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--identity-file', required=True)
    parser.add_argument('--max-seconds', type=int, default=900)
    parser.add_argument('--keep-target', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = restore_archive(args.ciphertext, args.manifest, args.identity_file,
                                 os.getenv('QUALIFICATION_TARGET_DATABASE_URL', ''),
                                 max_seconds=args.max_seconds, keep_target=args.keep_target)
        print(json.dumps(result, sort_keys=True)); return 0
    except (RestoreError, ExportError, OSError, ValueError) as error:
        result = {'status': 'failed', 'code': 'archive_restore_qualification_failed'}
        target = getattr(error, 'cleanup_target', '')
        if re.fullmatch(r'maison_restore_archive_[a-f0-9]{12}', target):
            result['local_cleanup_target'] = target
        print(json.dumps(result)); return 1


if __name__ == '__main__':
    raise SystemExit(main())
