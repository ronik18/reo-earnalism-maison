"""Opt-in private synthetic R2 probe. No title, rights, account or public object mutation.

This is provider HTTP evidence, not a substitute for real browser/device acceptance.
Reports never contain signatures, credentials, provider response bodies or private URLs.
"""
import hashlib
import http.client
import ssl
import time
import uuid
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from urllib.parse import urlsplit,urlunsplit
from django.conf import settings
from core.api import DomainError
from . import storage


def _request(url,method='GET',headers=None,body=None):
    try:parsed=urlsplit(url);allowed=urlsplit(settings.R2_ENDPOINT_URL);port=parsed.port
    except (TypeError,ValueError):raise DomainError('invalid_probe_target','Invalid private R2 probe target.',422) from None
    if (parsed.scheme!='https' or parsed.hostname!=allowed.hostname or port not in {None,443}
        or parsed.username or parsed.password or parsed.fragment or method not in {'GET','PUT','OPTIONS'}):
        raise DomainError('invalid_probe_target','Only this configured private R2 endpoint may be probed.',422)
    deadline=time.monotonic()+8
    connection=http.client.HTTPSConnection(parsed.hostname,timeout=3,context=ssl.create_default_context())
    try:
        connection.connect()
        connection.sock.settimeout(max(.01,deadline-time.monotonic()))
        connection.request(method,urlunsplit(('','',parsed.path,parsed.query,'')),body=body,headers=headers or {})
        connection.sock.settimeout(max(.01,deadline-time.monotonic()))
        response=connection.getresponse();chunks=[];count=0
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError()
            if connection.sock:connection.sock.settimeout(remaining)
            block=response.read(16384)
            if not block:break
            count+=len(block)
            if count>131072:raise ValueError('bounded canary response exceeded')
            chunks.append(block)
        return response.status,{key.lower():value for key,value in response.getheaders()},b''.join(chunks)
    except (OSError,TimeoutError,http.client.HTTPException,ValueError) as exc:
        raise DomainError('provider_probe_failed','Private R2 probe request failed or exceeded its bounds.',503) from exc
    finally:connection.close()


def _unsigned_denial(status,body,canary):
    """R2 may reject missing S3 authentication as400 InvalidArgument rather than403."""
    code=None
    if isinstance(body,bytes) and len(body)<=131072 and b'<!DOCTYPE' not in body.upper() and b'<!ENTITY' not in body.upper():
        try:
            root=ET.fromstring(body)
            fields=[child for child in root if child.tag.rsplit('}',1)[-1]=='Code']
            if root.tag.rsplit('}',1)[-1]=='Error' and len(fields)==1 and len(fields[0])==0:
                value=(fields[0].text or '').strip()
                # Never echo arbitrary provider text, message, key, signature or request URL.
                if value in {'InvalidArgument','AccessDenied','NoSuchKey','SignatureDoesNotMatch','AuthorizationQueryParametersError','RequestExpired','ExpiredToken','InvalidAccessKeyId'}:code=value
        except (ET.ParseError,ValueError):pass
    no_canary=isinstance(body,bytes) and canary not in body
    denied=no_canary and (status in {401,403,404} or status==400 and code=='InvalidArgument')
    return denied,{'status':status,'code':code}


def _validated_origin(origin):
    try:parsed=urlsplit(origin);port=parsed.port
    except (TypeError,ValueError):raise DomainError('invalid_probe_origin','Use a valid exact qualification origin.',422) from None
    local_origin_only=(bool(settings.LOCAL) and parsed.scheme=='http' and parsed.hostname=='127.0.0.1'
        and port is not None and 1<=port<=65535 and parsed.netloc==f'127.0.0.1:{port}')
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'','/'}
        or not (local_origin_only or parsed.scheme=='https' and port in {None,443})):
        raise DomainError('invalid_probe_origin','Use the approved HTTPS origin, or an explicit127.0.0.1 HTTP port in LOCAL mode only.',422)
    origin=origin.rstrip('/')
    if not local_origin_only and origin!=getattr(settings,'PUBLIC_BASE_URL','').rstrip('/'):
        raise DomainError('invalid_probe_origin','HTTPS probe origin must equal configured PUBLIC_BASE_URL.',422)
    return origin,local_origin_only


def qualify_r2(origin,expiry_seconds=2,*,on_prepared=None):
    origin,local_origin_only=_validated_origin(origin)
    if not storage.is_r2():raise DomainError('provider_not_configured','Qualification requires the production R2 adapter.',503)
    if type(expiry_seconds)!=int or not 1<=expiry_seconds<=5:raise DomainError('invalid_probe_expiry','Use expiry1–5seconds.',422)
    identifier=uuid.uuid4();prefix=f'exports/qualification/{identifier}'
    keys=[prefix+'/server.bin',prefix+'/direct.bin',prefix+'/copy.bin']
    # Explicitly synthetic payload: no real text, assets, customer or rights data.
    raw=(b'Maison private synthetic storage qualification.\n'*1500)[:65536]
    sha=hashlib.sha256(raw).hexdigest();checks=[]
    def check(name,ok):checks.append({'check':name,'status':'pass' if ok else 'fail'})
    report={'schema_version':1,'probe_id':str(identifier),'scope':'synthetic_private_r2_http_only','sha256':sha,'bytes':len(raw),
        'local_origin_only':local_origin_only,'browser_qualified':False,'public_cdn_qualified':False,'public_bucket_exposure_verified':False,'checks':checks,'cleanup':[],
        'status':'running','canary_keys':keys,
        'budget_plan':{'max_write_requests':16,'max_read_or_options_requests':40,'max_transfer_bytes':3*1024*1024,
            'basis':'conservative source-derived per-run ceiling with SDK total_max_attempts1; not measured provider billing telemetry'}}
    # Persist exact synthetic locators before the first write, so interruption does not lose cleanup scope.
    if on_prepared:on_prepared(report)
    try:
        storage.put_private(keys[0],raw,'application/octet-stream')
        check('server_upload_exact_sha256',storage.verify_private(keys[0],len(raw),sha,'application/octet-stream')['sha256']==sha)
        source=SimpleNamespace(storage_key=keys[0],bytes=len(raw),sha256=sha,content_type='application/octet-stream')
        check('immutable_copy_exact_sha256',storage.copy_verified(source,keys[2],max_seconds=60)['sha256']==sha)
        asset=SimpleNamespace(storage_key=keys[1],bytes=len(raw),content_type='application/octet-stream')
        upload,upload_headers=storage.upload_url(asset,60)
        status,headers,data=_request(upload,'OPTIONS',{'Origin':origin,'Access-Control-Request-Method':'PUT','Access-Control-Request-Headers':'content-type,if-none-match'})
        check('staff_upload_preflight_exact_origin',status in {200,204} and headers.get('access-control-allow-origin')==origin
            and 'put' in headers.get('access-control-allow-methods','').lower()
            and {'content-type','if-none-match'}<=set(x.strip().lower() for x in headers.get('access-control-allow-headers','').split(',')))
        status,headers,data=_request(upload,'OPTIONS',{'Origin':'https://maison-cors-denied.invalid','Access-Control-Request-Method':'PUT','Access-Control-Request-Headers':'content-type,if-none-match'})
        check('foreign_staff_upload_origin_not_cors_authorized',headers.get('access-control-allow-origin') not in {'https://maison-cors-denied.invalid','*'})
        status,headers,data=_request(upload,'GET')
        check('upload_signature_method_bound',status in {401,403})
        status,headers,data=_request(upload,'PUT',{**upload_headers,'Content-Type':'text/plain','Origin':origin},raw)
        check('upload_signature_content_type_bound',status in {401,403})
        status,headers,data=_request(upload,'PUT',{**upload_headers,'Origin':origin},raw)
        check('direct_signed_put',status in {200,201,204} and headers.get('access-control-allow-origin')==origin)
        check('direct_upload_exact_sha256',storage.verify_private(keys[1],len(raw),sha,'application/octet-stream')['sha256']==sha)
        status,headers,data=_request(upload,'PUT',{**upload_headers,'Origin':origin},raw)
        check('create_once_overwrite_rejected',status==412)
        grant=storage.private_url(keys[0],60,'application/octet-stream')
        status,headers,data=_request(grant,headers={'Origin':origin})
        check('signed_get_exact_sha256',status==200 and hashlib.sha256(data).hexdigest()==sha)
        check('delivery_cors_exact_origin',headers.get('access-control-allow-origin')==origin)
        cache=headers.get('cache-control','').lower()
        check('delivery_private_no_store','private' in cache and 'no-store' in cache)
        exposed={value.strip().lower() for value in headers.get('access-control-expose-headers','').split(',')}
        check('delivery_exposes_range_headers',{'accept-ranges','content-length','content-range','etag'}<=exposed)
        status,headers,data=_request(grant,headers={'Origin':origin,'Range':'bytes=5-31'})
        check('signed_get_range_exact',status==206 and data==raw[5:32] and headers.get('content-range')==f'bytes 5-31/{len(raw)}')
        status,headers,data=_request(grant,'OPTIONS',{'Origin':origin,'Access-Control-Request-Method':'GET','Access-Control-Request-Headers':'range'})
        check('delivery_range_preflight',status in {200,204} and headers.get('access-control-allow-origin')==origin and 'range' in headers.get('access-control-allow-headers','').lower())
        foreign='https://maison-cors-denied.invalid'
        status,headers,data=_request(grant,'OPTIONS',{'Origin':foreign,'Access-Control-Request-Method':'GET','Access-Control-Request-Headers':'range'})
        check('foreign_origin_not_cors_authorized',headers.get('access-control-allow-origin') not in {foreign,'*'})
        parts=urlsplit(grant);unsigned=urlunsplit((parts.scheme,parts.netloc,parts.path,'',''))
        status,headers,data=_request(unsigned)
        denied,redacted=_unsigned_denial(status,data,raw)
        report['unsigned_response']=redacted
        check('unsigned_private_object_denied',denied)
        short=storage.private_url(keys[0],expiry_seconds,'application/octet-stream')
        time.sleep(expiry_seconds+2)
        status,headers,data=_request(short)
        check('expired_signed_get_denied',status in {401,403})
    except DomainError as exc:
        report['error_code']=exc.code
        checks.append({'check':'probe_completed','status':'fail'})
    except Exception:
        # Never expose signed SDK/HTTP exceptions, even for unexpected protocol responses.
        report['error_code']='qualification_failed'
        checks.append({'check':'probe_completed','status':'fail'})
    finally:
        for key in keys:
            try:
                storage.delete_private(key)
                removed=not storage.private_exists(key)
                report['cleanup'].append({'storage_key':key,'status':'pass' if removed else 'fail'})
            except Exception:report['cleanup'].append({'storage_key':key,'status':'fail'})
    report['status']='pass' if checks and all(row['status']=='pass' for row in checks+report['cleanup']) else 'fail'
    return report
