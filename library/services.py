"""One authorization and serialization boundary for APIs and server-rendered pages."""
import hashlib
import json
import math
import re
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
from .cover_renditions import rendition_path

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


def prefetch_public_rights(revisions):
    """One complete, response-local rights snapshot; never an authorization cache.

    Callers finalizing public cache responses hold the existing generation lock.
    Authorization still re-fetches Revision via _revision and uses fresh queries.
    """
    from django.db.models import Prefetch,prefetch_related_objects
    rows=list(revisions)
    for revision in rows:
        if hasattr(revision,'_maison_public_rights'):delattr(revision,'_maison_public_rights')
    prefetch_related_objects(rows,Prefetch('rights',queryset=Rights.objects.only(
        'id','revision_id','format','action','territories','starts_at','ends_at','approved','test_only').order_by('-ends_at'),
        to_attr='_maison_public_rights'))
    return rows


def current_right(revision, format='reader', action='read', territory='IN', at=None):
    if territory.upper() not in settings.MAISON_PUBLICATION_TERRITORIES:
        return None
    at = at or timezone.now()
    grants=getattr(revision,'_maison_public_rights',None)
    if grants is None:
        grants=Rights.objects.filter(revision=revision,format=format,action=action,approved=True,
            starts_at__lte=at,ends_at__gt=at).order_by('-ends_at')
    for right in grants:
        if right.format!=format or right.action!=action or not right.approved or not right.starts_at<=at<right.ends_at:
            continue
        if right.test_only and not local_fixtures_enabled():
            continue
        if not isinstance(right.territories,list) or not right.territories or any(not isinstance(t,str) or (t!='*' and (len(t)!=2 or not t.isupper() or not t.isalpha())) for t in right.territories):
            continue
        if territory.upper() in right.territories or '*' in right.territories:
            return right
    return None


def _live(revision):
    return revision.state == 'live' and revision.edition.live_revision_id == revision.id


def free_access_for_revision(revision):
    """The free rollout changes price access only, never publication or rights."""
    return bool(getattr(settings,'FREE_ACCESS_ENABLED',False) and _live(revision))


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
                and user.is_verified and user.is_staff and user.has_perm('library.publish_revision')
                and (not getattr(settings,'STAFF_MFA_REQUIRED',not settings.LOCAL) or getattr(user,'staff_mfa_verified',False)))


def reviewable_edition(edition, user):
    if not edition.live_revision_id:
        revision=edition.revisions.filter(state='draft').order_by('-created_at').first()
        if can_review_draft(user,revision):
            # Private in-memory preview only. Never save/assign the persisted live pointer.
            edition.live_revision=revision
    return edition


def authorize_revision(user, revision, format='reader', action='read', territory='IN'):
    """Fresh fetch, then the single access check (LLD 6)."""
    revision = _revision(revision)
    prefetch_public_rights([revision])
    return _check_access(user, revision, format, action, territory)


def authorize_revisions(user, revision_ids, format='reader', action='read', territory='IN'):
    """Batch form for lists: one fresh fetch and one rights query; returns {revision_id: allowed}."""
    revisions=list(Revision.objects.select_related('edition','edition__work').filter(pk__in=set(revision_ids)))
    prefetch_public_rights(revisions)
    allowed={}
    for revision in revisions:
        try:_check_access(user,revision,format,action,territory);allowed[revision.pk]=True
        except DomainError:allowed[revision.pk]=False
    return allowed


def _check_access(user, revision, format='reader', action='read', territory='IN'):
    if not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        raise DomainError('authentication_required', 'Sign in to open the full edition.', 401)
    if not getattr(user, 'is_verified', False):
        raise DomainError('verification_required', 'Verify your email before opening this edition.', 403)
    if format not in FORMATS or action not in {'read','download'}:
        raise DomainError('access_denied', 'This content action is not available.', 403)
    if not _live(revision) and not (format in {'reader','video'} and action=='read' and can_review_draft(user,revision)):
        raise DomainError('content_unavailable', 'This revision is not currently published.', 404)
    if not current_right(revision, format, 'read', territory):
        raise DomainError('rights_unavailable', 'This format is unavailable in this territory or rights window.', 403)
    policy = revision.access_policy.get(format, 'deny')
    if policy == 'deny':
        raise DomainError('access_denied', 'This format is not offered.', 403)
    if policy == 'paid' and not free_access_for_revision(revision):
        from billing.services import has_entitlement
        if not has_entitlement(user, revision, format, at=timezone.now()):
            raise DomainError('entitlement_required', 'An active entitlement is required.', 403)
    elif policy not in {'free','paid'}:
        raise DomainError('access_denied', 'No explicit access policy exists for this format.', 403)
    if action == 'download':
        if format == 'video' or revision.download_policy.get(format) is not True or not current_right(revision, format, 'download', territory):
            raise DomainError('download_not_permitted', 'Offline access is not permitted for this format.', 403)
    return revision


def authorized_until(user, revision, format='reader', action='read', territory='IN'):
    revision = authorize_revision(user, revision, format, action, territory)
    return access_ends(user, revision, format, action, territory)


def access_ends(user, revision, format='reader', action='read', territory='IN'):
    """Earliest known end of an access that authorize_revision already allowed."""
    ends = [current_right(revision, format, 'read', territory).ends_at]
    if action == 'download':
        ends.append(current_right(revision, format, 'download', territory).ends_at)
    if revision.access_policy.get(format) == 'paid' and not free_access_for_revision(revision):
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


FORMAT_ASSETS = {format: (kind, 'stream' if format == 'video' else 'r2') for kind, format in DELIVERABLE_KINDS.items()}


def prefetch_ready_assets(revisions):
    """One query for the ready deliverable and cover rows of many revisions."""
    from django.db.models import Prefetch, prefetch_related_objects
    rows=[r for r in revisions if not hasattr(r,'_maison_ready_assets')]
    # Presence/cover checks need only these columns, not storage or provider metadata.
    prefetch_related_objects(rows,Prefetch('assets',queryset=Asset.objects.filter(
        state='ready',kind__in=[*DELIVERABLE_KINDS,'cover']).only('id','revision_id','unit_id','kind','provider','sha256')
        .order_by('created_at','id'),to_attr='_maison_ready_assets'))
    return revisions


def ready_assets(revision):
    return prefetch_ready_assets([revision])[0]._maison_ready_assets


def _offered(revision, territory):
    return [f for f in FORMATS if revision.access_policy.get(f, 'deny') != 'deny' and current_right(revision, f, 'read', territory)]


def available_formats(revision, territory='IN', unit=None):
    present = {(a.kind, a.provider) for a in ready_assets(revision) if unit is None or a.unit_id == unit.pk}
    return [f for f in _offered(revision, territory) if FORMAT_ASSETS[f] in present]


def _cover(revision, path='/api/v1/content/covers/'):
    selected=revision.validation_evidence.get('cover_pair',{}).get('front',{}).get('asset_id')
    covers=[a for a in ready_assets(revision) if a.kind=='cover']
    asset=next((a for a in covers if str(a.pk)==str(selected)),None) if selected else next(iter(covers),None)
    if not asset:
        return None
    base='' if path.startswith('/api/v1/staff/') else getattr(settings,'PUBLIC_BASE_URL','http://127.0.0.1:8008' if getattr(settings,'LOCAL',False) else '').rstrip('/')
    if base=='' and not path.startswith('/api/v1/staff/'): raise DomainError('configuration_required','Public application origin is not configured.',503)
    meta=revision.validation_evidence.get('cover_pair',{}).get('front',{})
    # Public covers use the content-addressed rendition path; staff drafts keep the private bare path.
    url=f'{base}{path}{asset.id}' if path.startswith('/api/v1/staff/') else base+rendition_path(asset.id,asset.sha256)
    return {'url':url, 'width':meta.get('width',600), 'height':meta.get('height',900), 'alt':revision.title+' — cover'}


def content_locale(value=None):
    """Optional content language is independent of the English interface."""
    if value in (None,'','all'):return None
    if not isinstance(value,str) or not re.fullmatch('[a-z]{2}',value):
        raise DomainError('invalid_filter','Choose a two-letter content language or all languages.',422)
    return value


def published_content_languages(territory='IN'):
    if territory not in settings.MAISON_PUBLICATION_TERRITORIES:return []
    from .catalog_query import catalog_queryset
    published=set(catalog_queryset(None,territory).order_by().values_list('locale',flat=True).distinct())
    labels={'en':'English','bn':'Bengali'}
    return [{'code':code,'label':labels.get(code,code.upper())} for code in ['en','bn',*sorted(published-set(labels))]]


def catalog_cards(locale=None, territory='IN', query='', house='', format='', **filters):
    """Bounded Home/SSR candidates; public listing APIs use catalog_page cursors."""
    from .catalog_query import catalog_cards_bounded
    return catalog_cards_bounded(locale,territory,query,house,format,**filters)


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
    revision=edition.live_revision
    if revision and _live(revision):
        formats=available_formats(revision,territory)
        if formats:
            return {'work_id':str(edition.work_id),'edition_id':str(edition.id),'title':revision.title,
                    'subtitle':None,'creators':edition.work.creators,'locale':edition.locale,'house':edition.work.house,
                    'formats':formats,'cover':_cover(revision),
                    'access_label':'free' if free_access_for_revision(revision) or any(revision.access_policy.get(fmt)=='free' for fmt in formats) else 'pass_required',
                    'availability':'available'}
    raise DomainError('content_unavailable','Edition is not currently available.',404)


def _edition(edition_id, user=None):
    try:
        edition = Edition.objects.select_related('live_revision','work').get(pk=edition_id)
    except (Edition.DoesNotExist,ValueError,ValidationError):
        raise DomainError('not_found','Edition not found.',404)
    return reviewable_edition(edition,user)


def catalog_cards_for(editions, territory='IN', user=None):
    """{edition_id: card or None} for many editions with one catalog query.

    Authorized staff also get cards for their own unpublished review copies.
    """
    from .catalog_query import catalog_queryset, card_from_edition
    editions=list(editions)
    cards={pk:None for pk in {e.pk for e in editions}}
    if cards:
        for row in catalog_queryset(None,territory).filter(pk__in=list(cards)):cards[row.pk]=card_from_edition(row)
    if getattr(user,'is_staff',False):
        for edition in editions:
            if cards[edition.pk] is None and not edition.live_revision_id:
                try:cards[edition.pk]=catalog_card(edition,territory=territory,user=user)
                except DomainError:pass
    return cards


def edition_detail(edition_id, territory='IN', user=None):
    return _edition_detail(_edition(edition_id,user), territory, user)


def _edition_detail(edition, territory='IN', user=None):
    revision = edition.live_revision
    if revision: prefetch_public_rights([revision])
    reviewing=can_review_draft(user,revision)
    if not revision or (not reviewing and (not _live(revision) or not available_formats(revision,territory))):
        raise DomainError('content_unavailable','Edition is not available.',404)
    if reviewing:
        formats = ['reader'] if current_right(revision,'reader','read',territory) else []
        if 'video' in available_formats(revision,territory): formats.append('video')
    else:
        formats = available_formats(revision,territory)
    if reviewing and not formats: raise DomainError('rights_unavailable','Draft rights are unavailable.',403)
    cover=_cover(revision,'/api/v1/staff/draft-covers/') if reviewing else _cover(revision)
    return {'edition_id':str(edition.id),'work_id':str(edition.work_id),'edition_revision_id':str(revision.id),
            'title':revision.title,'description':revision.description,'locale':edition.locale,'formats':formats,
            'content_sha256':revision.content_sha256,'anchor_revision':revision.anchor_revision,'cover':cover,
            'preview_available':bool(revision.preview and current_right(revision,'reader','preview',territory)),
            'downloadable_formats':[f for f in formats if revision.download_policy.get(f) is True and current_right(revision,f,'download',territory)],
            'published_at':iso(revision.published_at),'version':edition.version}


def edition_translation(edition_id):
    """Translation label data for pages; kept out of edition_detail because the Edition API shape is closed."""
    row=Edition.objects.filter(pk=edition_id,translated_from__isnull=False).values('translation_method','translation_credit').first()
    return {'method':row['translation_method'],'credit':row['translation_credit']} if row else None


def unit_dto(unit,territory='IN',revision=None):
    """revision: the already-loaded revision object, so its rights/assets load once for all units."""
    revision=revision or unit.revision
    return {'unit_id':str(unit.id),'edition_revision_id':str(unit.revision_id),'title':unit.title,'ordinal':unit.ordinal,
            'kind':unit.kind,'formats':available_formats(revision,territory,unit=unit),
            'duration_ms':unit.duration_ms,'preview':unit.preview}


def edition_units(edition_id,territory='IN',user=None):
    edition=_edition(edition_id,user)
    _edition_detail(edition,territory,user)  # Same availability/reviewer gate as the edition page.
    return [unit_dto(u,territory,edition.live_revision) for u in edition.live_revision.units.all()]


def paragraph_dto(paragraph):
    return {'anchor_id':str(paragraph.anchor_id),'text':paragraph.text,'kind':paragraph.kind,'ordinal':paragraph.ordinal}


def get_reader_document(user,edition_id,unit_id,territory='IN'):
    edition=_edition(edition_id,user)
    detail=_edition_detail(edition,territory,user)
    revision=authorize_revision(user,edition.live_revision,territory=territory)
    try:
        unit = revision.units.get(pk=unit_id)
    except (Unit.DoesNotExist,ValueError,ValidationError):
        raise DomainError('unit_not_found','Unit does not belong to this revision.',404)
    return {'edition':detail,'unit':unit_dto(unit,territory,edition.live_revision),'paragraphs':[paragraph_dto(p) for p in unit.paragraphs.all()]}


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


def has_active_pass(user,at=None):
    """A Pass is an active platform-scope entitlement (Step 3.1); free grants never count as one."""
    if not getattr(user,'is_authenticated',False):return False
    from billing.models import Entitlement
    at=at or timezone.now()
    return Entitlement.objects.filter(user=user,scope='platform',status='active',revoked_at=None,valid_from__lte=at).exclude(
        source='free').filter(Q(valid_until__isnull=True)|Q(valid_until__gt=at)).exists()


def parallel_companion(user,edition_id,unit_id,territory='IN'):
    """Step 3.2: the other half of a bn/en translation pair for one unit, or None (fail closed).

    Offered only when both editions are live and readable by this member in this territory, units
    and the unit's paragraphs align one to one by ordinal and kind, and, once the free rollout ends,
    the member holds an active Pass.
    """
    if not getattr(settings,'FREE_ACCESS_ENABLED',False) and not has_active_pass(user):return None
    try:
        edition=Edition.objects.select_related('live_revision','translated_from__live_revision').get(pk=edition_id)
    except (Edition.DoesNotExist,ValueError,ValidationError):
        return None
    if edition.translated_from_id:
        candidates=[edition.translated_from]
    else:
        candidates=edition.translations.select_related('live_revision').filter(live_revision__isnull=False).exclude(
            locale=edition.locale).order_by('locale','id')
    for partner in candidates:
        companion=_aligned_companion(user,edition,partner,unit_id,territory)
        if companion:return companion
    return None


def _aligned_companion(user,edition,partner,unit_id,territory):
    try:
        details={}
        for side in (edition,partner):
            if not side.live_revision_id or not _live(side.live_revision):return None
            details[side.id]=_edition_detail(side,territory,user)
            authorize_revision(user,side.live_revision,territory=territory)
    except DomainError:
        return None
    units=list(edition.live_revision.units.all())
    partner_units=list(partner.live_revision.units.all())
    if len(units)!=len(partner_units) or any(a.kind!=b.kind for a,b in zip(units,partner_units)):return None
    index=next((i for i,u in enumerate(units) if str(u.pk)==str(unit_id)),None)
    if index is None:return None
    kinds=list(units[index].paragraphs.values_list('kind',flat=True))
    paragraphs=list(partner_units[index].paragraphs.all())
    if len(kinds)!=len(paragraphs) or any(k!=p.kind for k,p in zip(kinds,paragraphs)):return None
    translation=edition if edition.translated_from_id==partner.id else partner
    return {'edition':{'edition_id':str(partner.id),'title':details[partner.id]['title'],'locale':partner.locale},
            'unit_id':str(partner_units[index].id),'current_is_original':translation is partner,
            'translation':{'method':translation.translation_method,'credit':translation.translation_credit},
            'paragraphs':[paragraph_dto(p) for p in paragraphs]}


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
    page=units[start:start+10]
    packages=list(revision.assets.filter(kind='reader_package',state='ready',unit__in=page).order_by('created_at','id'))
    for unit in page:
        chunks=[{'chunk_id':str(a.id),'asset_id':str(a.id),'sha256':a.sha256,'bytes':a.bytes,
                 'compressed_bytes':a.compressed_bytes or a.bytes,'content_type':'application/json'}
                for a in packages if a.unit_id==unit.pk]
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
    from .storage import read_verified
    try:return read_verified(asset)
    except DomainError as exc:
        if exc.code=='asset_integrity_failed':exc.status=503
        raise


def validate_device(user,device_id):
    from accounts.models import Device
    try:
        device = Device.objects.get(pk=device_id,user=user)
    except (Device.DoesNotExist,ValueError,ValidationError):
        raise DomainError('invalid_device','An active account device is required.',403)
    if getattr(device,'revoked_at',None) is not None or device.expires_at<=timezone.now():
        raise DomainError('device_revoked','This device has been revoked.',403)
    return device


def _asset_grant(user,asset,device_id,territory='IN',*,purpose='online',license_id=None):
    """One asset: authorize, then sign. Package grants authorize once and sign many."""
    format=DELIVERABLE_KINDS.get(asset.kind)
    if not format or asset.state!='ready':
        raise DomainError('asset_not_deliverable','This asset is not a deliverable output.',403)
    if purpose not in {'online','offline'}:raise DomainError('invalid_purpose','Unsupported content grant purpose.',422)
    action='download' if purpose=='offline' else 'read'
    revision=authorize_revision(user,asset.revision,format,action=action,territory=territory)
    expiry=_grant_expiry(user,revision,format,action,device_id,territory)
    if purpose=='offline':
        from reader.download_services import validate_delivery_license
        expiry=min(expiry,validate_delivery_license(user,license_id,asset,device_id,territory).expires_at)
    return _signed_asset(user,asset,revision,device_id,expiry,territory,purpose=purpose,license_id=license_id),expiry


def _grant_expiry(user,revision,format,action,device_id,territory):
    """Device check and latest permitted expiry for an already-authorized revision."""
    validate_device(user,device_id)
    return min(timezone.now()+timedelta(seconds=GRANT_SECONDS),access_ends(user,revision,format,action,territory))


def _signed_asset(user,asset,revision,device_id,expiry,territory,*,purpose='online',license_id=None):
    from . import storage
    remote=storage.is_r2()
    if asset.kind=='video' and remote:raise DomainError('provider_not_configured','Video requires its qualified Stream adapter.',503)
    if not remote:_asset_valid(asset)
    seconds=math.floor((expiry-timezone.now()).total_seconds())
    if seconds<1:raise DomainError('rights_unavailable','Content authorization is expiring.',403)
    payload={'asset':str(asset.id),'user':str(user.public_id),'device':str(device_id),'revision':str(revision.id),
             'purpose':purpose,'license_id':str(license_id) if license_id else None,'territory':territory,'exp':int(expiry.timestamp())}
    token=signing.dumps(payload,salt='maison-private-asset',compress=True)
    url=storage.private_url(asset.storage_key,seconds,asset.content_type) if remote else f'/api/v1/content/local-assets/{asset.id}?token={token}'
    return {'asset_id':str(asset.id),'unit_id':str(asset.unit_id) if asset.unit_id else None,
            'chunk_id':str(asset.id) if asset.kind=='reader_package' else None,'sha256':asset.sha256,'bytes':asset.bytes,
            'content_type':asset.content_type,'url':url,
            'range_supported':asset.kind=='audio_chapter'}


def package_grant(user,data,territory='IN'):
    if data.get('purpose')!='online':
        raise DomainError('invalid_purpose','Use a download license for offline access.',400)
    revision=authorize_revision(user,data.get('edition_revision_id'),territory=territory)
    units=data.get('unit_ids',[])
    chunks=data.get('chunk_ids',[])
    if not isinstance(units,list) or not 1<=len(units)<=10 or len(set(units))!=len(units) or not isinstance(chunks,list) or len(chunks)>100:
        raise DomainError('invalid_selection','Select 1–10 distinct units and at most 100 chunks.',400)
    try:
        if revision.units.filter(pk__in=units).count()!=len(units):raise ValueError
        assets=revision.assets.filter(unit_id__in=units,kind='reader_package',state='ready').order_by('created_at','id')
        if chunks:assets=assets.filter(pk__in=chunks)
        assets=list(assets[:101])
    except (ValueError,ValidationError):
        raise DomainError('unit_revision_mismatch','Every unit must belong to this revision.',409)
    if chunks and len(assets)!=len(set(chunks)):
        raise DomainError('chunk_revision_mismatch','Every chunk must belong to the selected revision and units.',409)
    if not assets or len(assets)>100:
        raise DomainError('invalid_selection','No ready chunks, or selection exceeds 100 chunks.',400)
    expiry=_grant_expiry(user,revision,'reader','read',data.get('device_id'),territory)
    body={'grant_id':str(uuid.uuid4()),'edition_revision_id':str(revision.id),'issued_at':iso(timezone.now()),
          'expires_at':iso(expiry),'purpose':'online',
          'assets':[_signed_asset(user,a,revision,data.get('device_id'),expiry,territory) for a in assets]}
    if len(canonical_bytes(body))>65536:
        raise DomainError('grant_too_large','Select fewer chunks.',413)
    return body


def media_grant(user,data,territory='IN'):
    try:
        asset=Asset.objects.select_related('revision','revision__edition').get(pk=data.get('asset_id'))
    except (Asset.DoesNotExist,ValueError,ValidationError):
        raise DomainError('not_found','Asset not found.',404)
    if asset.kind not in {'audio_chapter','video'} or data.get('purpose')!='online':
        raise DomainError('asset_not_deliverable','Only online processed media can be granted.',403)
    if asset.kind=='audio_chapter':
        if not settings.FEATURES.get('audio'):raise DomainError('feature_disabled','Audio is unavailable.',503)
        prepared=prepared_audio(asset)
        if data.get('quality_kbps',prepared['quality_kbps'])!=prepared['quality_kbps']:
            raise DomainError('quality_unavailable','The requested prepared audio rendition is unavailable.',409)
    else:
        from .stream import grant
        return grant(user,asset,data.get('device_id'),territory)
    descriptor,expiry=_asset_grant(user,asset,data.get('device_id'),territory)
    from .storage import is_r2
    return {'grant_id':str(uuid.uuid4()),'asset_id':str(asset.id),'edition_revision_id':str(asset.revision_id),
            'transport':'r2_s3_presigned' if is_r2() else 'local_signed','url':descriptor['url'],'issued_at':iso(timezone.now()),'expires_at':iso(expiry),
            'content_type':asset.content_type,'sha256':asset.sha256,'range_supported':descriptor['range_supported'],
            'quality_kbps':prepared['quality_kbps'],
            'duration_ms':prepared['duration_ms']}


def resolve_signed_asset(user,asset_id,token):
    try:
        data=signing.loads(token,salt='maison-private-asset',max_age=GRANT_SECONDS)
    except signing.BadSignature:
        raise DomainError('invalid_grant','Content grant is invalid or expired.',403)
    if (data.get('asset')!=str(asset_id) or data.get('user')!=str(getattr(user,'public_id',None))
            or data.get('purpose') not in {'online','offline'} or data.get('exp',0)<=timezone.now().timestamp()):
        raise DomainError('invalid_grant','Content grant is invalid or expired.',403)
    validate_device(user,data.get('device'))
    try:
        asset=Asset.objects.select_related('revision','revision__edition').get(pk=asset_id,revision_id=data.get('revision'),state='ready')
    except (Asset.DoesNotExist,ValueError,ValidationError):
        raise DomainError('not_found','Asset not found.',404)
    format=DELIVERABLE_KINDS.get(asset.kind)
    if not format:
        raise DomainError('asset_not_deliverable','Private source assets cannot be delivered.',403)
    territory=data.get('territory','ZZ')
    authorize_revision(user,asset.revision,format,action='download' if data['purpose']=='offline' else 'read',territory=territory)
    if data['purpose']=='offline':
        from reader.download_services import validate_delivery_license
        validate_delivery_license(user,data.get('license_id'),asset,data.get('device'),territory)
    return asset,_asset_valid(asset)


def revision_hash(revision):
    return digest(canonical_bytes([{'unit_id':str(u.id),'title':u.title,'ordinal':u.ordinal,
                                   'paragraphs':[paragraph_dto(p) for p in u.paragraphs.all()]}
                                  for u in revision.units.all()]))


def prepare_reader_package(unit,paragraphs,*,asset_id=None):
    revision=unit.revision
    if revision.state!='draft':raise DomainError('revision_frozen','Create a draft revision to rebuild content.',409)
    asset_id=asset_id or uuid.uuid4()
    body={'schema_version':1,'edition_revision_id':str(revision.id),'unit_id':str(unit.id),
          'chunk_id':str(asset_id),'anchor_revision':revision.anchor_revision,'locale':revision.edition.locale,
          'paragraphs':[paragraph_dto(p) for p in paragraphs]}
    raw=canonical_bytes(body)
    import gzip
    compressed=gzip.compress(raw,mtime=0)
    if len(raw)>262144 or len(compressed)>65536:raise DomainError('chunk_too_large','Split this unit at paragraph boundaries before packaging.',413)
    key=f'revisions/{revision.id}/{asset_id}.json'
    from .storage import put_private
    put_private(key,raw,'application/json')
    return Asset(id=asset_id,revision=revision,unit=unit,kind='reader_package',state='ready',storage_key=key,
                 sha256=digest(raw),bytes=len(raw),compressed_bytes=len(compressed),content_type='application/json')


def write_reader_package(unit):
    asset=prepare_reader_package(unit,list(unit.paragraphs.all()));asset.save();return asset


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


def prepare_revision_validation(revision):
    """Verify private bytes before any publication row lock; bind the immutable DB snapshot."""
    revision=_revision(revision)
    before=revision.version
    assets=list(revision.assets.order_by('id'))
    identity=[(str(a.id),a.version,a.state,a.sha256,a.bytes,a.storage_key,a.content_type,a.provider,a.duration_ms) for a in assets]
    integrity=True
    try:
        from .storage import verify_asset
        for asset in assets:
            if asset.state=='ready':
                if asset.provider=='stream':
                    from .stream import verify_video_metadata
                    verify_video_metadata(asset,max_seconds=8)
                else:verify_asset(asset,max_seconds=8)
    except DomainError:integrity=False
    coverage=_reader_package_coverage(revision,[a for a in assets if a.state=='ready']) if revision.access_policy.get('reader','deny')!='deny' else True
    current=Revision.objects.only('version','content_sha256').get(pk=revision.pk)
    if current.version!=before or current.content_sha256!=revision.content_sha256:
        raise DomainError('version_conflict','Revision changed during private asset verification.',412,{'current_version':current.version})
    return {'revision_id':str(revision.id),'version':before,'sha256':revision.content_sha256,'assets':identity,'integrity':integrity,'coverage':coverage}


def publication_clearance_matches(revision,ready_assets,formats=None,regions=None):
    """Exact private clearance facts; no provider I/O and no inferred legal claim."""
    formats=formats if formats is not None else [fmt for fmt in FORMATS if revision.access_policy.get(fmt,'deny')!='deny']
    regions=regions if regions is not None else list(settings.MAISON_PUBLICATION_TERRITORIES)
    clearance=revision.validation_evidence.get('publication_clearance',{})
    return (isinstance(clearance,dict) and clearance.get('status')=='pass'
        and clearance.get('sha256')==revision.content_sha256
        and isinstance(clearance.get('territories'),list) and set(clearance['territories'])==set(regions)
        and len(clearance['territories'])==len(regions)
        and isinstance(clearance.get('formats'),list) and set(clearance['formats'])==set(formats)
        and clearance.get('asset_sha256')=={str(asset.id):asset.sha256 for asset in ready_assets}
        and isinstance(clearance.get('evidence_ref'),str) and bool(clearance['evidence_ref'].strip()))


def validate_revision(revision,territory='IN',*,prepared=None):
    revision=_revision(revision)
    prepared=prepared if prepared is not None else prepare_revision_validation(revision)
    identity=[(str(a.id),a.version,a.state,a.sha256,a.bytes,a.storage_key,a.content_type,a.provider,a.duration_ms) for a in revision.assets.order_by('id')]
    if prepared.get('revision_id')!=str(revision.id) or prepared.get('version')!=revision.version or prepared.get('sha256')!=revision.content_sha256 or prepared.get('assets')!=identity:
        raise DomainError('version_conflict','Revision/assets changed after private verification.',412,{'current_version':revision.version})
    checks=[]
    def add(code,ok,message): checks.append({'code':code,'status':'pass' if ok else 'fail','message':message})
    formats=[f for f in FORMATS if revision.access_policy.get(f,'deny')!='deny']
    add('rights',bool(formats) and all(current_right(revision,f,'read',territory) for f in formats),'Every offered format requires current approved rights; local-only rights require local mode.')
    fixture_only = (local_fixtures_enabled() and revision.rights.filter(approved=True).exists()
                    and not revision.rights.filter(approved=True,test_only=False).exists())
    regions = [territory] if fixture_only else list(settings.MAISON_PUBLICATION_TERRITORIES)
    region_rights = bool(formats) and bool(regions)
    audio_preview_offered=revision.assets.filter(kind='preview_audio',state='ready').exists()
    for fmt in formats:
        actions = ['read'] + (['preview'] if (fmt=='reader' and revision.preview) or (fmt=='audio' and audio_preview_offered) else [])
        if revision.download_policy.get(fmt) is True: actions.append('download')
        for region in regions:
            for action in actions:
                right = current_right(revision,fmt,action,region)
                if not right or (not fixture_only and right.test_only): region_rights = False
    add('publication_regions',region_rights,'Every offered format/action requires current rights across the complete active whitelist; synthetic fixtures prove only their local test scope.')
    add('metadata',bool(revision.title and revision.description and revision.edition.locale in {'en','bn'}),'Title, description and supported edition locale required.')
    add('text',bool(revision.units.exists()) and revision.content_sha256==revision_hash(revision),'Immutable text root must match the ordered semantic paragraphs.')
    add('anchors',bool(Paragraph.objects.filter(unit__revision=revision).exists()),'Stable paragraph anchors are required.')
    ready_assets=list(revision.assets.filter(state='ready'))
    add('cover',any(a.kind=='cover' for a in ready_assets),'A ready original cover is required.')
    clearance = revision.validation_evidence.get('publication_clearance',{})
    if fixture_only:
        checks.append({'code':'publication_clearance','status':'not_applicable','message':'Synthetic local fixture only; no commercial legal clearance is implied.'})
    else:
        clearance_ok = publication_clearance_matches(revision,ready_assets,formats,regions)
        add('publication_clearance',clearance_ok,'Private exact-text/asset legal evidence must cover all whitelisted regions and offered formats, including applicable distribution permissions; draft term research is insufficient.')
    integrity=prepared['integrity']
    for fmt in formats:
        kind={'reader':'reader_package','audio':'audio_chapter','video':'video'}[fmt]
        if not any(a.kind==kind and a.provider==('stream' if fmt=='video' else 'r2') for a in ready_assets):integrity=False
    if 'reader' in formats and not prepared['coverage']:
        integrity=False
    add('media',integrity and all(a.state=='ready' for a in revision.assets.all()),
        'All assets require verified private bytes/checksums or exact signed Stream metadata; every Reader unit requires complete canonical revision/unit/chunk/anchor packages.')
    clips=list(revision.assets.filter(kind='preview_audio',state='ready'))
    if clips:
        from .audio_preview import prepared_clip
        sample_ok=len(clips)==1 and 'audio' in formats
        for clip in clips:
            clip.revision=revision
            try:prepared_clip(clip)
            except DomainError:sample_ok=False
        add('audio_preview',sample_ok,'Only one physically separate bounded audio sample with exact measurement evidence may be offered.')
    audio=revision.assets.filter(kind='audio_chapter',state='ready')
    if audio.exists():
        from .timing import validated_segments
        mapped=True
        for asset in audio:
            valid=False
            for mapping in revision.timing_maps.filter(asset=asset,measured=True,text_sha256=revision.content_sha256,asset_sha256=asset.sha256).select_related('asset','asset__unit','asset__revision','revision'):
                try:validated_segments(mapping);valid=True;break
                except DomainError:continue
            if not valid:mapped=False
        add('timing_map',mapped,'Every offered audio output requires exact prepared rendition evidence and a complete measured hash-bound map.')
    else:
        checks.append({'code':'timing_map','status':'not_applicable','message':'Reader-only revision; no audio release implied.'})
    browser=revision.validation_evidence.get('browser',{})
    add('browser',browser.get('sha256')==revision.content_sha256 and browser.get('status')=='pass' and
        (browser.get('scope')!='local_test_only' or local_fixtures_enabled()),'Browser acceptance must bind this exact text hash and release scope.')
    return {'edition_id':str(revision.edition_id),'edition_revision_id':str(revision.id),'sha256':revision.content_sha256,
            'status':'pass' if all(c['status'] in {'pass','not_applicable'} for c in checks) else 'fail',
            'checks':checks,'validated_at':iso(timezone.now())}


def transition_revision(user,revision_id,action,expected_version,expected_sha256,reason='',publish_at=None,*,prepared=None):
    if not user.is_active or not user.is_staff or not user.has_perm('library.publish_revision'):
        raise DomainError('permission_denied','Content publisher permission is required.',403)
    if action in {'validate','mark-ready','publish','schedule'} and prepared is None:
        prepared=prepare_revision_validation(revision_id)
    return _transition_revision(user,revision_id,action,expected_version,expected_sha256,reason,publish_at,prepared=prepared)


@transaction.atomic
def _transition_revision(user,revision_id,action,expected_version,expected_sha256,reason='',publish_at=None,*,prepared=None):
    if not user.is_active or not user.is_staff or not user.has_perm('library.publish_revision'):
        raise DomainError('permission_denied','Content publisher permission is required.',403)
    entry=Revision.objects.only('edition_id').get(pk=revision_id)
    # All publishers of one edition serialize before locking either old or new revision.
    edition=Edition.objects.select_for_update().get(pk=entry.edition_id)
    revision=Revision.objects.select_for_update().select_related('edition').get(pk=revision_id)
    if revision.version!=expected_version or revision.content_sha256!=expected_sha256:
        raise DomainError('version_conflict','Revision changed; review the current content.',412,{'current_version':revision.version})
    if action=='validate':
        return validate_revision(revision,prepared=prepared)
    if not reason.strip():
        raise DomainError('reason_required','Record a reason for this publication action.',400)
    if action in {'mark-ready','publish','schedule'}:
        report=validate_revision(revision,prepared=prepared)
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
            from .search import refresh_revision_search
            refresh_revision_search(revision)
            queue_catalog_purge(revision)
            return staff_state(revision)
    elif action=='withdraw':
        if revision.state!='live': raise DomainError('invalid_transition','Only live revisions can be withdrawn.',409)
        revision.state='retired';revision.scheduled_for=None
        if edition.live_revision_id==revision.id:
            edition.live_revision=None;edition.version+=1;edition.save()
    else:
        raise DomainError('invalid_action','Unknown publication action.',400)
    revision.version+=1;revision.save()
    if action=='schedule':
        from core.models import OutboxJob
        OutboxJob.objects.create(kind='scheduled_publication',actor=user,
            dedupe_key=f'scheduled-publication:{revision.id}:{revision.version}',not_before=revision.scheduled_for,
            payload={'actor_id':str(user.pk),'revision_id':str(revision.id),'expected_version':revision.version,
                'expected_sha256':revision.content_sha256,'scheduled_for':iso(revision.scheduled_for),'reason':reason})
    if action=='withdraw':queue_catalog_purge(revision)
    return staff_state(revision)


def clone_revision(source_id):
    """Prepare copies outside locks, then atomically persist the exact unchanged source snapshot."""
    source=Revision.objects.select_related('edition').get(pk=source_id)
    if source.assets.filter(provider='stream').exists():
        raise DomainError('stream_reimport_required','Prepare a separately approved Stream asset for the new revision.',409)
    source_version=source.version
    clone=Revision(id=uuid.uuid4(),edition=source.edition,title=source.title,description=source.description,
                   anchor_revision=source.anchor_revision+1,access_policy=source.access_policy.copy(),
                   download_policy=source.download_policy.copy())
    unit_map={};anchor_map={};asset_map={};paragraphs=[];assets=[];units=[];content=[]
    for old in source.units.prefetch_related('paragraphs').all():
        unit=Unit(id=uuid.uuid4(),revision=clone,title=old.title,ordinal=old.ordinal,kind=old.kind,duration_ms=old.duration_ms,preview=old.preview)
        units.append(unit);unit_map[old.id]=unit;unit_paragraphs=[]
        for original in old.paragraphs.all():
            paragraph=Paragraph(id=uuid.uuid4(),anchor_id=uuid.uuid4(),unit=unit,ordinal=original.ordinal,kind=original.kind,text=original.text)
            paragraphs.append(paragraph);unit_paragraphs.append(paragraph);anchor_map[str(original.anchor_id)]=str(paragraph.anchor_id)
        assets.append(prepare_reader_package(unit,unit_paragraphs))
        content.append({'unit_id':str(unit.id),'title':unit.title,'ordinal':unit.ordinal,'paragraphs':[paragraph_dto(p) for p in unit_paragraphs]})
    from .storage import copy_verified
    for old in source.assets.exclude(kind__in=['reader_package','timing_map']):
        if old.state!='ready':raise DomainError('source_asset_not_ready','Finish source uploads before cloning this revision.',409)
        if old.provider=='stream':raise DomainError('stream_reimport_required','Prepare a separately approved Stream asset for the new revision.',409)
        aid=uuid.uuid4();key=f'revisions/{clone.id}/{aid}';asset_map[str(old.id)]=str(aid)
        copy_verified(old,key)
        assets.append(Asset(id=aid,revision=clone,unit=unit_map.get(old.unit_id),kind=old.kind,state='ready',storage_key=key,
                            sha256=old.sha256,bytes=old.bytes,content_type=old.content_type,copy_verified_bytes=old.bytes,provider=old.provider,duration_ms=old.duration_ms))
    selected=source.validation_evidence.get('cover_pair',{})
    pair={side:{**item,'asset_id':asset_map[item['asset_id']]} for side,item in selected.items()
          if isinstance(item,dict) and item.get('asset_id') in asset_map}
    clone.validation_evidence={'cover_pair':pair} if pair else {}
    clone.preview=[{**p,'anchor_id':anchor_map[p['anchor_id']]} for p in source.preview if p.get('anchor_id') in anchor_map]
    clone.content_sha256=digest(canonical_bytes(content))
    rights=list(source.rights.all())
    with transaction.atomic():
        Edition.objects.select_for_update().get(pk=source.edition_id)
        current=Revision.objects.select_for_update().get(pk=source.id)
        if current.version!=source_version or current.state!=source.state:
            raise DomainError('version_conflict','Source changed while preparing private copies. Review the current revision.',412)
        clone.save();Unit.objects.bulk_create(units);Paragraph.objects.bulk_create(paragraphs);Asset.objects.bulk_create(assets)
        Rights.objects.bulk_create([Rights(revision=clone,format=right.format,action=right.action,territories=right.territories.copy(),
            starts_at=right.starts_at,ends_at=right.ends_at,approved=False,test_only=right.test_only,
            evidence='Copied for re-review; approval intentionally reset. '+right.evidence) for right in rights])
    clone.refresh_from_db()
    return clone


def queue_catalog_purge(revision):
    from operations.cache import queue_catalog_purge as enqueue_recorded_urls
    return enqueue_recorded_urls(revision)


def prepared_audio(asset):
    data=asset.revision.validation_evidence.get('media_assets',{}).get(str(asset.id),{})
    if (asset.kind!='audio_chapter' or asset.provider!='r2' or asset.state!='ready' or not asset.unit_id or not isinstance(data,dict)
        or data.get('sha256')!=asset.sha256 or data.get('unit_id')!=str(asset.unit_id)
        or data.get('prepared') is not True or not data.get('measurement_evidence')
        or type(data.get('duration_ms'))!=int or data['duration_ms']<1 or data['duration_ms']!=asset.unit.duration_ms
        or (asset.duration_ms is not None and data['duration_ms']!=asset.duration_ms)
        or data.get('quality_kbps') not in {48,96}):
        raise DomainError('media_not_ready','Audio requires exact prepared rendition and measured duration evidence.',409)
    return data


def media_chapters(user,revision_id,territory='IN'):
    if not settings.FEATURES.get('audio'):return []
    revision=authorize_revision(user,revision_id,'audio',territory=territory)
    result=[]
    for asset in revision.assets.filter(kind='audio_chapter',state='ready').select_related('unit','revision').order_by('unit__ordinal','id'):
        try:data=prepared_audio(asset)
        except DomainError:continue
        result.append({'asset_id':str(asset.id),'unit_id':str(asset.unit_id),'duration_ms':data['duration_ms'],
                       'sha256':asset.sha256,'quality_kbps':data['quality_kbps'],'title':asset.unit.title})
    return result
