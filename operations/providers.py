"""Small qualified-provider operations; no credentials in outbox payloads.

Configuration: CLOUDFLARE_ZONE_ID, CLOUDFLARE_CACHE_PURGE_TOKEN (zone Cache Purge
permission only), PUBLIC_BASE_URL. Outbox payload.urls holds at most30 recorded
public URLs; edition/revision IDs alone never substitute for emitted references.

Cloudflare's exact-file purge API is repeat-safe. An API acknowledgement does
not establish global eviction; release qualification also samples CDN readback.
"""
import hashlib
import http.client
import json
import re
import ssl
import time
from urllib.parse import parse_qsl,urlsplit
from django.conf import settings
from core.api import DomainError

# Fixed API host. URL payloads select cache entries, never the request destination.
API_HOST='api.cloudflare.com'
PUBLIC_PATH=re.compile(r'/(?:api/v1/(?:home|catalog(?:/collections(?:/[0-9a-f-]{36})?|/works/[0-9a-f-]{36}|/editions/[0-9a-f-]{36})?|content/(?:previews|covers)/[0-9a-f-]{36})|(?:en|bn)/(?:|explore/|titles/[a-z0-9-]+/))\Z')


def _configuration():
    zone=getattr(settings,'CLOUDFLARE_ZONE_ID','')
    token=getattr(settings,'CLOUDFLARE_CACHE_PURGE_TOKEN','')
    base=getattr(settings,'PUBLIC_BASE_URL','')
    try:parsed=urlsplit(base);port=parsed.port
    except (TypeError,ValueError):raise DomainError('provider_not_enabled','Cloudflare purge origin is invalid.',503)
    if (not re.fullmatch(r'[0-9a-f]{32}',zone) or not token or any(c in token for c in '\r\n')
        or parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
        or parsed.path not in {'','/'} or parsed.query or parsed.fragment or port not in {None,443}):
        raise DomainError('provider_not_enabled','Cloudflare exact-URL cache purge is not configured.',503)
    return zone,token,parsed.netloc


def _urls(payload,host):
    values=payload.get('urls') if isinstance(payload,dict) else None
    if not isinstance(values,list) or not values:
        raise DomainError('catalog_purge_urls_missing','Recorded emitted public URLs are required before catalog purge can be qualified.',409)
    if len(values)>30:raise DomainError('invalid_purge_urls','Use at most 30 exact URLs per outbox batch.',422)
    territories=set(settings.MAISON_PUBLICATION_TERRITORIES)
    result=[]
    for value in values:
        if not isinstance(value,str) or len(value)>2048 or any(c in value for c in '\r\n\\'):
            raise DomainError('invalid_purge_urls','Invalid exact public cache URL.',422)
        try:parsed=urlsplit(value)
        except ValueError:raise DomainError('invalid_purge_urls','Invalid exact public cache URL.',422)
        if (parsed.scheme!='https' or parsed.netloc!=host or parsed.username or parsed.password or parsed.fragment
            or '%' in parsed.path or not PUBLIC_PATH.fullmatch(parsed.path)):
            raise DomainError('invalid_purge_urls','Only configured-origin public catalog/preview/cover URLs may be purged.',422)
        query=parse_qsl(parsed.query,keep_blank_values=True)
        if query and (len(query)!=2 or [key for key,value in query]!=['locale','territory']
            or query[0][1] not in {'en','bn'} or query[1][1] not in territories
            or parsed.query!=f'locale={query[0][1]}&territory={query[1][1]}'):
            raise DomainError('invalid_purge_urls','Only canonical locale/territory cache variants are permitted.',422)
        # Catalog JSON variants always carry explicit storefront context.
        if parsed.path.startswith('/api/v1/') and not query:
            raise DomainError('invalid_purge_urls','API public cache URLs require explicit locale/territory.',422)
        if value not in result:result.append(value)
    return result


def purge_catalog_cache(payload):
    """Purge one recorded exact-URL batch. Never skips missing URLs or configuration."""
    zone,token,host=_configuration();urls=_urls(payload,host)
    raw=json.dumps({'files':urls},separators=(',',':')).encode()
    digest=hashlib.sha256(raw).hexdigest();deadline=time.monotonic()+8
    connection=http.client.HTTPSConnection(API_HOST,timeout=3,context=ssl.create_default_context())
    try:
        connection.connect()
        if connection.sock:connection.sock.settimeout(max(.01,deadline-time.monotonic()))
        connection.request('POST',f'/client/v4/zones/{zone}/purge_cache',body=raw,
            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':'application/json'})
        if connection.sock:connection.sock.settimeout(max(.01,deadline-time.monotonic()))
        response=connection.getresponse();parts=[];size=0
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError()
            if connection.sock:connection.sock.settimeout(remaining)
            block=response.read(16384)
            if not block:break
            size+=len(block)
            if size>65536:raise ValueError('oversized provider response')
            parts.append(block)
        if response.status==429:raise DomainError('provider_rate_limited','Cloudflare purge was rate limited; the outbox will retry.',503)
        if not 200<=response.status<300:raise DomainError('provider_request_failed','Cloudflare purge was not acknowledged.',503)
        data=json.loads(b''.join(parts))
        if not isinstance(data,dict) or data.get('success') is not True or data.get('errors'):
            raise DomainError('provider_request_failed','Cloudflare purge was not acknowledged.',503)
        return {'status':'acknowledged','url_count':len(urls),'batch_sha256':digest,'readback_verified':False}
    except DomainError:raise
    except (OSError,TimeoutError,http.client.HTTPException,ValueError) as exc:
        raise DomainError('provider_outcome_unknown','Cloudflare purge outcome is unknown; repeat-safe outbox retry is required.',503) from exc
    finally:connection.close()
