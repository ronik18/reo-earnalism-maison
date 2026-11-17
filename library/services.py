"""One authorization and serialization boundary for APIs and server-rendered pages."""
import hashlib
import json
import math
import unicodedata
import uuid
from pathlib import Path
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.api import DomainError
from .models import Work, Edition, Revision, Unit, Paragraph, Asset, Rights, TimingMap

FORMATS = ('reader', 'audio', 'video')
DELIVERABLE_KINDS = {'reader_package': 'reader', 'audio_chapter': 'audio', 'video': 'video'}
RAW_KINDS = {'reader_source', 'timing_map', 'rights_document'}
GRANT_SECONDS = 120
PREVIEW_CHAR_LIMIT = 1200


def canonical_bytes(value):
    return unicodedata.normalize('NFC', json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def iso(value):
    return value.isoformat().replace('+00:00', 'Z') if value else None


def local_fixtures_enabled():
    return bool(getattr(settings,'LOCAL',False) and getattr(settings, 'MAISON_LOCAL_FIXTURES', False))


def asset_path(key):
    root = Path(settings.MEDIA_ROOT).resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root):
        raise DomainError('invalid_storage_key', 'Invalid content locator.', 400)
    return path


def _revision(value):
    if isinstance(value, Revision):
        # Re-fetch authorization authority; callers cannot retain an old live/rights state.
        value = value.pk
    try:
        return Revision.objects.select_related('edition', 'edition__work').get(pk=value)
    except (Revision.DoesNotExist, ValueError, ValidationError):
        raise DomainError('not_found', 'Edition revision not found.', 404)


def current_right(revision, format='reader', action='read', territory='IN', at=None):
    at = at or timezone.now()
    grants = Rights.objects.filter(revision=revision, format=format, action=action, approved=True,
                                   starts_at__lte=at, ends_at__gt=at).order_by('-ends_at')
    for right in grants:
        if right.test_only and not local_fixtures_enabled():
            continue
        if not isinstance(right.territories,list) or not right.territories or any(not isinstance(t,str) or (t!='*' and (len(t)!=2 or not t.isupper() or not t.isalpha())) for t in right.territories):
            continue
        if territory.upper() in right.territories or '*' in right.territories:
            return right
    return None


def _live(revision):
    return revision.state == 'live' and revision.edition.live_revision_id == revision.id


def check_revision_rights(revision,format='reader',action='read',territory='IN'):
    """Internal billing pre-fulfilment boundary. Does not itself grant member access."""
    revision=_revision(revision)
    if format not in FORMATS or action not in {'read','download'} or revision.access_policy.get(format,'deny') not in {'free','paid'}:
        raise DomainError('access_denied','This format/action is not offered.',403)
    if not _live(revision): raise DomainError('content_unavailable','This revision is not currently published.',404)
    if not current_right(revision,format,'read',territory): raise DomainError('rights_unavailable','Rights are unavailable.',403)
    if action=='download' and (format=='video' or revision.download_policy.get(format) is not True or not current_right(revision,format,'download',territory)):
        raise DomainError('download_not_permitted','Offline access is not permitted.',403)
    return revision


def authorize_purchase(user,revision,format='reader',territory='IN'):
    if not getattr(user,'is_authenticated',False) or not getattr(user,'is_active',False): raise DomainError('authentication_required','Sign in to continue.',401)
    if not getattr(user,'is_verified',False): raise DomainError('verification_required','Verify your account.',403)
    return check_revision_rights(revision,format,territory=territory)


def can_review_draft(user, revision):
    return bool(revision and revision.state=='draft' and user and user.is_authenticated and user.is_active
                and user.is_verified and user.is_staff and user.has_perm('library.publish_revision'))


def reviewable_edition(edition, user):
    if not edition.live_revision_id:
        revision=edition.revisions.filter(state='draft').order_by('-created_at').first()
        if can_review_draft(user,revision):
            # Private in-memory preview only. Never save/assign the persisted live pointer.
            edition.live_revision=revision
    return edition


def authorize_revision(user, revision, format='reader', action='read', territory='IN'):
    revision = _revision(revision)
    if not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        raise DomainError('authentication_required', 'Sign in to open the full edition.', 401)
    if not getattr(user, 'is_verified', False):
        raise DomainError('verification_required', 'Verify your email before opening this edition.', 403)
    if format not in FORMATS or action not in {'read','download'}:
        raise DomainError('access_denied', 'This content action is not available.', 403)
    if not _live(revision) and not (format=='reader' and action=='read' and can_review_draft(user,revision)):
        raise DomainError('content_unavailable', 'This revision is not currently published.', 404)
    if not current_right(revision, format, 'read', territory):
        raise DomainError('rights_unavailable', 'This format is unavailable in this territory or rights window.', 403)
    policy = revision.access_policy.get(format, 'deny')
    if policy == 'deny':
        raise DomainError('access_denied', 'This format is not offered.', 403)
    if policy == 'paid':
        from billing.services import has_entitlement
        if not has_entitlement(user, revision, format, at=timezone.now()):
            raise DomainError('entitlement_required', 'An active entitlement is required.', 403)
    elif policy != 'free':
        raise DomainError('access_denied', 'No explicit access policy exists for this format.', 403)
    if action == 'download':
        if format == 'video' or revision.download_policy.get(format) is not True or not current_right(revision, format, 'download', territory):
            raise DomainError('download_not_permitted', 'Offline access is not permitted for this format.', 403)
    return revision


def authorized_until(user, revision, format='reader', action='read', territory='IN'):
    revision = authorize_revision(user, revision, format, action, territory)
    ends = [current_right(revision, format, 'read', territory).ends_at]
    if action == 'download':
        ends.append(current_right(revision, format, 'download', territory).ends_at)
    if revision.access_policy.get(format) == 'paid':
        # Billing exposes the actual entitlement end; never mint beyond a known paid expiry.
        from billing.services import entitlement_expires_at
        expiry = entitlement_expires_at(user, revision, format)
        if expiry:
            ends.append(expiry)
    return min(ends)


def public_ttl(revision, class_seconds=30, action='read', territory='IN'):
    """Known rights deadlines cap freshness. No stale-while-revalidate after rights expiry."""
    now = timezone.now()
    rights = [current_right(revision, fmt, action, territory, now) for fmt in FORMATS
              if revision.access_policy.get(fmt, 'deny') != 'deny']
    ends = [r.ends_at for r in rights if r]
    return max(0, min(class_seconds, math.floor((min(ends)-now).total_seconds()))) if ends else 0


def available_formats(revision, territory='IN'):
    return [f for f in FORMATS if revision.access_policy.get(f, 'deny') != 'deny'
            and current_right(revision, f, 'read', territory)
            and revision.assets.filter(state='ready',kind={'reader':'reader_package','audio':'audio_chapter','video':'video'}[f]).exists()]


def _cover(revision):
    selected=revision.validation_evidence.get('cover_pair',{}).get('front',{}).get('asset_id')
    asset = revision.assets.filter(kind='cover',state='ready',pk=selected).first() if selected else revision.assets.filter(kind='cover',state='ready').first()
    if not asset:
        return None
    base=getattr(settings,'PUBLIC_BASE_URL','http://127.0.0.1:8008' if getattr(settings,'LOCAL',False) else '').rstrip('/')
    if not base: raise DomainError('configuration_required','Public application origin is not configured.',503)
    meta=revision.validation_evidence.get('cover_pair',{}).get('front',{})
    return {'url':f'{base}/api/v1/content/covers/{asset.id}', 'width':meta.get('width',600), 'height':meta.get('height',900), 'alt':revision.title+' — cover'}


def catalog_cards(locale='en', territory='IN', query='', house='', format='', **filters):
    editions = Edition.objects.filter(locale=locale, live_revision__state='live').select_related('work','live_revision')
    if query:
        query=unicodedata.normalize('NFC',' '.join(query.split()))
        editions = editions.filter(Q(live_revision__title__icontains=query)|Q(live_revision__description__icontains=query)|
                                   Q(work__title__icontains=query)|Q(work__creators__icontains=query)|Q(work__topic__icontains=query))
    if house:
        editions = editions.filter(work__house=house)
    if filters.get('topic'):
        editions = editions.filter(work__topic=filters['topic'])
    if filters.get('level'):
        editions = editions.filter(work__level=filters['level'])
    if filters.get('author'):
        editions = editions.filter(work__creators__icontains=filters['author'])
    if filters.get('recency_days'):
        try:
            days = int(filters['recency_days'])
        except (TypeError,ValueError):
            raise DomainError('invalid_filter','Recency must be an integer number of days.',422)
        if days:
            editions = editions.filter(live_revision__published_at__gte=timezone.now()-timedelta(days=days))
    cards = []
    for edition in editions.order_by('work__title','id'):
        revision = edition.live_revision
        formats = available_formats(revision, territory)
        if not formats or (format and format not in formats):
            continue
        access = 'free' if any(revision.access_policy.get(f)=='free' for f in formats) else 'pass_required'
        access_filter='pass_required' if filters.get('access')=='paid' else filters.get('access')
        if access_filter and access_filter not in {access,'all'}:
            continue
        duration = sum(revision.units.values_list('duration_ms',flat=True).exclude(duration_ms=None))
        try:
            if filters.get('duration_min') not in (None,'') and duration < int(filters['duration_min'])*60000: continue
            if filters.get('duration_max') not in (None,'') and duration > int(filters['duration_max'])*60000: continue
        except (TypeError,ValueError):
            raise DomainError('invalid_filter','Duration bounds must be integer minutes.',422)
        cards.append({'work_id':str(edition.work_id),'edition_id':str(edition.id),'title':revision.title,
                      'subtitle':None,'creators':edition.work.creators,'locale':edition.locale,'house':edition.work.house,
                      'formats':formats,'cover':_cover(revision),'access_label':access,'availability':'available'})
    return cards


def get_edition_by_slug(slug, locale=None):
    try:
        qs=Edition.objects.select_related('live_revision','work').filter(slug=slug)
        if locale is not None: qs=qs.filter(locale=locale)
        return qs.get()
    except Edition.DoesNotExist:
        raise DomainError('not_found','Edition not found.',404)


def catalog_card(edition,territory='IN',user=None):
    if not isinstance(edition,Edition):
        try: edition=Edition.objects.get(pk=edition)
        except (Edition.DoesNotExist,ValueError,ValidationError): raise DomainError('not_found','Edition not found.',404)
    if not edition.live_revision_id and user:
        row=reviewable_edition(edition,user)
        if can_review_draft(user,row.live_revision):
            detail=edition_detail(row.id,territory,user=user)
            return {'work_id':str(row.work_id),'edition_id':str(row.id),'title':detail['title'],'subtitle':None,
                    'creators':row.work.creators,'locale':row.locale,'house':row.work.house,'formats':['reader'],
                    'cover':detail['cover'],'access_label':'free','availability':'available'}
    for card in catalog_cards(edition.locale,territory):
        if card['edition_id']==str(edition.id): return card
    raise DomainError('content_unavailable','Edition is not currently available.',404)


def edition_detail(edition_id, territory='IN', user=None):
    try:
        edition = Edition.objects.select_related('live_revision','work').get(pk=edition_id)
    except (Edition.DoesNotExist,ValueError,ValidationError):
        raise DomainError('not_found','Edition not found.',404)
    edition=reviewable_edition(edition,user)
    revision = edition.live_revision
    reviewing=can_review_draft(user,revision)
    if not revision or (not reviewing and (not _live(revision) or not available_formats(revision,territory))):
        raise DomainError('content_unavailable','Edition is not available.',404)
    formats = ['reader'] if reviewing and current_right(revision,'reader','read',territory) else available_formats(revision,territory)
    if reviewing and not formats: raise DomainError('rights_unavailable','Draft rights are unavailable.',403)
    cover=_cover(revision)
    if reviewing and cover:
        selected=revision.validation_evidence.get('cover_pair',{}).get('front',{}).get('asset_id')
        a=revision.assets.filter(kind='cover',state='ready',pk=selected).first() if selected else revision.assets.filter(kind='cover',state='ready').first()
        cover={**cover,'url':f'/api/v1/staff/draft-covers/{a.id}'}
    return {'edition_id':str(edition.id),'work_id':str(edition.work_id),'edition_revision_id':str(revision.id),
            'title':revision.title,'description':revision.description,'locale':edition.locale,'formats':formats,
            'content_sha256':revision.content_sha256,'anchor_revision':revision.anchor_revision,'cover':cover,
            'preview_available':bool(revision.preview and current_right(revision,'reader','preview',territory)),
            'downloadable_formats':[f for f in formats if revision.download_policy.get(f) is True and current_right(revision,f,'download',territory)],
            'published_at':iso(revision.published_at),'version':edition.version}


def unit_dto(unit,territory='IN'):
    kinds = set(unit.assets.filter(state='ready').values_list('kind',flat=True))
    return {'unit_id':str(unit.id),'edition_revision_id':str(unit.revision_id),'title':unit.title,'ordinal':unit.ordinal,
            'kind':unit.kind,'formats':[f for f in available_formats(unit.revision,territory)
                                     if {'reader':'reader_package','audio':'audio_chapter','video':'video'}[f] in kinds],
            'duration_ms':unit.duration_ms,'preview':unit.preview}


def edition_units(edition_id,territory='IN',user=None):
    detail = edition_detail(edition_id,territory,user=user)
    return [unit_dto(u,territory) for u in Unit.objects.filter(revision_id=detail['edition_revision_id']).select_related('revision','revision__edition')]


def paragraph_dto(paragraph):
    return {'anchor_id':str(paragraph.anchor_id),'text':paragraph.text,'kind':paragraph.kind,'ordinal':paragraph.ordinal}


def get_reader_document(user,edition_id,unit_id,territory='IN'):
    detail = edition_detail(edition_id,territory,user=user)
    revision = authorize_revision(user,detail['edition_revision_id'],territory=territory)
    try:
        unit = revision.units.get(pk=unit_id)
    except (Unit.DoesNotExist,ValueError,ValidationError):
        raise DomainError('unit_not_found','Unit does not belong to this revision.',404)
    return {'edition':detail,'unit':unit_dto(unit,territory),'paragraphs':[paragraph_dto(p) for p in unit.paragraphs.all()]}


def get_preview_document(edition_id,unit_id,territory='IN'):
    detail=edition_detail(edition_id,territory)
    revision=_revision(detail['edition_revision_id'])
    unit=revision.units.filter(pk=unit_id).first()
    first=revision.units.first()
    if not unit or not first or unit.id!=first.id or not revision.preview or not current_right(revision,'reader','preview',territory):
        raise DomainError('preview_unavailable','This unit has no bounded public preview.',404)
    paragraphs=revision.preview
    if len(paragraphs)>3 or sum(len(p['text']) for p in paragraphs)>1200:
        raise DomainError('preview_unavailable','Preview exceeds its approved bounds.',409)
    return {'edition':detail,'unit':unit_dto(unit,territory),'paragraphs':paragraphs,
            'boundary':{'end_anchor_id':paragraphs[-1]['anchor_id'],'end_offset_chars':len(paragraphs[-1]['text']),
                        'audio_end_ms':None,'video_end_ms':None},'preview':True}


def get_reader_manifest(user,revision_id,territory='IN',cursor=None):
    revision = authorize_revision(user,revision_id,territory=territory)
    units = list(revision.units.all())
    start = 0
    if cursor:
        try:
            data = signing.loads(cursor,salt='maison-manifest-cursor',max_age=3600)
            if data['revision'] != str(revision.id):
                raise ValueError()
            start = int(data['offset'])
        except (signing.BadSignature,ValueError,KeyError,TypeError):
            raise DomainError('invalid_cursor','Invalid manifest cursor.',400)
    output=[]
    for unit in units[start:start+10]:
        chunks=[{'chunk_id':str(a.id),'asset_id':str(a.id),'sha256':a.sha256,'bytes':a.bytes,
                 'compressed_bytes':a.compressed_bytes or a.bytes,'content_type':'application/json'}
                for a in unit.assets.filter(kind='reader_package',state='ready').order_by('created_at','id')]
        output.append({'unit_id':str(unit.id),'title':unit.title,'chunks':chunks})
    end = start+len(output)
    body={'schema_version':1,'edition_revision_id':str(revision.id),'content_sha256':revision.content_sha256,
          'anchor_revision':revision.anchor_revision,'locale':revision.edition.locale,'units':output,
          'next_cursor':signing.dumps({'revision':str(revision.id),'offset':end},salt='maison-manifest-cursor') if end<len(units) else None,
          'available_formats':available_formats(revision,territory),'published_at':iso(revision.published_at),
          'offline_policy':{'permitted':revision.download_policy.get('reader') is True and bool(current_right(revision,'reader','download',territory)),
                            'max_lease_seconds':86400}}
    if len(canonical_bytes(body))>65536:
        raise DomainError('manifest_too_large','Package must be split before publication.',409)
    return body


def _asset_valid(asset):
    path=asset_path(asset.storage_key)
    try:
        raw=path.read_bytes()
    except OSError:
        raise DomainError('asset_unavailable','Content bytes are unavailable.',503)
    if len(raw)!=asset.bytes or digest(raw)!=asset.sha256:
        raise DomainError('asset_integrity_failed','Content checksum verification failed.',503)
    return raw


def validate_device(user,device_id):
    from accounts.models import Device
    try:
        device = Device.objects.get(pk=device_id,user=user)
    except (Device.DoesNotExist,ValueError,ValidationError):
        raise DomainError('invalid_device','An active account device is required.',403)
    if getattr(device,'revoked_at',None) is not None or device.expires_at<=timezone.now():
        raise DomainError('device_revoked','This device has been revoked.',403)
    return device


def _asset_grant(user,asset,device_id,territory='IN'):
    format=DELIVERABLE_KINDS.get(asset.kind)
    if not format or asset.state!='ready':
        raise DomainError('asset_not_deliverable','This asset is not a deliverable output.',403)
    revision=authorize_revision(user,asset.revision,format,territory=territory)
    validate_device(user,device_id)
    _asset_valid(asset)
    now=timezone.now()
    expiry=min(now+timedelta(seconds=GRANT_SECONDS),authorized_until(user,revision,format,territory=territory))
    if expiry<=now:
        raise DomainError('rights_unavailable','Content rights have expired.',403)
    payload={'asset':str(asset.id),'user':str(user.public_id),'device':str(device_id),'revision':str(revision.id),
             'purpose':'online','territory':territory,'exp':int(expiry.timestamp())}
    token=signing.dumps(payload,salt='maison-private-asset',compress=True)
    return {'asset_id':str(asset.id),'unit_id':str(asset.unit_id) if asset.unit_id else None,
            'chunk_id':str(asset.id) if asset.kind=='reader_package' else None,'sha256':asset.sha256,'bytes':asset.bytes,
            'content_type':asset.content_type,'url':f'/api/v1/content/local-assets/{asset.id}?token={token}',
            'range_supported':asset.kind=='audio_chapter'},expiry


def package_grant(user,data,territory='IN'):
    if not getattr(settings,'LOCAL',False):
        raise DomainError('provider_not_configured','A qualified private-storage delivery adapter is required.',503)
    if data.get('purpose')!='online':
        raise DomainError('invalid_purpose','Use a download license for offline access.',400)
    revision=authorize_revision(user,data.get('edition_revision_id'),territory=territory)
    units=data.get('unit_ids',[])
    chunks=data.get('chunk_ids',[])
    if not isinstance(units,list) or not 1<=len(units)<=10 or len(set(units))!=len(units) or not isinstance(chunks,list) or len(chunks)>100:
        raise DomainError('invalid_selection','Select 1–10 distinct units and at most 100 chunks.',400)
    if revision.units.filter(pk__in=units).count()!=len(units):
        raise DomainError('unit_revision_mismatch','Every unit must belong to this revision.',409)
    assets=revision.assets.filter(unit_id__in=units,kind='reader_package',state='ready').order_by('created_at','id')
    if chunks:
        assets=assets.filter(pk__in=chunks)
        if assets.count()!=len(set(chunks)):
            raise DomainError('chunk_revision_mismatch','Every chunk must belong to the selected revision and units.',409)
    if not assets.exists() or assets.count()>100:
        raise DomainError('invalid_selection','No ready chunks, or selection exceeds 100 chunks.',400)
    grants=[_asset_grant(user,a,data.get('device_id'),territory) for a in assets]
    body={'grant_id':str(uuid.uuid4()),'edition_revision_id':str(revision.id),'issued_at':iso(timezone.now()),
          'expires_at':iso(min(g[1] for g in grants)),'purpose':'online','assets':[g[0] for g in grants]}
    if len(canonical_bytes(body))>65536:
        raise DomainError('grant_too_large','Select fewer chunks.',413)
    return body


def media_grant(user,data,territory='IN'):
    if not getattr(settings,'LOCAL',False):
        raise DomainError('provider_not_configured','A qualified private-media delivery adapter is required.',503)
    try:
        asset=Asset.objects.select_related('revision','revision__edition').get(pk=data.get('asset_id'))
    except (Asset.DoesNotExist,ValueError,ValidationError):
        raise DomainError('not_found','Asset not found.',404)
    if asset.kind not in {'audio_chapter','video'} or data.get('purpose')!='online':
        raise DomainError('asset_not_deliverable','Only online processed media can be granted.',403)
    descriptor,expiry=_asset_grant(user,asset,data.get('device_id'),territory)
    return {'grant_id':str(uuid.uuid4()),'asset_id':str(asset.id),'edition_revision_id':str(asset.revision_id),
            'transport':'local_signed','url':descriptor['url'],'issued_at':iso(timezone.now()),'expires_at':iso(expiry),
            'content_type':asset.content_type,'sha256':asset.sha256,'range_supported':descriptor['range_supported'],
            'quality_kbps':data.get('quality_kbps',96) if asset.kind=='audio_chapter' else None,
            'duration_ms':asset.unit.duration_ms if asset.unit and asset.unit.duration_ms else 1}


def resolve_signed_asset(user,asset_id,token):
    try:
        data=signing.loads(token,salt='maison-private-asset',max_age=GRANT_SECONDS)
    except signing.BadSignature:
        raise DomainError('invalid_grant','Content grant is invalid or expired.',403)
    if (data.get('asset')!=str(asset_id) or data.get('user')!=str(getattr(user,'public_id',None))
            or data.get('purpose')!='online' or data.get('exp',0)<=timezone.now().timestamp()):
        raise DomainError('invalid_grant','Content grant is invalid or expired.',403)
    validate_device(user,data.get('device'))
    try:
        asset=Asset.objects.select_related('revision','revision__edition').get(pk=asset_id,revision_id=data.get('revision'),state='ready')
    except (Asset.DoesNotExist,ValueError,ValidationError):
        raise DomainError('not_found','Asset not found.',404)
    format=DELIVERABLE_KINDS.get(asset.kind)
    if not format:
        raise DomainError('asset_not_deliverable','Private source assets cannot be delivered.',403)
    authorize_revision(user,asset.revision,format,territory=data.get('territory','IN'))
    return asset,_asset_valid(asset)


def revision_hash(revision):
    return digest(canonical_bytes([{'unit_id':str(u.id),'title':u.title,'ordinal':u.ordinal,
                                   'paragraphs':[paragraph_dto(p) for p in u.paragraphs.all()]}
                                  for u in revision.units.all()]))


def write_reader_package(unit):
    revision=unit.revision
    if revision.state!='draft':
        raise DomainError('revision_frozen','Create a draft revision to rebuild content.',409)
    asset_id=uuid.uuid4()
    body={'schema_version':1,'edition_revision_id':str(revision.id),'unit_id':str(unit.id),
          'chunk_id':str(asset_id),'anchor_revision':revision.anchor_revision,'locale':revision.edition.locale,
          'paragraphs':[paragraph_dto(p) for p in unit.paragraphs.all()]}
    raw=canonical_bytes(body)
    import gzip
    compressed=gzip.compress(raw,mtime=0)
    if len(raw)>262144 or len(compressed)>65536:
        raise DomainError('chunk_too_large','Split this unit at paragraph boundaries before packaging.',413)
    key=f'revisions/{revision.id}/{asset_id}.json'
    path=asset_path(key)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(raw)
    return Asset.objects.create(id=asset_id,revision=revision,unit=unit,kind='reader_package',state='ready',
                                storage_key=key,sha256=digest(raw),bytes=len(raw),compressed_bytes=len(compressed),content_type='application/json')


def staff_state(revision):
    return {'edition_id':str(revision.edition_id),'edition_revision_id':str(revision.id),'state':revision.state,
            'sha256':revision.content_sha256,'version':revision.version,'scheduled_for':iso(revision.scheduled_for),'updated_at':iso(revision.updated_at)}


def _reader_package_coverage(revision,ready_assets):
    """Prove complete ordered source coverage, not merely the presence of one package."""
    import gzip
    from .validation import validate_schema
    units=list(revision.units.prefetch_related('paragraphs').all())
    expected={unit.id:[paragraph_dto(p) for p in unit.paragraphs.all()] for unit in units}
    assembled={unit.id:[] for unit in units}
    packages=[asset for asset in ready_assets if asset.kind=='reader_package']
    if not units or not packages or any(not paragraphs for paragraphs in expected.values()):
        return False
    # Match manifest ordering. Each canonical paragraph must occur exactly once in that order.
    for asset in sorted(packages,key=lambda item:(item.created_at,item.id)):
        if asset.unit_id not in expected or asset.content_type!='application/json':
            return False
        try:
            raw=_asset_valid(asset)
            package=json.loads(raw)
            validate_schema(package,'ReaderChunk')
        except (DomainError,ValueError,UnicodeDecodeError):
            return False
        if (package['edition_revision_id']!=str(revision.id) or package['unit_id']!=str(asset.unit_id)
                or package['chunk_id']!=str(asset.id) or package['anchor_revision']!=revision.anchor_revision
                or package['locale']!=revision.edition.locale or raw!=canonical_bytes(package)
                or len(raw)>262144 or len(gzip.compress(raw,mtime=0))>65536):
            return False
        assembled[asset.unit_id].extend(package['paragraphs'])
    return assembled==expected


def validate_revision(revision,territory='IN'):
    revision=_revision(revision)
    checks=[]
    def add(code,ok,message): checks.append({'code':code,'status':'pass' if ok else 'fail','message':message})
    formats=[f for f in FORMATS if revision.access_policy.get(f,'deny')!='deny']
    add('rights',bool(formats) and all(current_right(revision,f,'read',territory) for f in formats),'Every offered format requires current approved rights; local-only rights require local mode.')
    add('metadata',bool(revision.title and revision.description and revision.edition.locale in {'en','bn'}),'Title, description and supported edition locale required.')
    add('text',bool(revision.units.exists()) and revision.content_sha256==revision_hash(revision),'Immutable text root must match the ordered semantic paragraphs.')
    add('anchors',bool(Paragraph.objects.filter(unit__revision=revision).exists()),'Stable paragraph anchors are required.')
    ready_assets=list(revision.assets.filter(state='ready'))
    add('cover',any(a.kind=='cover' for a in ready_assets),'A ready original cover is required.')
    integrity=True
    try:
        for asset in ready_assets: _asset_valid(asset)
    except DomainError:
        integrity=False
    for fmt in formats:
        kind={'reader':'reader_package','audio':'audio_chapter','video':'video'}[fmt]
        if not any(a.kind==kind for a in ready_assets): integrity=False
    if 'reader' in formats and not _reader_package_coverage(revision,ready_assets):
        integrity=False
    add('media',integrity and all(a.state=='ready' for a in revision.assets.all()),
        'All assets require verified bytes/checksums; every Reader unit requires complete ordered canonical packages bound to this revision, unit, chunk and anchor revision.')
    audio=revision.assets.filter(kind='audio_chapter',state='ready')
    if audio.exists():
        add('timing_map',all(revision.timing_maps.filter(asset=a,measured=True,text_sha256=revision.content_sha256,asset_sha256=a.sha256).exists() for a in audio),'Every offered audio output requires a measured hash-bound map.')
    else:
        checks.append({'code':'timing_map','status':'not_applicable','message':'Reader-only revision; no audio release implied.'})
    browser=revision.validation_evidence.get('browser',{})
    add('browser',browser.get('sha256')==revision.content_sha256 and browser.get('status')=='pass' and
        (browser.get('scope')!='local_test_only' or local_fixtures_enabled()),'Browser acceptance must bind this exact text hash and release scope.')
    return {'edition_id':str(revision.edition_id),'edition_revision_id':str(revision.id),'sha256':revision.content_sha256,
            'status':'pass' if all(c['status'] in {'pass','not_applicable'} for c in checks) else 'fail',
            'checks':checks,'validated_at':iso(timezone.now())}


@transaction.atomic
def transition_revision(user,revision_id,action,expected_version,expected_sha256,reason='',publish_at=None):
    if not user.is_active or not user.is_staff or not user.has_perm('library.publish_revision'):
        raise DomainError('permission_denied','Content publisher permission is required.',403)
    entry=Revision.objects.only('edition_id').get(pk=revision_id)
    # All publishers of one edition serialize before locking either old or new revision.
    edition=Edition.objects.select_for_update().get(pk=entry.edition_id)
    revision=Revision.objects.select_for_update().select_related('edition').get(pk=revision_id)
    if revision.version!=expected_version or revision.content_sha256!=expected_sha256:
        raise DomainError('version_conflict','Revision changed; review the current content.',412,{'current_version':revision.version})
    if action=='validate':
        return validate_revision(revision)
    if not reason.strip():
        raise DomainError('reason_required','Record a reason for this publication action.',400)
    if action in {'mark-ready','publish','schedule'}:
        report=validate_revision(revision)
        if report['status']!='pass':
            raise DomainError('publication_not_ready','Required publication checks have not passed.',409,report)
    if action=='mark-ready':
        if revision.state!='draft': raise DomainError('invalid_transition','Only drafts can be marked ready.',409)
        revision.state='ready'
    elif action in {'publish','schedule'}:
        if revision.state!='ready': raise DomainError('invalid_transition','Only ready revisions can be published or scheduled.',409)
        if action=='schedule':
            if not publish_at or publish_at<=timezone.now(): raise DomainError('invalid_schedule','Choose a future UTC publication time.',400)
            revision.scheduled_for=publish_at
        else:
            if edition.live_revision_id and edition.live_revision_id!=revision.id:
                old=Revision.objects.select_for_update().get(pk=edition.live_revision_id)
                old.state='retired';old.version+=1;old.save(update_fields=['state','version','updated_at'])
            revision.state='live';revision.published_at=timezone.now();revision.scheduled_for=None
            # The cross-row FK guard requires the pointed-to revision to be live in this transaction.
            revision.version+=1;revision.save()
            edition.live_revision=revision;edition.version+=1;edition.full_clean();edition.save()
            return staff_state(revision)
    elif action=='withdraw':
        if revision.state!='live': raise DomainError('invalid_transition','Only live revisions can be withdrawn.',409)
        revision.state='retired';revision.scheduled_for=None
        if edition.live_revision_id==revision.id:
            edition.live_revision=None;edition.version+=1;edition.save()
    else:
        raise DomainError('invalid_action','Unknown publication action.',400)
    revision.version+=1;revision.save()
    return staff_state(revision)


@transaction.atomic
def clone_revision(source_id):
    """Fork frozen content. Each locator is new; byte copies are rehashed, packages rebuilt."""
    source=Revision.objects.select_for_update().select_related('edition').get(pk=source_id)
    clone=Revision.objects.create(edition=source.edition,title=source.title,description=source.description,
                                  anchor_revision=source.anchor_revision+1,access_policy=source.access_policy.copy(),
                                  download_policy=source.download_policy.copy(),preview=source.preview.copy())
    unit_map={};anchor_map={};asset_map={}
    for old in source.units.all():
        unit=Unit.objects.create(revision=clone,title=old.title,ordinal=old.ordinal,kind=old.kind,duration_ms=old.duration_ms,preview=old.preview)
        unit_map[old.id]=unit
        for p in old.paragraphs.all():
            new=Paragraph.objects.create(unit=unit,ordinal=p.ordinal,kind=p.kind,text=p.text)
            anchor_map[str(p.anchor_id)]=str(new.anchor_id)
    for right in source.rights.all():
        Rights.objects.create(revision=clone,format=right.format,action=right.action,territories=right.territories.copy(),
                              starts_at=right.starts_at,ends_at=right.ends_at,approved=False,test_only=right.test_only,
                              evidence='Copied for re-review; approval intentionally reset. '+right.evidence)
    for old in source.assets.exclude(kind__in=['reader_package','timing_map']):
        raw=_asset_valid(old)
        aid=uuid.uuid4();key=f'revisions/{clone.id}/{aid}';asset_map[str(old.id)]=str(aid)
        destination=asset_path(key);destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(raw)
        if digest(destination.read_bytes())!=old.sha256: raise DomainError('copy_integrity_failed','Clone copy failed checksum verification.',503)
        Asset.objects.create(id=aid,revision=clone,unit=unit_map.get(old.unit_id),kind=old.kind,state=old.state,
                             storage_key=key,sha256=old.sha256,bytes=old.bytes,content_type=old.content_type,copy_verified_bytes=len(raw))
    selected=source.validation_evidence.get('cover_pair',{})
    pair={side:{**item,'asset_id':asset_map[item['asset_id']]} for side,item in selected.items()
          if isinstance(item,dict) and item.get('asset_id') in asset_map}
    if pair:clone.validation_evidence={'cover_pair':pair}
    for unit in unit_map.values(): write_reader_package(unit)
    clone.preview=[{**p,'anchor_id':anchor_map[p['anchor_id']]} for p in source.preview if p.get('anchor_id') in anchor_map]
    clone.content_sha256=revision_hash(clone);clone.save()
    return clone
