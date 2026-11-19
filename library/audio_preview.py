"""Physically separate bounded audio samples; never a full-chapter grant.

Actual clips require retained measurement and exact publication/delivery evidence.
Fixture metadata proves code behavior only, never real media or legal acceptance.
"""
import math
from datetime import timedelta
from urllib.parse import urlencode
from django.conf import settings
from django.http import HttpResponse
from django.core.exceptions import ValidationError
from django.utils import timezone
from core.api import DomainError
from .models import Asset

MAX_DURATION_MS=120000
MAX_BYTES=2*1024*1024


def prepared_clip(asset):
    proof=asset.revision.validation_evidence.get('audio_preview',{})
    if (asset.kind!='preview_audio' or asset.provider!='r2' or asset.state!='ready' or not asset.unit_id
        or type(asset.duration_ms)!=int or not 1<=asset.duration_ms<=MAX_DURATION_MS
        or not 0<asset.bytes<=MAX_BYTES or asset.content_type!='audio/mpeg' or not isinstance(proof,dict)
        or proof.get('asset_id')!=str(asset.id) or proof.get('unit_id')!=str(asset.unit_id)
        or proof.get('sha256')!=asset.sha256 or proof.get('duration_ms')!=asset.duration_ms
        or proof.get('quality_kbps') not in {48,96} or proof.get('prepared') is not True
        or not isinstance(proof.get('measurement_evidence'),str) or not proof['measurement_evidence'].strip()):
        raise DomainError('preview_not_ready','No independently prepared bounded audio sample is available.',409)
    return proof


def _authority(revision,territory,asset_id=None):
    from . import services as svc
    if not settings.FEATURES.get('audio'):
        raise DomainError('preview_unavailable','Audio samples are unavailable.',404)
    revision=svc._revision(revision)
    if not svc._live(revision) or revision.access_policy.get('audio','deny')=='deny':
        raise DomainError('preview_unavailable','This revision has no released audio sample.',404)
    proof=revision.validation_evidence.get('audio_preview',{})
    selected=asset_id or (proof.get('asset_id') if isinstance(proof,dict) else None)
    try:asset=revision.assets.select_related('unit').get(pk=selected,kind='preview_audio',state='ready')
    except (Asset.DoesNotExist,ValueError,ValidationError):
        raise DomainError('preview_unavailable','Audio sample not found.',404)
    asset.revision=revision;proof=prepared_clip(asset)
    now=timezone.now()
    svc.prefetch_public_rights([revision])
    fixture_only=(svc.local_fixtures_enabled() and any(row.approved for row in revision._maison_public_rights)
        and not any(row.approved and not row.test_only for row in revision._maison_public_rights))
    regions=[territory] if fixture_only else list(settings.MAISON_PUBLICATION_TERRITORIES)
    if territory not in settings.MAISON_PUBLICATION_TERRITORIES or not regions:
        raise DomainError('region_unavailable','This region has no qualified preview delivery.',403)
    deadlines=[]
    for region in regions:
        right=svc.current_right(revision,'audio','preview',region,at=now)
        if not right or (not fixture_only and right.test_only):
            raise DomainError('preview_rights_unavailable','Current sample delivery rights are incomplete.',403)
        deadlines.append(right.ends_at)
    if not fixture_only:
        ready=list(revision.assets.filter(state='ready'))
        if not svc.publication_clearance_matches(revision,ready):
            raise DomainError('preview_clearance_unavailable','Exact sample publication/delivery clearance is incomplete.',403)
    return revision,asset,proof,min([now+timedelta(seconds=120),*deadlines])


def descriptor(revision,territory):
    from . import services as svc
    try:revision,asset,proof,_=_authority(revision,territory)
    except DomainError:return None
    base=settings.PUBLIC_BASE_URL.rstrip('/')
    return {'asset_id':str(asset.id),'edition_revision_id':str(revision.id),'unit_id':str(asset.unit_id),
        'url':base+f'/api/v1/content/audio-previews/{asset.id}?'+urlencode({'locale':revision.edition.locale,'territory':territory}),
        'sha256':asset.sha256,'bytes':asset.bytes,'content_type':asset.content_type,
        'duration_ms':asset.duration_ms,'quality_kbps':proof['quality_kbps']}


def deliver(request,asset_id,territory):
    from . import services as svc,storage
    try:asset=Asset.objects.only('revision_id').get(pk=asset_id,kind='preview_audio')
    except Asset.DoesNotExist:raise DomainError('preview_unavailable','Audio sample not found.',404)
    _,asset,_,expiry=_authority(asset.revision_id,territory,asset_id)
    if storage.is_r2():
        seconds=math.floor((expiry-timezone.now()).total_seconds())
        if seconds<1:raise DomainError('preview_rights_unavailable','Sample delivery rights are expiring.',403)
        response=HttpResponse(status=307)
        response['Location']=storage.private_url(asset.storage_key,seconds,asset.content_type)
    else:
        # A test-only local transport for the same separate bounded object.
        raw=svc._asset_valid(asset);total=len(raw);status=200
        requested=request.headers.get('Range')
        if requested:
            import re
            match=re.fullmatch(r'bytes=([0-9]{1,10})-([0-9]{0,10})',requested)
            start=int(match[1]) if match else total
            end=int(match[2]) if match and match[2] else total-1
            if start>end or start>=total or end>=total:
                response=HttpResponse(status=416);response['Content-Range']=f'bytes */{total}'
                response['Cache-Control']='private, no-store';return response
            raw=raw[start:end+1];status=206
        response=HttpResponse(raw,status=status,content_type='audio/mpeg')
        response['Content-Length']=str(len(raw));response['Accept-Ranges']='bytes'
        if status==206:response['Content-Range']=f'bytes {start}-{end}/{total}'
    response['Cache-Control']='private, no-store'
    response['Referrer-Policy']='no-referrer';response['X-Content-Type-Options']='nosniff'
    return response
