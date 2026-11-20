"""Bounded Render -> age -> private R2 security-log archive, separate from DB backups.

Render schema/pagination: https://api-docs.render.com/reference/list-logs and
https://api-docs.render.com/openapi/render-public-api-1.json (Logs200Response).
Only ciphertext reaches disk; no restore identity belongs on this job host.
Uncommitted ciphertexts are preserved for operator review, not silently expired.
"""
import hashlib
import http.client
import ipaddress
import uuid
import json
import math
import os
import re
import select
import ssl
import subprocess
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, unquote, urlsplit, urlunsplit
from .database_archive import Archive, ArchiveError, HEX
from .database_export import _stop

ROOT='security-logs/v1/'
WORKSPACE='tea-dbu9jguc6qcc73c379bg'
RESOURCES=('srv-dbunbd8jo6nc73akbng0','crn-dbv7bte7bikc73fpso3g','crn-dbv7agetlv9c7381is10')
STAMP=r'\d{8}T\d{6}Z'
MANIFEST=re.compile(ROOT+r'windows/(\d{4}-\d{2}-\d{2})/('+STAMP+r')-([0-9a-f]{12})\.manifest\.json\Z')
CHECKPOINT=re.compile(ROOT+r'checkpoints/('+STAMP+r')\.json\Z')
HOLD=re.compile(ROOT+r'windows/\d{4}-\d{2}-\d{2}/\Z')
LABELS={'resource','instance','host','statusCode','method','level','type','path','build'}
SOURCE_FIELDS={'event','schema_version','at','component','method','path','route','status','duration_ms','request_id','actor_id','source_ip','territory'}


def instant(value):
    try:
        if not isinstance(value,str) or len(value)>64:raise ValueError()
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        if result.tzinfo is None:raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError,TypeError):raise ArchiveError('Security-log timestamp is invalid.') from None


def iso(value):return value.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
def stamp(value):return value.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
def packed(value):return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()


def redact(value):
    """Defense in depth for provider messages, never an authority for extra fields."""
    if not isinstance(value,str) or len(value)>32768:raise ArchiveError('Security-log text exceeds its bound.')
    value=unquote(unquote(value))
    def url(match):
        try:
            parsed=urlsplit(match.group())
            host=parsed.hostname or ''
            return urlunsplit((parsed.scheme,host,parsed.path,'',''))
        except ValueError:return '[redacted-url]'
    value=re.sub(r'(?:https?|postgres(?:ql)?|redis)://[^\s<>"\']+',url,value,flags=re.I)
    value=re.sub(r'(/[^\s?<>"\']*)\?[^\s<>"\']*',r'\1',value)
    value=re.sub(r'(/(?:password-reset|verify-email)/)[^/\s?<>"\']+',r'\1[redacted]',value,flags=re.I)
    value=re.sub(r'\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+','[redacted-authorization]',value,flags=re.I)
    value=re.sub(r'([\w-]*(?:password|secret|token|credential|authorization|cookie|api[_-]?key|access[_-]?key)[\w-]*["\']?\s*[:=]\s*)(?:"[^"\n]*"|\'[^\'\n]*\'|[^\s,;]+)',r'\1[redacted]',value,flags=re.I)
    value=re.sub(r'\b[A-Za-z0-9_-]{24,}\b','[redacted-opaque]',value)
    return value


def source_value(key,value):
    if type(value) is float and not math.isfinite(value):return '[redacted-invalid-number]'
    if not isinstance(value,str):return value
    if key in {'request_id','actor_id'}:
        try:return str(uuid.UUID(value))
        except ValueError:return '[redacted-invalid-identity]'
    if key=='source_ip':
        try:return str(ipaddress.ip_address(value))
        except ValueError:return '[redacted-invalid-address]'
    return redact(value)


def safe_row(row,start,end):
    if not isinstance(row,dict) or not {'id','message','timestamp','labels'}<=row.keys():raise ArchiveError('Render log schema is invalid.')
    if not isinstance(row['id'],str) or not 1<=len(row['id'])<=512 or not isinstance(row['labels'],list) or len(row['labels'])>32:raise ArchiveError('Render log metadata is invalid.')
    at=instant(row['timestamp'])
    if not start<=at<=end:raise ArchiveError('Render returned a log outside the requested window.')
    labels={}
    for item in row['labels']:
        if not isinstance(item,dict) or not isinstance(item.get('name'),str) or not isinstance(item.get('value'),str):raise ArchiveError('Render log labels are invalid.')
        name=item['name'];value=item['value']
        if name=='resource' and name in labels:raise ArchiveError('Render log resource is ambiguous.')
        if name in LABELS:
            if len(value)>1024:raise ArchiveError('Render log label exceeds its bound.')
            labels[name]=value if name=='resource' else redact(value)
    if labels.get('resource') not in RESOURCES:raise ArchiveError('Render returned a resource outside the isolated allowlist.')
    message=redact(row['message'])
    try:source=json.loads(row['message'])
    except (ValueError,TypeError):source=None
    if isinstance(source,dict):
        # Unknown structured fields are omitted rather than copied as raw JSON.
        message=None;source={key:source_value(key,value) for key,value in source.items() if key in SOURCE_FIELDS and (value is None or type(value) in (str,int,float,bool))}
    result={'id':row['id'],'timestamp':row['timestamp'],'labels':labels}
    result['source' if message is None else 'message']=source if message is None else message
    return result


@dataclass(frozen=True)
class LogConfig:
    token:str
    inception:str
    held_prefixes:tuple=()
    max_pages:int=100
    max_lines:int=10000
    max_plain_bytes:int=20*1024**2

    def validate(self):
        if not isinstance(self.token,str) or not self.token or any(c in self.token for c in '\r\n') or len(self.token)>4096:raise ArchiveError('A scoped log-read credential is required.')
        instant(self.inception)
        if any(not isinstance(p,str) or not HOLD.fullmatch(p) for p in self.held_prefixes):raise ArchiveError('Security-log holds must name an exact generated UTC-day prefix.')
        if not 1<=self.max_pages<=2000 or not 1<=self.max_lines<=200000 or not 1<=self.max_plain_bytes<=256*1024**2:raise ArchiveError('Security-log bounds are invalid.')


class RenderLogs:
    def __init__(self,config,deadline):self.config=config;self.deadline=deadline

    def _remaining(self):
        remaining=self.deadline-time.monotonic()
        if remaining<=0:raise ArchiveError('Security-log collection exceeded its time budget.')
        return remaining

    def _socket_timeout(self,connection,sock=None):
        remaining=self._remaining()
        target=connection.sock or sock
        if target:target.settimeout(min(10,remaining))

    def page(self,start,end):
        query=[('ownerId',WORKSPACE),('startTime',start),('endTime',end),('direction','forward'),('limit','100')]+[('resource',value) for value in RESOURCES]
        for attempt in range(3):
            delay=.25*(2**attempt)
            connection=http.client.HTTPSConnection('api.render.com',timeout=min(10,self._remaining()),context=ssl.create_default_context())
            try:
                connection.request('GET','/v1/logs?'+urlencode(query),headers={'Authorization':'Bearer '+self.config.token,'Accept':'application/json','User-Agent':'Earnalism-Security-Archive/1'})
                self._socket_timeout(connection);network_socket=connection.sock;response=connection.getresponse()
                if response.status==200:
                    chunks=[];size=0
                    while True:
                        self._remaining()
                        # HTTPResponse can close its final socket reference as
                        # soon as a short Content-Length/chunked body is read.
                        if response.isclosed():break
                        self._socket_timeout(connection,network_socket)
                        part=response.read(65536)
                        if not part:break
                        size+=len(part)
                        if size>4*1024**2:raise ArchiveError('Render log page exceeds its bound.')
                        chunks.append(part)
                    if type(response.length) is int and response.length>0:
                        raise http.client.IncompleteRead(b'',response.length)
                    self._remaining()
                    try:return json.loads(b''.join(chunks))
                    except (ValueError,UnicodeDecodeError):raise ArchiveError('Render log page is not valid JSON.') from None
                if response.status!=429 and not 500<=response.status<=599:
                    raise ArchiveError('Scoped Render log read failed.')
                retry_after=response.getheader('Retry-After')
                if isinstance(retry_after,str):
                    try:
                        delay=float(retry_after)
                        if not math.isfinite(delay) or not 0<=delay<=10:raise ValueError()
                    except ValueError:raise ArchiveError('Scoped Render log read requires a later retry.') from None
            except ssl.SSLCertVerificationError:
                raise ArchiveError('Scoped Render log TLS verification failed.') from None
            except (OSError,http.client.HTTPException):
                # GET-only transport retries repeat the exact uncommitted page,
                # never yield partial records or expose provider exception data.
                pass
            finally:
                try:connection.close()
                except (OSError,http.client.HTTPException):pass
            if attempt==2:raise ArchiveError('Scoped Render log read failed after bounded retries.')
            if delay>=self._remaining():raise ArchiveError('Security-log retry exceeds its time budget.')
            time.sleep(delay)
        raise ArchiveError('Scoped Render log read failed.')


class SecurityLogs:
    def __init__(self,archive_config,log_config,recipient,*,client=None,api=None,age='age'):
        log_config.validate()
        if not isinstance(recipient,str) or not re.fullmatch(r'age1[0-9a-z]{58}',recipient):raise ArchiveError('A public age archive recipient is required.')
        #180 daily overlapping windows need more than1000 pair/checkpoint objects.
        self.archive=Archive(replace(archive_config,max_objects=max(archive_config.max_objects,5000),max_bytes=min(archive_config.max_bytes,25*1024**2)),client)
        self.config=log_config;self.recipient=recipient;self.api=api or RenderLogs(log_config,self.archive.deadline);self.age=age
        self.pages=self.lines=self.plain_bytes=0

    def _inventory(self,prefix):
        rows=[];token=None;seen=set()
        while True:
            options={'Prefix':prefix,'MaxKeys':min(1000,self.archive.config.max_objects-len(rows))}
            if token:options['ContinuationToken']=token
            response=self.archive.call('list_objects_v2',**options)
            part=response.get('Contents',[])
            if type(response.get('IsTruncated')) is not bool:raise ArchiveError('Security-log inventory completeness is unknown.')
            if not isinstance(part,list) or len(part)>options['MaxKeys'] or any(not isinstance(row,dict) or not isinstance(row.get('Key'),str) or not row['Key'].startswith(prefix) for row in part):raise ArchiveError('Security-log inventory is invalid.')
            rows.extend(part)
            if len(rows)>self.archive.config.max_objects:raise ArchiveError('Security-log inventory exceeds its bound.')
            if not response.get('IsTruncated'):return rows
            token=response.get('NextContinuationToken')
            if len(rows)>=self.archive.config.max_objects or not isinstance(token,str) or not token or len(token)>4096 or token in seen:raise ArchiveError('Security-log inventory pagination did not complete.')
            seen.add(token)

    def _put(self,key,body,content_type,digest,size):
        if not key.startswith(ROOT) or time.monotonic()>=self.archive.deadline:raise ArchiveError('Security-log write is outside its scope/budget.')
        try:self.archive.client.put_object(Bucket=self.archive.config.bucket,Key=key,Body=body,ContentType=content_type,Metadata={'sha256':digest,'maison-security-logs':'v1'},IfNoneMatch='*')
        except Exception as error:
            if str(getattr(error,'response',{}).get('Error',{}).get('Code','')) not in ('412','PreconditionFailed'):raise ArchiveError('Security-log archive write failed.') from None
        actual,count,_=self.archive.get(key,min(self.archive.config.max_bytes,max(size,1)))
        if (actual,count)!=(digest,size):raise ArchiveError('Security-log readback checksum mismatch.')

    def _json(self,key):
        digest,_,raw=self.archive.get(key,65536);head=self.archive.head(key)
        if head.get('Metadata',{}).get('maison-security-logs')!='v1' or head.get('Metadata',{}).get('sha256')!=digest:raise ArchiveError('Security-log metadata ownership/checksum is invalid.')
        try:
            value=json.loads(raw)
            if not isinstance(value,dict):raise ValueError()
            return value
        except ValueError:raise ArchiveError('Security-log metadata is invalid.') from None

    def _manifest(self,key):
        match=MANIFEST.fullmatch(key)
        if not match:raise ArchiveError('Security-log manifest key is invalid.')
        value=self._json(key)
        try:
            start=instant(value['window_start']);end=instant(value['window_end']);cipher=value['ciphertext_key']
            if (value['security_log_version']!=1 or value['workspace']!=WORKSPACE or value['resources']!=list(RESOURCES) or not start<end or end-start>timedelta(days=1)
                or match[1]!=start.strftime('%Y-%m-%d') or match[2]!=stamp(end) or cipher!=key.removesuffix('.manifest.json')+'.jsonl.age'
                or not HEX.fullmatch(value['ciphertext_sha256']) or match[3]!=value['ciphertext_sha256'][:12] or type(value['ciphertext_bytes']) is not int or not 0<value['ciphertext_bytes']<=self.archive.config.max_bytes):raise ValueError()
        except (KeyError,TypeError,ValueError):raise ArchiveError('Security-log manifest is invalid.') from None
        return value

    def _checkpoint(self,key):
        match=CHECKPOINT.fullmatch(key);value=self._json(key)
        try:
            if not match or value['security_log_checkpoint']!=1 or value['workspace']!=WORKSPACE or value['resources']!=list(RESOURCES) or match[1]!=stamp(instant(value['window_end'])):raise ValueError()
            entries=value['manifests']
            if not isinstance(entries,list) or not 1<=len(entries)<=9:raise ValueError()
            expected=instant(value['window_start'])
            for entry in entries:
                manifest=self._manifest(entry['key'])
                if hashlib.sha256(packed(manifest)).hexdigest()!=entry['sha256'] or instant(manifest['window_start'])!=expected:raise ValueError()
                actual,size,_=self.archive.get(manifest['ciphertext_key'],self.archive.config.max_bytes)
                if (actual,size)!=(manifest['ciphertext_sha256'],manifest['ciphertext_bytes']):raise ValueError()
                expected=instant(manifest['window_end'])
            if expected!=instant(value['window_end']):raise ValueError()
        except (KeyError,TypeError,ValueError):raise ArchiveError('Security-log checkpoint is invalid/incomplete.') from None
        return value

    def _rows(self,start,end):
        original_start=start;original_end=end;lower=iso(start);upper=iso(end);seen=set();ids={}
        while True:
            if (lower,upper) in seen or self.pages>=self.config.max_pages:raise ArchiveError('Render log pagination did not complete within its bound.')
            seen.add((lower,upper));self.pages+=1;page=self.api.page(lower,upper)
            if (not isinstance(page,dict) or not {'hasMore','nextStartTime','nextEndTime','logs'}<=page.keys() or type(page['hasMore']) is not bool or not isinstance(page['logs'],list) or len(page['logs'])>100):raise ArchiveError('Render log page schema is invalid.')
            for row in page['logs']:
                safe=safe_row(row,original_start,original_end);identity=safe['id'];raw=packed(safe);fingerprint=hashlib.sha256(raw).hexdigest()
                if identity in ids:
                    if ids[identity]!=fingerprint:raise ArchiveError('Render repeated a changed log identity.')
                    continue
                ids[identity]=fingerprint;self.lines+=1;self.plain_bytes+=len(raw)
                if self.lines>self.config.max_lines or self.plain_bytes>self.config.max_plain_bytes:raise ArchiveError('Security-log content exceeded its bound.')
                yield raw
            if not page['hasMore']:break
            next_lower=page['nextStartTime'];next_upper=page['nextEndTime'];lo=instant(next_lower);hi=instant(next_upper)
            if not original_start<=lo<=hi<=original_end or lo<instant(lower) or hi>instant(upper) or (next_lower,next_upper)==(lower,upper):raise ArchiveError('Render log pagination window is invalid.')
            lower,upper=next_lower,next_upper

    def _window(self,start,end,directory):
        target=Path(directory)/'logs.jsonl.age';process=None
        try:
            with target.open('wb') as output:
                target.chmod(0o600)
                process=subprocess.Popen([self.age,'--encrypt','--recipient',self.recipient],stdin=subprocess.PIPE,stdout=output,stderr=subprocess.DEVNULL,start_new_session=True,
                                         env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'LANG':'C.UTF-8'})
                os.set_blocking(process.stdin.fileno(),False)
                for raw in self._rows(start,end):
                    remaining=memoryview(raw)
                    while remaining:
                        if time.monotonic()>=self.archive.deadline or target.stat().st_size>self.archive.config.max_bytes:raise ArchiveError('Security-log encryption exceeded its bound.')
                        if process.poll() is not None:raise ArchiveError('Security-log encryption failed.')
                        if select.select([],[process.stdin.fileno()],[],0.1)[1]:
                            try:count=os.write(process.stdin.fileno(),remaining)
                            except BlockingIOError:continue
                            remaining=remaining[count:]
                process.stdin.close()
                while process.poll() is None:
                    if time.monotonic()>=self.archive.deadline or target.stat().st_size>self.archive.config.max_bytes:raise ArchiveError('Security-log encryption exceeded its bound.')
                    time.sleep(.02)
                if process.returncode:raise ArchiveError('Security-log encryption failed.')
            size=target.stat().st_size
            with target.open('rb') as stream:
                header=b'age-encryption.org/v1\n->'
                if stream.read(len(header))!=header:raise ArchiveError('Security-log encryption header is invalid.')
                stream.seek(0);digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if not 0<size<=self.archive.config.max_bytes:raise ArchiveError('Security-log ciphertext exceeds its bound.')
            prefix=ROOT+'windows/'+start.strftime('%Y-%m-%d')+'/'+stamp(end)+'-'+digest[:12]
            with target.open('rb') as stream:self._put(prefix+'.jsonl.age',stream,'application/octet-stream',digest,size)
            manifest={'security_log_version':1,'workspace':WORKSPACE,'resources':list(RESOURCES),'window_start':iso(start),'window_end':iso(end),'ciphertext_key':prefix+'.jsonl.age','ciphertext_sha256':digest,'ciphertext_bytes':size,'redaction_version':1}
            raw=packed(manifest);self._put(prefix+'.manifest.json',raw,'application/json',hashlib.sha256(raw).hexdigest(),len(raw))
            return {'key':prefix+'.manifest.json','sha256':hashlib.sha256(raw).hexdigest()}
        except ArchiveError:raise
        except Exception:raise ArchiveError('Security-log encrypted export failed.') from None
        finally:
            if process is not None and process.stdin and not process.stdin.closed:
                try:process.stdin.close()
                except OSError:pass
            _stop(process)

    def _held(self,key,value):
        if value.get('legal_hold') or value.get('retention_hold') or any(key.startswith(prefix) for prefix in self.config.held_prefixes):return True
        for target in {key,value.get('ciphertext_key',key)}:
            meta=self.archive.head(target).get('Metadata',{})
            if any(meta.get(name,'').casefold() in ('1','true','yes') for name in ('legal-hold','retention-hold')):return True
        return False

    def retention(self,now,apply=False,max_pairs=32):
        if not isinstance(now,datetime) or now.tzinfo is None or type(apply) is not bool or type(max_pairs) is not int or not 1<=max_pairs<=100:raise ArchiveError('Security-log retention bounds are invalid.')
        inventory=self._inventory(ROOT+'windows/');checkpoints=self._inventory(ROOT+'checkpoints/');cutoff=now-timedelta(days=180);candidates=[]
        for row in inventory:
            key=row['Key'];match=MANIFEST.fullmatch(key)
            if not match or datetime.strptime(match[2],'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)>cutoff:continue
            manifest=self._manifest(key)
            if instant(manifest['window_end'])<=cutoff and not self._held(key,manifest):
                head=self.archive.head(manifest['ciphertext_key']);metadata=head.get('Metadata',{})
                if head and (head.get('ContentLength')!=manifest['ciphertext_bytes'] or metadata.get('maison-security-logs')!='v1' or metadata.get('sha256')!=manifest['ciphertext_sha256']):raise ArchiveError('Security-log ciphertext ownership changed; no retention applied.')
                candidates.append((key,manifest))
        selected=sorted(candidates,key=lambda item:item[0])[:max_pairs];removed=0
        if apply:
            for key,value in selected:
                if self._held(key,value):continue
                self.archive.call('delete_object',Key=value['ciphertext_key']);self.archive.call('delete_object',Key=key)
                if self.archive.head(key) or self.archive.head(value['ciphertext_key']):raise ArchiveError('Security-log deletion readback failed.')
                removed+=1
            old=[]
            for row in checkpoints:
                key=row['Key'];match=CHECKPOINT.fullmatch(key)
                if not match:continue
                try:at=datetime.strptime(match[1],'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
                except ValueError:continue
                if at<=cutoff:old.append(key)
            for key in sorted(old)[:max_pairs]:
                value=self._json(key)
                try:
                    entries=value['manifests']
                    if (value['security_log_checkpoint']!=1 or value['workspace']!=WORKSPACE or value['resources']!=list(RESOURCES)
                        or stamp(instant(value['window_end']))!=CHECKPOINT.fullmatch(key)[1] or instant(value['window_end'])>cutoff
                        or not isinstance(entries,list) or not 1<=len(entries)<=9
                        or any(not isinstance(entry,dict) or not MANIFEST.fullmatch(entry.get('key','')) or not HEX.fullmatch(entry.get('sha256','')) for entry in entries)):raise ValueError()
                except (KeyError,TypeError,ValueError):raise ArchiveError('Security-log checkpoint ownership is invalid.') from None
                # Retain a checkpoint while any referenced pair remains, e.g.
                # held content or bounded retention not yet processed.
                if self._held(key,value) or any(self.archive.head(entry['key']) for entry in entries):continue
                self.archive.call('delete_object',Key=key)
                if self.archive.head(key):raise ArchiveError('Security-log checkpoint deletion readback failed.')
        return {'dry_run':not apply,'eligible_pairs':len(candidates),'removed_pairs':removed,'more':len(candidates)>len(selected)}

    def run(self,now=None,apply_retention=False):
        if type(apply_retention) is not bool:raise ArchiveError('Security-log retention flag must be boolean.')
        self.pages=self.lines=self.plain_bytes=0
        now=now or datetime.now(timezone.utc)
        if not isinstance(now,datetime) or now.tzinfo is None:raise ArchiveError('Security-log collection requires an aware UTC time.')
        now=now.astimezone(timezone.utc);end=(now-timedelta(minutes=5)).replace(second=0,microsecond=0)
        keys=[row['Key'] for row in self._inventory(ROOT+'checkpoints/')];known=[key for key in keys if CHECKPOINT.fullmatch(key)]
        previous=self._checkpoint(max(known)) if known else None
        inception=instant(self.config.inception)
        if previous and (instant(previous['window_end'])>now or instant(previous.get('inception',''))!=inception):raise ArchiveError('Security-log checkpoint continuity is invalid.')
        start=max(inception,instant(previous['window_end'])-timedelta(days=1)) if previous else inception
        if start<now-timedelta(days=7) or inception>start or start>=end:raise ArchiveError('Available log window is invalid or exceeds native retention; no checkpoint advanced.')
        if previous and end<=instant(previous['window_end']):return {'status':'already_archived','retention':self.retention(now,apply_retention)}
        manifests=[];point=start
        with tempfile.TemporaryDirectory(prefix='maison-encrypted-security-logs-') as directory:
            while point<end:
                following=min(end,(point+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0))
                manifests.append(self._window(point,following,directory));point=following
        checkpoint={'security_log_checkpoint':1,'inception':iso(inception),'workspace':WORKSPACE,'resources':list(RESOURCES),'window_start':iso(start),'window_end':iso(end),'manifests':manifests}
        raw=packed(checkpoint);key=ROOT+'checkpoints/'+stamp(end)+'.json';self._put(key,raw,'application/json',hashlib.sha256(raw).hexdigest(),len(raw))
        return {'status':'verified_security_log_archive','window_start':iso(start),'window_end':iso(end),'logs':self.lines,'pages':self.pages,'manifest_count':len(manifests),'checkpoint_sha256':hashlib.sha256(raw).hexdigest(),'retention':self.retention(now,apply_retention)}


def run_security_log_archive(archive_config,*,apply_retention=False):
    if os.getenv('SECURITY_LOG_ARCHIVE_ENABLED','false').lower()!='true':return {'status':'disabled'}
    try:
        values=json.loads(os.getenv('SECURITY_LOG_HELD_PREFIXES','[]'))
        if not isinstance(values,list):raise ValueError()
        holds=tuple(values)
    except (ValueError,TypeError):raise ArchiveError('Security-log hold configuration is invalid.') from None
    config=LogConfig(os.getenv('RENDER_LOG_READ_TOKEN',''),os.getenv('SECURITY_LOG_INCEPTION_UTC',''),holds)
    return SecurityLogs(archive_config,config,os.getenv('SECURITY_LOG_AGE_RECIPIENT','')).run(apply_retention=apply_retention)
