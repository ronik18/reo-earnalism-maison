"""Backup and restore only the isolated local Maison development DB.
Does not contact cloud providers and does not qualify production PITR/HA.
"""
import hashlib
import json
import subprocess
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONTAINER='earnalism-maison-pg17'

def local_container(config):
    if config.get('HOST')!='127.0.0.1' or config.get('NAME')!='maison':
        raise ValueError('Only the isolated local development DB is supported')
    containers={55432:'earnalism-maison-pg17',55433:'earnalism-maison-pg18'}
    try:return containers[int(config.get('PORT',0))]
    except (KeyError,TypeError,ValueError):raise ValueError('Only the isolated PostgreSQL17/18 ports are supported')

def command(*args,stdout=None):
    return subprocess.run(['docker','exec',CONTAINER,*args],check=True,stdout=stdout or subprocess.PIPE,stderr=subprocess.PIPE)

def counts(database):
    query="SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    tables=command('psql','-U','maison','-d',database,'-At','-c',query).stdout.decode().splitlines()
    result={}
    for table in tables:
        if not table.replace('_','').isalnum():raise ValueError('Unexpected table identifier')
        query=f'SELECT count(*),md5(coalesce(string_agg(row_json,CHR(10) ORDER BY row_json),\'\')) FROM (SELECT row_to_json(t)::text row_json FROM "{table}" t) q'
        result[table]=command('psql','-U','maison','-d',database,'-At','-c',query).stdout.decode().strip()
    return result

def main():
    global CONTAINER
    config=json.loads((ROOT/'.local/database.json').read_text())
    try:CONTAINER=local_container(config)
    except ValueError as error:raise SystemExit(str(error)) from error
    target='maison_restore_'+uuid.uuid4().hex[:12]
    directory=ROOT/'.local/backups';directory.mkdir(exist_ok=True)
    path=directory/(target+'.dump')
    before=counts('maison')
    with path.open('wb') as stream:command('pg_dump','-U','maison','-d','maison','--format=custom','--no-owner','--no-acl',stdout=stream)
    path.chmod(0o600)
    command('createdb','-U','maison',target)
    with path.open('rb') as stream:
        subprocess.run(['docker','exec','-i',CONTAINER,'pg_restore','-U','maison','-d',target,'--no-owner','--no-acl','--exit-on-error'],stdin=stream,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
    after=counts(target)
    report={'scope':'local logical backup/restore only; production PITR/HA not qualified','source_container':CONTAINER,'source_database':'maison','restored_database':target,'backup_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'backup_bytes':path.stat().st_size,'tables_compared':len(before),'row_counts_and_content_hashes_match':before==after,'paid_infrastructure':False,'pass':before==after}
    (ROOT/'docs/evidence/local-backup-restore.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return 0 if report['pass'] else 1

if __name__=='__main__':raise SystemExit(main())
