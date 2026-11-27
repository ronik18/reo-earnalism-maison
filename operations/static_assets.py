"""Deterministic Maison-only static releases; explicit immutable R2 publication."""
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit
from django.conf import settings
from core.api import DomainError

CHUNK_BYTES=1024*1024
CACHE_CONTROL='public, max-age=31536000, immutable'
MIME={'.js':'text/javascript','.css':'text/css','.woff2':'font/woff2','.woff':'font/woff','.ttf':'font/ttf','.otf':'font/otf',
      '.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.avif':'image/avif','.svg':'image/svg+xml',
      '.ico':'image/vnd.microsoft.icon','.json':'application/json','.webmanifest':'application/manifest+json','.txt':'text/plain','.md':'text/markdown'}
PRIVATE_PARTS={'private','intake','exports','revisions','evidence','credentials','secrets','books','manuscripts'}


def canonical_manifest(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')


def _bounds(max_files,max_file_bytes,max_total_bytes,max_seconds):
    if (type(max_files)!=int or not 1<=max_files<=10000 or type(max_file_bytes)!=int or not 1<=max_file_bytes<=100*CHUNK_BYTES
        or type(max_total_bytes)!=int or not 1<=max_total_bytes<=1024*CHUNK_BYTES or not 0<max_seconds<=3600):
        raise DomainError('invalid_asset_budget','Invalid bounded static release budget.',422)


def _content_type(relative):
    parts=relative.parts
    if (not parts or parts[0]!='maison' or any(part.startswith('.') or set(re.split(r'[-_.]',part.lower())) & PRIVATE_PARTS for part in parts)
        or relative.suffix.lower()=='.map' or any(not re.fullmatch(r'[A-Za-z0-9_.-]+',part) for part in parts)):
        return None
    mime=MIME.get(relative.suffix.lower())
    if not mime and relative.name.upper().startswith(('LICENSE','COPYING','NOTICE','OFL')):mime='text/plain'
    return mime


def tree_manifest(collected_directory,*,max_files=2000,max_file_bytes=20*CHUNK_BYTES,max_total_bytes=100*CHUNK_BYTES,max_seconds=30):
    _bounds(max_files,max_file_bytes,max_total_bytes,max_seconds)
    root=Path(collected_directory).resolve();namespace=root/'maison';deadline=time.monotonic()+max_seconds
    if not namespace.is_dir() or namespace.is_symlink():raise DomainError('static_tree_missing','A collected maison namespace is required.',422)
    assets=[];total=0
    for path in sorted(namespace.rglob('*')):
        if time.monotonic()>=deadline:raise DomainError('static_time_budget','Static preparation exceeded its time budget.',503)
        if path.is_symlink():raise DomainError('unsafe_static_path','Symlinks are not permitted in a public release.',422)
        if not path.is_file():continue
        relative=path.relative_to(root);mime=_content_type(relative)
        if not mime:continue
        if root not in path.resolve().parents:raise DomainError('unsafe_static_path','Invalid static path.',422)
        digest=hashlib.sha256();size=0
        with path.open('rb') as file:
            while True:
                if time.monotonic()>=deadline:raise DomainError('static_time_budget','Static preparation exceeded its time budget.',503)
                block=file.read(CHUNK_BYTES)
                if not block:break
                size+=len(block)
                if size>max_file_bytes:raise DomainError('static_size_budget','A static asset exceeds its size budget.',413)
                digest.update(block)
        total+=size
        if len(assets)>=max_files or total>max_total_bytes:raise DomainError('static_size_budget','The static release exceeds its size/count budget.',413)
        assets.append({'path':relative.as_posix(),'sha256':digest.hexdigest(),'bytes':size,'content_type':mime})
    if not assets:raise DomainError('static_tree_empty','No eligible Maison static assets were found.',422)
    manifest={'schema_version':1,'assets':assets,'file_count':len(assets),'bytes_total':total}
    return {**manifest,'release_id':hashlib.sha256(canonical_manifest(manifest)).hexdigest()}


def write_private_manifest(manifest,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='wb',dir=path.parent,delete=False) as file:
        temporary=Path(file.name);os.fchmod(file.fileno(),0o600);file.write(canonical_manifest(manifest)+b'\n')
    try:os.replace(temporary,path);path.chmod(0o600)
    finally:
        if temporary.exists():temporary.unlink()


def _public_client():
    endpoint=getattr(settings,'R2_ENDPOINT_URL','');account=getattr(settings,'R2_ACCOUNT_ID','');parsed=urlsplit(endpoint)
    bucket=getattr(settings,'R2_PUBLIC_BUCKET','');key=getattr(settings,'R2_PUBLIC_UPLOAD_KEY_ID','');secret=getattr(settings,'R2_PUBLIC_UPLOAD_SECRET','')
    if (not re.fullmatch(r'[a-f0-9]{32}',account) or parsed.scheme!='https' or parsed.netloc!=account+'.r2.cloudflarestorage.com'
        or parsed.path not in {'','/'} or parsed.query or parsed.fragment or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]',bucket)
        or bucket==getattr(settings,'R2_PRIVATE_BUCKET','') or not key or not secret
        or key in [getattr(settings,'R2_UPLOAD_KEY_ID',''),getattr(settings,'R2_APPLICATION_KEY_ID','')]):
        raise DomainError('public_storage_not_configured','A public bucket and separate public-only upload credentials are required.',503)
    import boto3
    from botocore.config import Config
    return boto3.client('s3',endpoint_url=endpoint,region_name='auto',aws_access_key_id=key,aws_secret_access_key=secret,
        config=Config(signature_version='s3v4',connect_timeout=3,read_timeout=5,retries={'total_max_attempts':1},s3={'addressing_style':'path'},
            request_checksum_calculation='when_required',response_checksum_validation='when_required'))


def _verify_object(client,bucket,key,asset,deadline):
    response=client.get_object(Bucket=bucket,Key=key);body=response['Body']
    try:
        if response.get('ContentLength')!=asset['bytes'] or response.get('ContentType')!=asset['content_type'] or response.get('CacheControl')!=CACHE_CONTROL:
            raise DomainError('public_asset_mismatch','Existing public asset metadata differs from the release.',409)
        size=0;digest=hashlib.sha256()
        while size<asset['bytes']:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise DomainError('static_time_budget','Static publication exceeded its time budget.',503)
            if hasattr(body,'set_socket_timeout'):body.set_socket_timeout(max(.01,min(5,remaining)))
            block=body.read(min(CHUNK_BYTES,asset['bytes']-size))
            if not block:break
            size+=len(block);digest.update(block)
        if size!=asset['bytes'] or digest.hexdigest()!=asset['sha256']:
            raise DomainError('public_asset_mismatch','Existing public asset bytes differ from the release.',409)
    finally:body.close()


def publish_manifest(collected_directory,manifest,*,execute=False,max_files=2000,max_file_bytes=20*CHUNK_BYTES,max_total_bytes=100*CHUNK_BYTES,max_seconds=300):
    _bounds(max_files,max_file_bytes,max_total_bytes,max_seconds)
    started=time.monotonic();deadline=started+max_seconds
    actual=tree_manifest(collected_directory,max_files=max_files,max_file_bytes=max_file_bytes,max_total_bytes=max_total_bytes,max_seconds=max_seconds)
    if manifest!=actual:raise DomainError('static_manifest_mismatch','The collected tree no longer matches its exact prepared release.',409)
    result={'status':'planned','release_id':actual['release_id'],'file_count':actual['file_count'],'bytes_total':actual['bytes_total'],
        'key_prefix':'static/'+actual['release_id']+'/','uploaded':0,'verified_existing':0,'public_http_verified':False}
    if not execute:return result
    client=_public_client();bucket=settings.R2_PUBLIC_BUCKET;root=Path(collected_directory).resolve()
    try:
        for asset in actual['assets']:
            if time.monotonic()>=deadline:raise DomainError('static_time_budget','Static publication exceeded its time budget.',503)
            key=result['key_prefix']+asset['path']
            with (root/asset['path']).open('rb') as file:
                try:
                    client.put_object(Bucket=bucket,Key=key,Body=file,ContentLength=asset['bytes'],ContentType=asset['content_type'],CacheControl=CACHE_CONTROL,IfNoneMatch='*',Metadata={'sha256':asset['sha256']})
                    result['uploaded']+=1
                except Exception as error:
                    code=getattr(error,'response',{}).get('Error',{}).get('Code')
                    status=getattr(error,'response',{}).get('ResponseMetadata',{}).get('HTTPStatusCode')
                    if code not in {'PreconditionFailed','ConditionalRequestConflict'} and status not in {409,412}:raise
                    result['verified_existing']+=1
            _verify_object(client,bucket,key,asset,deadline)
        result['status']='uploaded_and_verified';return result
    except DomainError:raise
    except Exception:raise DomainError('public_storage_unavailable','Static publication outcome is unknown; retry the same exact release.',503) from None
