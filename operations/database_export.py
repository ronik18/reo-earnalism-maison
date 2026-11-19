"""Bounded pg_dump18 -> age export. No plaintext dump is written to disk.

Only age's public recipient belongs on the job host. Restore identities must be
kept separately. This module performs no provider upload or retention deletion.
"""
import hashlib
import json
import os
import re
import signal
import ssl
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import parse_qs,unquote,urlsplit


class ExportError(Exception):
    pass


def database_reference(connection, deadline):
    """Stream canonical fingerprints inside the caller's consistent snapshot.

    Only counts and hashes are returned. Row values never leave the process or
    enter a plaintext artifact. Server-side cursors bound Python memory.
    """
    from psycopg import sql
    def bounded():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ExportError('Export reference exceeded its time budget.')
        connection.execute('SELECT set_config(\'statement_timeout\', %s, true)', (str(max(1, int(remaining * 1000))),))
    bounded()
    connection.execute("SET LOCAL TIME ZONE 'UTC'")
    connection.execute("SET LOCAL bytea_output = 'hex'")
    connection.execute("SET LOCAL intervalstyle = 'iso_8601'")
    connection.execute('SET LOCAL extra_float_digits = 3')
    tables = connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename COLLATE \"C\"").fetchall()
    if len(tables) > 1000:
        raise ExportError('Export reference table bound exceeded.')
    result = {}
    for (table,) in tables:
        bounded()
        columns = connection.execute("SELECT a.attname,pg_catalog.format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attidentity,a.attgenerated FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname=%s AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum", (table,)).fetchall()
        schema = hashlib.sha256(json.dumps(columns, separators=(',', ':')).encode()).hexdigest()
        digest = hashlib.sha256(); count = 0
        with connection.cursor(name='maison_reference_' + uuid.uuid4().hex[:12]) as cursor:
            cursor.itersize = 200
            cursor.execute(sql.SQL('SELECT to_jsonb(t)::text FROM {} t ORDER BY to_jsonb(t)::text COLLATE "C"').format(sql.Identifier('public', table)))
            for row in cursor:
                if time.monotonic() >= deadline:
                    raise ExportError('Export reference exceeded its time budget.')
                value = row[0].encode('utf-8')
                if len(value) > 16 * 1024**2:
                    raise ExportError('Export reference row bound exceeded.')
                digest.update(len(value).to_bytes(8, 'big')); digest.update(value); count += 1
        result[table] = {'rows': count, 'sha256': digest.hexdigest(), 'columns_sha256': schema}
    return {'format': 'postgres-jsonb-C-SHA256-lengthprefixed-v1', 'schema': 'public', 'tables': result}


@contextmanager
def export_reference_snapshot(env, deadline, enabled=False):
    """Hold a direct read-only transaction until pg_dump imports its snapshot."""
    if not enabled:
        yield None, None
        return
    import psycopg
    connection = None
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ExportError('Export reference exceeded its time budget.')
        connection = psycopg.connect(host=env['PGHOST'], port=env['PGPORT'], user=env['PGUSER'], password=env['PGPASSWORD'],
                                    dbname=env['PGDATABASE'], sslmode=env['PGSSLMODE'], connect_timeout=3,
                                    autocommit=True,
                                    **({'sslrootcert': env['PGSSLROOTCERT']} if 'PGSSLROOTCERT' in env else {}),
                                    options=f'-c default_transaction_read_only=on -c lock_timeout=2000 -c statement_timeout={max(1, int(remaining*1000))} -c idle_in_transaction_session_timeout={max(1, int(remaining*1000))}')
        connection.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        snapshot = connection.execute('SELECT pg_export_snapshot()').fetchone()[0]
        if not isinstance(snapshot, str) or not re.fullmatch(r'[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9]+', snapshot):
            raise ExportError('Database snapshot identifier is invalid.')
        reference = database_reference(connection, deadline)
        yield snapshot, reference
    except ExportError:
        raise
    except Exception:
        raise ExportError('Consistent export reference could not complete.') from None
    finally:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
            try:
                connection.close()
            except Exception:
                pass


def database_environment(url,*,local=False):
    try:
        parsed=urlsplit(url)
        port=parsed.port or 5432
        options=parse_qs(parsed.query,keep_blank_values=True)
    except (TypeError,ValueError):raise ExportError('A valid backup database URL is required.') from None
    if (parsed.scheme not in {'postgres','postgresql'} or not parsed.hostname or not parsed.username
        or not parsed.path.strip('/') or parsed.fragment or '-pooler.' in parsed.hostname):
        raise ExportError('Backup requires an explicit direct PostgreSQL connection.')
    if set(options)-{'sslmode','sslrootcert'} or any(len(v)!=1 for v in options.values()):
        raise ExportError('Unsupported or duplicate backup connection options.')
    sslmode=options.get('sslmode',['verify-full'])[0]
    if sslmode!='verify-full' and not (local and sslmode=='disable' and parsed.hostname in {'localhost','127.0.0.1','host.docker.internal'}):
        raise ExportError('Backup requires verified database TLS.')
    env={key:value for key,value in os.environ.items() if key in {'PATH','HOME','LANG','LC_ALL','SSL_CERT_FILE'}}
    env.update(PGHOST=parsed.hostname,PGPORT=str(port),PGUSER=unquote(parsed.username),PGPASSWORD=unquote(parsed.password or ''),
               PGDATABASE=unquote(parsed.path.lstrip('/')),PGSSLMODE=sslmode,PGCONNECT_TIMEOUT='3',
               PGAPPNAME='maison-independent-export')
    if sslmode=='verify-full':env['PGSSLROOTCERT']=options.get('sslrootcert',[ssl.get_default_verify_paths().cafile or '/etc/ssl/certs/ca-certificates.crt'])[0]
    return env


def database_facts(env):
    import psycopg
    try:
        with psycopg.connect(host=env['PGHOST'],port=env['PGPORT'],user=env['PGUSER'],password=env['PGPASSWORD'],
                            dbname=env['PGDATABASE'],sslmode=env['PGSSLMODE'],connect_timeout=3,
                            **({'sslrootcert':env['PGSSLROOTCERT']} if 'PGSSLROOTCERT' in env else {}),
                            options='-c statement_timeout=5000 -c default_transaction_read_only=on') as connection:
            with connection.cursor() as cursor:
                cursor.execute('SHOW server_version_num');version=int(cursor.fetchone()[0])
                if version//10000!=18:raise ExportError('This export command requires PostgreSQL18.')
                cursor.execute('SELECT app,name FROM django_migrations ORDER BY app,name');migrations=cursor.fetchall()
    except ExportError:raise
    except Exception:raise ExportError('Cannot read backup database metadata.') from None
    encoded=json.dumps(migrations,separators=(',',':')).encode()
    return {'server_version_num':version,'migration_count':len(migrations),'migration_sha256':hashlib.sha256(encoded).hexdigest()}


def _stop(process):
    if process is None or process.poll() is not None:return
    try:os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:return
    try:process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait(timeout=2)


def export_database(url,recipient,output_dir,*,local=False,max_seconds=900,max_bytes=2*1024**3,
                    pg_dump='pg_dump',age='age',with_reference=False):
    if not isinstance(recipient,str) or not re.fullmatch(r'age1[0-9a-z]{58}',recipient):
        raise ExportError('An age X25519 public backup recipient is required.')
    if not 0<max_seconds<=3600 or not 0<max_bytes<=20*1024**3:
        raise ExportError('Export time or size bound is invalid.')
    if type(with_reference) is not bool:
        raise ExportError('Export reference flag must be boolean.')
    started=time.monotonic()
    env=database_environment(url,local=local)
    try:
        version=subprocess.run([pg_dump,'--version'],check=True,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=5,text=True).stdout
        if not re.search(r'\b18\.',version):raise ExportError('pg_dump18 is required.')
    except (OSError,subprocess.SubprocessError):raise ExportError('pg_dump18 is unavailable.') from None
    facts=database_facts(env)
    output=Path(output_dir);output.mkdir(parents=True,exist_ok=True,mode=0o700)
    if output.is_symlink():raise ExportError('Backup output directory must not be a symlink.')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    stem='maison-'+stamp+'-'+uuid.uuid4().hex[:12]
    final=output/(stem+'.dump.age');manifest=output/(stem+'.manifest.json')
    dumped=encrypted=None
    env['PGOPTIONS']=f'-c statement_timeout={int(max_seconds*1000)} -c lock_timeout=2000 -c default_transaction_read_only=on'
    try:
        with export_reference_snapshot(env, started + max_seconds, with_reference) as (snapshot, reference), tempfile.TemporaryDirectory(prefix='.export-',dir=output) as temporary:
            pending=Path(temporary)/'database.dump.age'
            with pending.open('xb') as stream:
                pending.chmod(0o600)
                dump_args=[pg_dump,'--format=custom','--no-owner','--no-acl','--lock-wait-timeout=2000']
                if snapshot is not None:dump_args.append('--snapshot='+snapshot)
                dumped=subprocess.Popen(dump_args,
                                        env=env,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
                encrypted=subprocess.Popen([age,'--encrypt','--recipient',recipient],stdin=dumped.stdout,stdout=stream,
                                           stderr=subprocess.DEVNULL,start_new_session=True)
                dumped.stdout.close()
                while dumped.poll() is None or encrypted.poll() is None:
                    if time.monotonic()-started>max_seconds:raise ExportError('Export exceeded its time budget.')
                    if pending.stat().st_size>max_bytes:raise ExportError('Encrypted export exceeded its size budget.')
                    if dumped.poll() not in (None,0) or encrypted.poll() not in (None,0):raise ExportError('Export encryption pipeline failed.')
                    time.sleep(.05)
                if dumped.returncode or encrypted.returncode:raise ExportError('Export encryption pipeline failed.')
                stream.flush();os.fsync(stream.fileno())
            if not 0<pending.stat().st_size<=max_bytes:raise ExportError('Encrypted export size is invalid.')
            with pending.open('rb') as stream:
                header=b'age-encryption.org/v1\n->'
                if stream.read(len(header))!=header:raise ExportError('Export is not a standard age encrypted file.')
            with pending.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            report={'format':'PostgreSQL custom dump encrypted with age v1','completed_at':datetime.now(timezone.utc).isoformat(),
                    'ciphertext_file':final.name,'ciphertext_sha256':digest,'ciphertext_bytes':pending.stat().st_size,
                    'elapsed_seconds':round(time.monotonic()-started,3),'database':facts,
                    'provider_uploaded':False,'restore_verified':False}
            if reference is not None:
                report['table_reference'] = reference
            serialized_manifest = (json.dumps(report, indent=2) + '\n').encode()
            if len(serialized_manifest) > 65536:
                raise ExportError('Export manifest exceeds the private archive metadata bound.')
            pending_manifest=Path(temporary)/'manifest.json'
            with pending_manifest.open('xb') as stream:
                pending_manifest.chmod(0o600);stream.write(serialized_manifest);stream.flush();os.fsync(stream.fileno())
            os.link(pending,final);os.link(pending_manifest,manifest)
            return report
    except ExportError:raise
    except (OSError,subprocess.SubprocessError):raise ExportError('Export pipeline could not complete.') from None
    finally:
        _stop(dumped);_stop(encrypted)
