"""Exact emitted public cache references; publication and capture serialize locally."""
import hashlib
import json
import re
import uuid
from datetime import timedelta
from urllib.parse import urlsplit
from django.conf import settings
from django.db import connection,transaction
from django.db.models import F,Q
from django.utils import timezone
from core.models import OutboxJob
from .models import PublicCacheReference,PublicCacheGeneration
from .providers import _urls,PUBLIC_PATH

def _generation(shared=False):
    if shared:
        with connection.cursor() as cursor:
            cursor.execute('SELECT epoch FROM maison_public_cache_generation WHERE id=1 FOR SHARE')
            row=cursor.fetchone()
            if not row:raise ValueError('Missing cache generation')
            return row[0]
    return PublicCacheGeneration.objects.get(pk=1).epoch


def _candidate(request):
    if request.method!='GET' or getattr(request.user,'is_authenticated',False) or request.COOKIES or request.META.get('HTTP_COOKIE') or request.META.get('HTTP_AUTHORIZATION'):return None
    base=urlsplit(settings.PUBLIC_BASE_URL)
    if request.get_host()!=base.netloc:return None
    if base.scheme!='https' or base.path not in {'','/'} or base.query or base.fragment or base.username or base.password:return None
    if not PUBLIC_PATH.fullmatch(request.path):return None
    # Capture the actual URI, never generate a locale/country or enumerate variants.
    query=request.META.get('QUERY_STRING','')
    from library.cover_renditions import COVER_PATH
    if COVER_PATH.fullmatch(request.path):
        # Public cover objects are exact query-less paths (owner decision 26 Nov 2026).
        if query:return None
        url=f'{base.scheme}://{base.netloc}{request.path}'
        try:_urls({'urls':[url]},base.netloc)
        except Exception:return None
        return url if getattr(request,'territory',None) in settings.MAISON_PUBLICATION_TERRITORIES else None
    if not query:return None
    url=f'{base.scheme}://{base.netloc}{request.path}'+('?' + query if query else '')
    try:_urls({'urls':[url]},base.netloc)
    except Exception:return None
    if getattr(request,'territory',None) not in settings.MAISON_PUBLICATION_TERRITORIES:return None
    if query:
        if request.GET.get('territory')!=request.territory:return None
    return url


def begin_public_response(request):
    """Call before get_response; errors/missing markers fail closed in finalization."""
    request._maison_public_cache_start=None
    url=_candidate(request)
    if url:
        try:request._maison_public_cache_start=(url,_generation())
        except Exception:pass


def _private(response):
    current=response.get('Cache-Control','').lower()
    if 'private' not in current or 'no-store' not in current:
        response['Cache-Control']='private, no-store'
    return response


def _uuid(value):
    try:
        result=uuid.UUID(str(value))
        return str(result) if result.version==4 else None
    except (ValueError,TypeError,AttributeError):return None


def _dependencies(request,response):
    from library.models import Asset,Edition,Revision
    refs=set();edition_ids=set();revision_ids=set();asset_ids=set();work_ids=set()
    def visit(value):
        if isinstance(value,list):
            for item in value:visit(item)
        elif isinstance(value,dict):
            for key,item in value.items():
                identifier=_uuid(item) if isinstance(item,str) else None
                if identifier:
                    if key=='edition_id':edition_ids.add(identifier)
                    elif key in ['edition_revision_id','revision_id']:revision_ids.add(identifier)
                    elif key=='asset_id':asset_ids.add(identifier)
                    elif key=='work_id':work_ids.add(identifier)
                if isinstance(item,(dict,list)):visit(item)
    if response.get('Content-Type','').split(';')[0]=='application/json':
        if len(response.content)>1048576:raise ValueError('Oversized public response')
        visit(json.loads(response.content))
    for value in getattr(response,'_maison_cache_dependencies',[]):
        kind,identifier=value.split(':',1)
        if kind=='catalog' and identifier=='global':refs.add(value);continue
        identifier=_uuid(identifier)
        if not identifier:raise ValueError('Invalid cache dependency')
        target={'work':work_ids,'edition':edition_ids,'revision':revision_ids,'asset':asset_ids}.get(kind)
        if target is None:raise ValueError('Invalid cache dependency')
        target.add(identifier)
    path=request.path
    preview=re.fullmatch(r'/api/v1/content/previews/([0-9a-f-]{36})',path)
    cover=re.fullmatch(r'/api/v1/content/covers/([0-9a-f-]{36})',path)
    edition=re.fullmatch(r'/api/v1/catalog/editions/([0-9a-f-]{36})',path)
    work=re.fullmatch(r'/api/v1/catalog/works/([0-9a-f-]{36})',path)
    title=re.fullmatch(r'/(?:en|bn)/titles/([a-z0-9-]+)/',path)
    if preview:revision_ids.add(preview[1])
    if cover:asset_ids.add(cover[1])
    if edition:edition_ids.add(edition[1])
    if work:work_ids.add(work[1])
    if title:
        edition_ids.update(str(x) for x in Edition.objects.filter(slug=title[1]).values_list('id',flat=True))
    if not any([preview,cover,edition,work,title]):refs.add('catalog:global')
    if asset_ids:
        assets=list(Asset.objects.filter(pk__in=asset_ids,state='ready',kind='cover'))
        if len(assets)!=len(asset_ids):raise ValueError('Unready public asset')
        revision_ids.update(str(a.revision_id) for a in assets)
    if not revision_ids and not edition_ids and response.get('Content-Type','').startswith('text/html'):
        raise ValueError('SSR requires exact rendered cache dependencies')
    # Resolve explicit revisions and current edition pointers together. The same
    # response-local rights snapshot feeds the ordinary policy selector below.
    from library.services import prefetch_public_rights,public_ttl,global_preview_ttl
    revisions=prefetch_public_rights(Revision.objects.filter(
        Q(pk__in=revision_ids) | Q(edition_id__in=edition_ids,edition__live_revision_id=F('id'))
    ).select_related('edition'))
    if (not revision_ids.issubset({str(r.id) for r in revisions})
            or not edition_ids.issubset({str(r.edition_id) for r in revisions})):
        raise ValueError('Missing revision or unpublished edition')
    revision_ids.update(str(r.id) for r in revisions)
    ttl=60 if preview else 3600 if cover else 30
    for revision in revisions:
        if revision.state!='live' or revision.edition.live_revision_id!=revision.id:raise ValueError('Stale published response')
        remaining=public_ttl(revision,ttl,'preview' if preview else 'read',request.territory)
        # A preview cache key carries no territory: shared only while cleared in every publication territory.
        if preview and remaining>0:remaining=global_preview_ttl(revision,remaining)
        if remaining<=0:raise ValueError('Public rights unavailable')
        ttl=min(ttl,remaining);edition_ids.add(str(revision.edition_id));work_ids.add(str(revision.edition.work_id))
    for kind,values in [('work',work_ids),('edition',edition_ids),('revision',revision_ids),('asset',asset_ids)]:refs.update(kind+':'+str(x) for x in values)
    return sorted(refs),ttl


def finalize_public_response(request,response):
    """Call after cache policy, before emitting response headers. Any capture error is private."""
    start=getattr(request,'_maison_public_cache_start',None)
    if (not start or response.status_code!=200 or response.cookies or response.has_header('Set-Cookie')
        or 'authorization' in [part.strip().lower() for part in response.get('Vary','').split(',')] or getattr(response,'streaming',False)
        or 'private' in response.get('Cache-Control','').lower() or 'no-store' in response.get('Cache-Control','').lower()):return _private(response)
    match=re.search(r'(?:^|,)\s*s-maxage=(\d+)(?:,|$)',response.get('Cache-Control',''))
    if not match or int(match[1])<=0:return _private(response)
    try:
        with transaction.atomic():
            epoch=_generation(shared=True)
            if _candidate(request)!=start[0] or epoch!=start[1]:return _private(response)
            dependencies,remaining=_dependencies(request,response)
            ttl=min(int(match[1]),remaining)
            if ttl<=0:return _private(response)
            now=timezone.now();digest=hashlib.sha256(start[0].encode()).hexdigest()
            row=PublicCacheReference.objects.select_for_update().filter(url_sha256=digest).first()
            if row:
                if row.url!=start[0]:raise ValueError('URL digest collision')
                # Earlier responses may still be resident; keep their dependencies until TTL expires.
                row.dependencies=sorted(set(dependencies)|set(row.dependencies if row.expires_at>now else []))
                row.expires_at=max(row.expires_at,now+timedelta(seconds=ttl));row.save()
            else:PublicCacheReference.objects.create(url=start[0],url_sha256=digest,dependencies=dependencies,expires_at=now+timedelta(seconds=ttl))
            response['Cache-Control']=f'public, max-age=0, s-maxage={ttl}, must-revalidate'
    except Exception:return _private(response)
    return response


COVER_RECORD_HEADROOM=3600


def _cover_refs(request,response,ttl):
    start=getattr(request,'_maison_public_cache_start',None)
    dependencies=getattr(response,'_maison_public_cover',None)
    if not start or not dependencies or ttl<=0:return None,None
    refs=sorted(f'{kind}:{_uuid(value)}' for kind,value in dependencies.items() if _uuid(value))
    return (start,refs) if len(refs)==4 else (None,None)


def public_cover_covered(request,response,ttl):
    """True when an unexpired ledger row already covers this exact URL, its asset/revision and epoch until now+ttl.

    Read-only: no lock and no write. A purge committed after the request
    started changes the epoch (refused); one committed later finds the row.
    """
    start,refs=_cover_refs(request,response,ttl)
    if not start:return False
    try:
        if _candidate(request)!=start[0]:return False
        digest=hashlib.sha256(start[0].encode()).hexdigest()
        row=PublicCacheReference.objects.filter(url_sha256=digest).only('url','dependencies','expires_at').first()
        if (not row or row.url!=start[0] or not set(refs).issubset(row.dependencies)
                or row.expires_at<timezone.now()+timedelta(seconds=ttl)):return False
        return _generation()==start[1]
    except Exception:return False


def record_public_cover(request,response,ttl):
    """Record an emitted public cover URL like finalize_public_response, or return 0 (edge must not cache).

    Called only for live covers already cleared in every publication territory.
    The dependencies name the asset, revision, edition and work so publication,
    replacement and withdrawal purge the exact URL. A row already covering the
    URL is not touched; a new or extended row gets headroom so repeat edge
    misses within it are read-only.
    """
    start,refs=_cover_refs(request,response,ttl)
    if not start:return 0
    if public_cover_covered(request,response,ttl):return ttl
    try:
        with transaction.atomic():
            epoch=_generation(shared=True)
            if _candidate(request)!=start[0] or epoch!=start[1]:return 0
            now=timezone.now();digest=hashlib.sha256(start[0].encode()).hexdigest()
            until=now+timedelta(seconds=ttl+COVER_RECORD_HEADROOM)
            row=PublicCacheReference.objects.select_for_update().filter(url_sha256=digest).first()
            if row:
                if row.url!=start[0]:raise ValueError('URL digest collision')
                row.dependencies=sorted(set(refs)|set(row.dependencies if row.expires_at>now else []))
                row.expires_at=max(row.expires_at,until);row.save()
            else:PublicCacheReference.objects.create(url=start[0],url_sha256=digest,dependencies=refs,expires_at=until)
    except Exception:return 0
    return ttl


def _with_cover_siblings(urls):
    """A recorded cover URL also purges every reviewed width and the unversioned path of that asset."""
    from library.cover_renditions import COVER_PATH,all_cover_paths
    from library.models import Asset
    base=urlsplit(settings.PUBLIC_BASE_URL);result=list(urls)
    ids=set()
    for url in urls:
        parts=urlsplit(url);match=COVER_PATH.fullmatch(parts.path)
        if match and not parts.query:ids.add(match['asset_id'])
    for asset in Asset.objects.filter(pk__in=ids,kind='cover').order_by('id'):
        for path in all_cover_paths(asset.id,asset.sha256):
            url=f'{base.scheme}://{base.netloc}{path}'
            if url not in result:result.append(url)
    return result


@transaction.atomic
def queue_catalog_purge(revision):
    """Capture affected, actually emitted URLs in the publication transaction."""
    generation=PublicCacheGeneration.objects.select_for_update().get(pk=1)
    generation.epoch+=1;generation.save(update_fields=['epoch'])
    now=timezone.now()
    affected=Q(dependencies__contains=['catalog:global'])
    for value in ['work:'+str(revision.edition.work_id),'edition:'+str(revision.edition_id),'revision:'+str(revision.id)]:affected|=Q(dependencies__contains=[value])
    rows=list(PublicCacheReference.objects.select_for_update().filter(expires_at__gt=now).filter(affected).order_by('url_sha256'))
    if not rows:return {'status':'not_needed','reason':'no_unexpired_emitted_urls','url_count':0,'batch_count':0}
    urls=_with_cover_siblings([row.url for row in rows]);batches=0
    for index in range(0,len(urls),30):
        batch=urls[index:index+30];digest=hashlib.sha256(json.dumps(batch,separators=(',',':')).encode()).hexdigest()
        OutboxJob.objects.get_or_create(dedupe_key=f'catalog-purge:{revision.id}:{generation.epoch}:{digest}',defaults={
            'kind':'catalog_cache_purge','payload':{'edition_id':str(revision.edition_id),'revision_id':str(revision.id),'urls':batch},'not_before':now})
        batches+=1
    return {'status':'queued','url_count':len(urls),'batch_count':batches}


def cleanup_expired_references(limit=1000):
    identifiers=list(PublicCacheReference.objects.filter(expires_at__lte=timezone.now()).order_by('expires_at').values_list('pk',flat=True)[:max(1,min(10000,limit))])
    count,_=PublicCacheReference.objects.filter(pk__in=identifiers,expires_at__lte=timezone.now()).delete()
    return {'deleted':count}
