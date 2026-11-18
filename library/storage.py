"""Private local/R2 object adapter. Immutable keys; bounded reads, no byte proxy for media."""
import hashlib
import re
import time
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from core.api import DomainError

CHUNK_BYTES = 1024 * 1024
MAX_INLINE_BYTES = 4 * CHUNK_BYTES


def _key(value):
    if not isinstance(value,str) or not re.fullmatch(r'(?:revisions|exports)/[A-Za-z0-9_./-]{1,480}',value) or '..' in value.split('/'):
        raise DomainError('invalid_storage_key','A generated private object key is required.',422)
    return value


def is_r2():
    name=getattr(settings,'MEDIA_STORAGE_BACKEND','local')
    if name not in {'local','r2'} or (name=='local' and not settings.LOCAL):
        raise DomainError('provider_not_configured','Private object storage is not configured.',503)
    return name=='r2'


def _local_path(key):
    root=Path(settings.MEDIA_ROOT).resolve();path=(root/_key(key)).resolve()
    if root not in path.parents:raise DomainError('invalid_storage_key','Invalid private object key.',422)
    return path


def _client(upload=False):
    """SDK construction is lazy: local development never searches for cloud credentials."""
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise DomainError('provider_not_configured','R2 SDK is not installed.',503) from exc
    endpoint=getattr(settings,'R2_ENDPOINT_URL','')
    parsed=urlsplit(endpoint)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'','/'} or not parsed.hostname or not parsed.hostname.endswith('.r2.cloudflarestorage.com'):
        raise DomainError('provider_not_configured','Use the configured HTTPS R2 S3 endpoint.',503)
    prefix='R2_UPLOAD' if upload else 'R2_APPLICATION'
    key=getattr(settings,prefix+'_KEY_ID','');secret=getattr(settings,prefix+'_SECRET','')
    if not key or not secret or not getattr(settings,'R2_PRIVATE_BUCKET',''):
        raise DomainError('provider_not_configured','R2 private bucket credentials are incomplete.',503)
    return boto3.client('s3',endpoint_url=endpoint,region_name='auto',aws_access_key_id=key,aws_secret_access_key=secret,
        config=Config(signature_version='s3v4',connect_timeout=3,read_timeout=5,retries={'total_max_attempts':1},s3={'addressing_style':'path'},
                      request_checksum_calculation='when_required',response_checksum_validation='when_required'))


def _params(key):return {'Bucket':settings.R2_PRIVATE_BUCKET,'Key':_key(key)}


def _provider_call(fn,*args,**kwargs):
    try:return fn(*args,**kwargs)
    except DomainError:raise
    except Exception as exc:
        # SDK exception text can contain signed requests/credentials: never expose it.
        raise DomainError('storage_unavailable','Private object storage is temporarily unavailable.',503) from exc


def private_url(key,expires_seconds=120,content_type=None):
    if type(expires_seconds)!=int or not 1<=expires_seconds<=120:
        raise DomainError('invalid_grant','Private URLs last at most120 seconds.',422)
    if not is_r2():
        raise DomainError('provider_not_configured','Use the account-bound local asset route in development.',503)
    params=_params(key);params['ResponseCacheControl']='private, no-store'
    if content_type:params['ResponseContentType']=content_type
    return _provider_call(_client().generate_presigned_url,'get_object',Params=params,ExpiresIn=expires_seconds,HttpMethod='GET')


def upload_url(asset,expires_seconds=120):
    if not is_r2():raise DomainError('provider_not_configured','Direct R2 upload is unavailable.',503)
    if type(expires_seconds)!=int or not 1<=expires_seconds<=120:raise DomainError('invalid_grant','Upload URL expiry is invalid.',422)
    params={**_params(asset.storage_key),'ContentType':asset.content_type,'ContentLength':asset.bytes,'IfNoneMatch':'*'}
    # Atomic create-once protects a finalized key even while its original signed URL remains valid.
    url=_provider_call(_client(upload=True).generate_presigned_url,'put_object',Params=params,ExpiresIn=expires_seconds,HttpMethod='PUT')
    return url,{'Content-Type':asset.content_type,'If-None-Match':'*'}


def _open(key):
    if is_r2():
        result=_provider_call(_client().get_object,**_params(key))
        return result['Body'],result.get('ContentLength'),result.get('ContentType')
    path=_local_path(key)
    try:return path.open('rb'),path.stat().st_size,None
    except OSError as exc:raise DomainError('asset_unavailable','Private object bytes are unavailable.',503) from exc


def verify_private(key,expected_bytes,expected_sha256,content_type=None,max_seconds=8,return_bytes=False):
    if type(expected_bytes)!=int or expected_bytes<1 or not re.fullmatch('[a-f0-9]{64}',expected_sha256 or ''):
        raise DomainError('invalid_asset','Expected object size/hash are invalid.',422)
    if return_bytes and expected_bytes>MAX_INLINE_BYTES:
        raise DomainError('asset_too_large','This object requires streaming verification.',413)
    started=time.monotonic();stream,size,mime=_open(key);hasher=hashlib.sha256();total=0;chunks=[]
    try:
        if size!=expected_bytes or (mime and content_type and mime.split(';')[0]!=content_type):
            raise DomainError('asset_integrity_failed','Private object size/type differs from its intent.',422)
        while True:
            if time.monotonic()-started>max_seconds:raise DomainError('asset_verification_timeout','Object verification exceeded its budget.',503)
            remaining=max_seconds-(time.monotonic()-started)
            if hasattr(stream,'set_socket_timeout'):stream.set_socket_timeout(max(.01,min(5,remaining)))
            block=stream.read(min(CHUNK_BYTES,expected_bytes-total+1))
            if not block:break
            total+=len(block)
            if total>expected_bytes:raise DomainError('asset_integrity_failed','Private object exceeds its expected size.',422)
            hasher.update(block)
            if return_bytes:chunks.append(block)
            # HTTP ContentLength was checked above. urllib3 can close its socket
            # immediately after these final bytes; never reset that exhausted socket.
            if total==expected_bytes:break
        if total!=expected_bytes or hasher.hexdigest()!=expected_sha256:
            raise DomainError('asset_integrity_failed','Private object bytes fail their SHA256 verification.',422)
    except DomainError:raise
    except Exception as exc:raise DomainError('storage_unavailable','Private object read was interrupted.',503) from exc
    finally:stream.close()
    return b''.join(chunks) if return_bytes else {'bytes':total,'sha256':hasher.hexdigest()}


def read_verified(asset):
    return verify_private(asset.storage_key,asset.bytes,asset.sha256,asset.content_type,return_bytes=True)


def verify_asset(asset,max_seconds=8):
    return verify_private(asset.storage_key,asset.bytes,asset.sha256,asset.content_type,max_seconds=max_seconds)


def put_private(key,raw,content_type='application/octet-stream'):
    _key(key)
    if not isinstance(raw,bytes) or not raw or len(raw)>MAX_INLINE_BYTES:
        raise DomainError('invalid_object','Server-produced private objects are limited to4MiB.',422)
    if is_r2():
        try:_provider_call(_client(upload=True).put_object,**_params(key),Body=raw,ContentLength=len(raw),ContentType=content_type,IfNoneMatch='*')
        except DomainError:
            # Conditional conflict or ambiguous timeout: accept only the exact independently read bytes.
            # An absent object retains the original failure; retry can safely use the same immutable key.
            if not private_exists(key):raise
            return verify_private(key,len(raw),hashlib.sha256(raw).hexdigest(),content_type)
        return verify_private(key,len(raw),hashlib.sha256(raw).hexdigest(),content_type)
    else:
        path=_local_path(key);path.parent.mkdir(parents=True,exist_ok=True)
        try:
            with path.open('xb') as stream:stream.write(raw)
        except FileExistsError:
            if path.read_bytes()!=raw:raise DomainError('object_exists','Private object already exists with different bytes.',409)
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def delete_private(key):
    if not _key(key).startswith('exports/'):
        raise DomainError('deletion_not_permitted','This operation only removes account export objects.',403)
    if is_r2():_provider_call(_client(upload=True).delete_object,**_params(key))
    else:_local_path(key).unlink(missing_ok=True)


def copy_verified(source,destination_key,*,max_seconds=8):
    """Conditional destination creation, never S3 CopyObject overwrite.

    Request callers default to8seconds; maintenance explicitly supplies a larger budget.

    Download to bounded-memory temporary scratch, verify source before upload, then
    complete a create-once multipart destination. Replayed/unknown writes reconcile
    through exact stored bytes. The private object remains the durable copy.
    """
    _key(destination_key);started=time.monotonic()
    if private_exists(destination_key):
        return verify_private(destination_key,source.bytes,source.sha256,source.content_type,max_seconds=max_seconds)
    stream,size,mime=_open(source.storage_key)
    try:
        if size!=source.bytes or mime and mime.split(';')[0]!=source.content_type:
            raise DomainError('asset_integrity_failed','Copy source differs from its expected size/type.',422)
        with tempfile.TemporaryFile(mode='w+b') as scratch:
            hasher=hashlib.sha256();count=0
            while True:
                remaining=max_seconds-(time.monotonic()-started)
                if remaining<=0:raise DomainError('asset_verification_timeout','Private copy exceeded its maintenance budget.',503)
                if hasattr(stream,'set_socket_timeout'):stream.set_socket_timeout(max(.01,min(5,remaining)))
                block=stream.read(min(CHUNK_BYTES,source.bytes-count+1))
                if not block:break
                count+=len(block)
                if count>source.bytes:raise DomainError('asset_integrity_failed','Copy source exceeds its expected size.',422)
                hasher.update(block);scratch.write(block)
                if count==source.bytes:break
            if count!=source.bytes or hasher.hexdigest()!=source.sha256:
                raise DomainError('asset_integrity_failed','Copy source SHA256 verification failed.',422)
            scratch.seek(0)
            return put_private_file(destination_key,scratch,source.content_type,source.bytes,source.sha256,
                max_seconds=max(.01,max_seconds-(time.monotonic()-started)))
    except DomainError:raise
    except Exception as exc:raise DomainError('copy_unavailable','Private object copy failed.',503) from exc
    finally:stream.close()


def put_private_file(key,fileobj,content_type,bytes,sha256,max_seconds=300):
    """Upload a server-produced file with bounded memory; caller supplies its measured hash."""
    _key(key)
    if type(bytes)!=int or not 1<=bytes<=10*1024**3 or not re.fullmatch('[a-f0-9]{64}',sha256 or ''):
        raise DomainError('invalid_object','Invalid generated export size/hash.',422)
    owned=not hasattr(fileobj,'read');stream=open(fileobj,'rb') if owned else fileobj
    start=time.monotonic();hasher=hashlib.sha256();count=0;upload_id=None;client=None
    try:
        if not is_r2():
            target=_local_path(key);target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():return verify_private(key,bytes,sha256,content_type,max_seconds=max_seconds)
            with target.open('xb') as out:
                while block:=stream.read(CHUNK_BYTES):
                    count+=len(block)
                    if count>bytes or time.monotonic()-start>max_seconds:raise DomainError('export_upload_failed','Generated export exceeded its bounds.',503)
                    hasher.update(block);out.write(block)
            if count!=bytes or hasher.hexdigest()!=sha256:
                target.unlink(missing_ok=True);raise DomainError('asset_integrity_failed','Generated export differs from its hash.',422)
        else:
            client=_client(upload=True)
            try:client.head_object(**_params(key))
            except Exception as exc:
                if str(getattr(exc,'response',{}).get('Error',{}).get('Code')) not in {'404','NoSuchKey','NotFound'}:
                    raise DomainError('storage_unavailable','Cannot inspect private export destination.',503) from exc
            else:return verify_private(key,bytes,sha256,content_type,max_seconds=max_seconds)
            created=_provider_call(client.create_multipart_upload,**_params(key),ContentType=content_type)
            upload_id=created['UploadId'];parts=[]
            while block:=stream.read(8*CHUNK_BYTES):
                count+=len(block)
                if count>bytes or time.monotonic()-start>max_seconds:raise DomainError('export_upload_failed','Generated export exceeded its bounds.',503)
                hasher.update(block)
                result=_provider_call(client.upload_part,**_params(key),UploadId=upload_id,PartNumber=len(parts)+1,Body=block,ContentLength=len(block))
                parts.append({'ETag':result['ETag'],'PartNumber':len(parts)+1})
            if count!=bytes or hasher.hexdigest()!=sha256:raise DomainError('asset_integrity_failed','Generated export differs from its hash.',422)
            try:_provider_call(client.complete_multipart_upload,**_params(key),UploadId=upload_id,MultipartUpload={'Parts':parts},IfNoneMatch='*')
            except DomainError:
                if not private_exists(key):raise
                result=verify_private(key,bytes,sha256,content_type,max_seconds=max(.01,max_seconds-(time.monotonic()-start)))
                # Abort any still-open losing multipart below; completed ambiguous sessions are harmless.
                return result
            upload_id=None
        return verify_private(key,bytes,sha256,content_type,max_seconds=max(.01,max_seconds-(time.monotonic()-start)))
    finally:
        if upload_id is not None:
            try:client.abort_multipart_upload(**_params(key),UploadId=upload_id)
            except Exception:pass  # Provider lifecycle rules clean an ambiguous/failed multipart session.
        if owned:stream.close()


def prepare_audio_pieces(asset,max_seconds=300):
    """One streaming verification pass prepares immutable1MiB offline hashes, never per download."""
    from .validation import validate_schema
    from .services import canonical_bytes
    stream,size,mime=_open(asset.storage_key);start=time.monotonic();total=0;whole=hashlib.sha256();pieces=[]
    try:
        if size!=asset.bytes or mime and mime.split(';')[0]!=asset.content_type:raise DomainError('asset_integrity_failed','Audio upload differs from its intent.',422)
        while True:
            if time.monotonic()-start>max_seconds:raise DomainError('asset_verification_timeout','Audio preparation exceeded its budget.',503)
            # StreamingBody.read(n) returns up to n bytes; aggregate a full piece before hashing.
            block=bytearray()
            while len(block)<CHUNK_BYTES:
                chunk=stream.read(CHUNK_BYTES-len(block))
                if not chunk:break
                block.extend(chunk)
            if not block:break
            if total+len(block)>asset.bytes or len(pieces)>=5000:raise DomainError('asset_integrity_failed','Audio exceeds prepared piece bounds.',422)
            whole.update(block);pieces.append({'piece_index':len(pieces),'offset_bytes':total,'bytes':len(block),'sha256':hashlib.sha256(block).hexdigest()});total+=len(block)
        if total!=asset.bytes or whole.hexdigest()!=asset.sha256:raise DomainError('asset_integrity_failed','Audio SHA256 verification failed.',422)
    finally:stream.close()
    document={'asset_id':str(asset.id),'asset_sha256':asset.sha256,'piece_bytes':CHUNK_BYTES,'pieces':pieces}
    validate_schema(document,'OfflinePiecePage');raw=canonical_bytes(document)
    if len(raw)>CHUNK_BYTES:raise DomainError('manifest_too_large','Split this audio into smaller prepared units.',413)
    key=f'revisions/{asset.revision_id}/offline-pieces/{asset.id}-{hashlib.sha256(raw).hexdigest()}.json'
    proof=put_private(key,raw,'application/json')
    return {**proof,'storage_key':key,'asset_sha256':asset.sha256}


def private_exists(key):
    _key(key)
    if not is_r2():return _local_path(key).is_file()
    try:_client().head_object(**_params(key))
    except Exception as exc:
        if str(getattr(exc,'response',{}).get('Error',{}).get('Code')) in {'404','NoSuchKey','NotFound'}:return False
        if isinstance(exc,DomainError):raise
        raise DomainError('storage_unavailable','Cannot inspect the private object.',503) from exc
    return True
