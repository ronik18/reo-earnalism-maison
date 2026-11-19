"""Bounded offline grants using the same current authorization as online delivery."""
import hashlib
import json
import uuid
from urllib.parse import urljoin
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.core import signing
from django.utils import timezone
from core.api import DomainError,public_uuid
from core.services import apply_operation,audit
from library.models import Asset,Revision
from library.services import authorize_revision,current_right,validate_device,canonical_bytes,free_access_for_revision
from .models import DownloadLicense
from .services import iso


def _enabled():
    if not getattr(settings,'FEATURES',{}).get('offline_text_audio',False):
        raise DomainError('feature_disabled','Offline text/audio is not enabled.',409)


def _owned(user,device_id,license_id,lock=False):
    device=validate_device(user,device_id)
    rows=DownloadLicense.objects.select_related('revision__edition','device','entitlement','rights_record')
    if lock:rows=rows.select_for_update(of=('self',))
    row=rows.filter(pk=public_uuid(license_id,'license_id'),user=user,device=device).first()
    if not row:raise DomainError('not_found','Download license not found for this device.',404)
    return row


def _status(row):
    now=timezone.now()
    if row.revoked_at or row.device.revoked_at or row.entitlement.revoked_at or row.entitlement.status!='active':return 'revoked'
    if row.expires_at<=now or row.device.expires_at<=now or row.entitlement.valid_from>now or (row.entitlement.valid_until and row.entitlement.valid_until<=now):return 'expired'
    expected=row.manifest.get('assets',[])
    if Asset.objects.filter(pk__in=[item['asset_id'] for item in expected],revision=row.revision,state='ready').count()!=len(expected):
        now=timezone.now();DownloadLicense.objects.filter(pk=row.pk,revoked_at=None).update(revoked_at=now);row.revoked_at=now
        return 'revoked'
    try:authorize_revision(row.user,row.revision,row.format,'download',row.territory)
    except DomainError:
        now=timezone.now();DownloadLicense.objects.filter(pk=row.pk,revoked_at=None).update(revoked_at=now);row.revoked_at=now
        return 'revoked'
    return 'active'


def validate_delivery_license(user,license_id,asset,device_id,territory):
    """Called again by the media adapter when minting/resolving a URL."""
    _enabled()
    row=_owned(user,device_id,license_id)
    if row.format=='audio' and not getattr(settings,'FEATURES',{}).get('audio',False):
        raise DomainError('feature_disabled','Audio is not enabled.',409)
    if _status(row)!='active' or row.territory!=territory or row.revision_id!=asset.revision_id:
        raise DomainError('license_inactive','This offline license is no longer active.',403)
    if hashlib.sha256(canonical_bytes(row.manifest)).hexdigest()!=row.manifest_sha256:
        raise DomainError('license_integrity_failed','Request a new download.',409)
    bound=next((a for a in row.manifest['assets'] if a['asset_id']==str(asset.id)),None)
    if not bound or bound['sha256']!=asset.sha256 or bound['bytes']!=asset.bytes:
        raise DomainError('license_asset_mismatch','This asset is not part of the license.',403)
    return row


def _serialize(row,urls=True):
    status=_status(row);assets=[]
    if urls and status=='active':
        from library.services import _asset_grant
        for bound in row.manifest['assets']:
            asset=Asset.objects.select_related('revision__edition','unit').filter(pk=bound['asset_id'],revision=row.revision,state='ready').first()
            if not asset:
                DownloadLicense.objects.filter(pk=row.pk,revoked_at=None).update(revoked_at=timezone.now())
                raise DomainError('license_inactive','A downloaded asset is no longer available.',409)
            validate_delivery_license(row.user,row.id,asset,row.device_id,row.territory)
            descriptor,expiry=_asset_grant(row.user,asset,row.device_id,row.territory,purpose='offline',license_id=str(row.id))
            piece=None
            if bound.get('piece_manifest'):
                from library import storage
                prepared=bound['piece_manifest'];seconds=min(120,int((row.expires_at-timezone.now()).total_seconds()))
                if seconds<1:raise DomainError('license_inactive','Renew this expired license.',409)
                piece_url=storage.private_url(prepared['storage_key'],seconds,'application/json') if storage.is_r2() else _local_piece_url(row,asset,seconds)
                piece={'url':piece_url,'url_expires_at':iso(min(expiry,row.expires_at)),
                       'sha256':prepared['sha256'],'bytes':prepared['bytes']}
            assets.append({'asset_id':str(asset.id),'unit_id':str(asset.unit_id),'sha256':asset.sha256,'bytes':asset.bytes,
                'content_type':asset.content_type,'url':urljoin(getattr(settings,'PUBLIC_BASE_URL','http://127.0.0.1:8008'),descriptor['url']),'url_expires_at':iso(min(expiry,row.expires_at)),'piece_manifest':piece})
    return {'license_id':str(row.id),'edition_revision_id':str(row.revision_id),'content_sha256':row.revision.content_sha256,
        'anchor_revision':row.revision.anchor_revision,'device_id':str(row.device_id),'format':row.format,'unit_ids':row.unit_ids,
        'status':status,'issued_at':iso(row.issued_at),'valid_until':iso(row.expires_at),'last_validated_at':iso(timezone.now()),
        'assets':assets,'bytes_total':row.manifest['bytes_total']}


def _create(user,device_id,data,territory):
    from accounts.models import Device
    from billing.services import ensure_free_entitlement,_eligible
    device=Device.objects.select_for_update().get(pk=validate_device(user,device_id).pk)
    if str(data.get('device_id'))!=str(device.id):raise DomainError('device_mismatch','Use the current session device.',403)
    fmt=data.get('format')
    if fmt not in ['reader','audio']:raise DomainError('download_not_permitted','Only eligible text/audio can be downloaded.',403)
    if fmt=='audio' and not getattr(settings,'FEATURES',{}).get('audio',False):
        raise DomainError('feature_disabled','Audio is not enabled.',409)
    revision=authorize_revision(user,data.get('edition_revision_id'),fmt,'download',territory)
    # No staff draft download exception: offline always binds a public release.
    if revision.state!='live' or revision.edition.live_revision_id!=revision.id:raise DomainError('content_unavailable','Only a released revision can be downloaded.',404)
    units=data.get('unit_ids')
    if not isinstance(units,list) or not 1<=len(units)<=10:raise DomainError('validation_error','Select1–10 units.',422)
    units=[str(public_uuid(u,'unit_id')) for u in units]
    if len(set(units))!=len(units) or revision.units.filter(pk__in=units).count()!=len(units):raise DomainError('unit_revision_mismatch','Choose distinct units from this revision.',409)
    right=current_right(revision,fmt,'download',territory)
    right=type(right).objects.select_for_update().get(pk=right.pk)
    if revision.access_policy.get(fmt)=='free' or free_access_for_revision(revision):entitlement=ensure_free_entitlement(user,revision,fmt,territory=territory)
    else:
        candidates=[e for e in _eligible(user,revision,fmt,timezone.now()).select_for_update() if fmt in e.formats]
        if not candidates:raise DomainError('entitlement_required','An active entitlement is required.',403)
        entitlement=max(candidates,key=lambda e:e.valid_until or timezone.now()+timedelta(days=36500))
    kind='reader_package' if fmt=='reader' else 'audio_chapter'
    assets=list(revision.assets.filter(unit_id__in=units,kind=kind,state='ready').order_by('unit__ordinal','created_at','id'))
    if not assets or len(assets)>100 or {str(a.unit_id) for a in assets}!=set(units):raise DomainError('invalid_selection','Select complete bounded units with ready assets.',409)
    prepared_manifests={}
    if fmt=='audio':
        from library import storage
        from library.validation import validate_schema
        for asset in assets:
            prepared=revision.validation_evidence.get('offline_piece_manifests',{}).get(str(asset.id),{})
            if (prepared.get('asset_sha256')!=asset.sha256 or not isinstance(prepared.get('bytes'),int)
                or not 1<=prepared['bytes']<=1048576 or not prepared.get('storage_key','').startswith(f'revisions/{revision.id}/offline-pieces/')):
                raise DomainError('offline_audio_not_prepared','Prepared audio piece manifests are required before offline audio.',409)
            raw=storage.verify_private(prepared['storage_key'],prepared['bytes'],prepared['sha256'],'application/json',return_bytes=True)
            document=json.loads(raw);validate_schema(document,'OfflinePiecePage')
            if document['asset_id']!=str(asset.id) or document['asset_sha256']!=asset.sha256:
                raise DomainError('offline_audio_not_prepared','Audio piece manifest belongs to another asset.',409)
            offset=0
            for index,piece in enumerate(document['pieces']):
                if piece['piece_index']!=index or piece['offset_bytes']!=offset or (index<len(document['pieces'])-1 and piece['bytes']!=document['piece_bytes']):
                    raise DomainError('offline_audio_not_prepared','Audio pieces are not contiguous.',409)
                offset+=piece['bytes']
            if offset!=asset.bytes:raise DomainError('offline_audio_not_prepared','Audio pieces do not cover the whole asset.',409)
            prepared_manifests[str(asset.id)]=prepared

    now=timezone.now();ends=[now+timedelta(hours=24),device.expires_at,right.ends_at,current_right(revision,fmt,'read',territory).ends_at]
    if entitlement.valid_until:ends.append(entitlement.valid_until)
    expiry=min(ends)
    if expiry<=now:raise DomainError('rights_unavailable','No remaining offline rights window.',403)
    identifier=uuid.uuid4();manifest={'schema_version':1,'edition_revision_id':str(revision.id),'content_sha256':revision.content_sha256,
        'assets':[{'asset_id':str(a.id),'unit_id':str(a.unit_id),'sha256':a.sha256,'bytes':a.bytes,'content_type':a.content_type,'piece_manifest':prepared_manifests.get(str(a.id))} for a in assets],
        'bytes_total':sum(a.bytes for a in assets)}
    if len(canonical_bytes(manifest))>65536:raise DomainError('manifest_too_large','Choose fewer units.',413)
    row=DownloadLicense.objects.create(id=identifier,user=user,device=device,entitlement=entitlement,revision=revision,rights_record=right,
        format=fmt,territory=territory,unit_ids=units,manifest=manifest,manifest_sha256=hashlib.sha256(canonical_bytes(manifest)).hexdigest(),
        private_manifest_key=f'db:download-license:{identifier}',issued_at=now,expires_at=expiry)
    audit(user,'download.licensed',row,{'format':fmt,'units':len(units)})
    return row


def create_license(user,device_id,data,key,territory):
    _enabled()
    def mutate():
        row=_create(user,device_id,data,territory)
        # Receipt stores stable identity only; retries get fresh120s URLs, never an extended lease.
        return 201,{'license_id':str(row.id)},1
    status,result=apply_operation(user,key,'download.create',data,mutate)
    return status,_serialize(_owned(user,device_id,result['license_id']))


def list_licenses(user,device_id,params=None):
    from core.pagination import keyset_page
    _enabled();device=validate_device(user,device_id)
    rows=DownloadLicense.objects.filter(user=user,device=device).select_related('revision__edition','device','entitlement','rights_record','user')
    return keyset_page(rows,params or {},f'downloads:{user.pk}:{device.pk}','issued_at',lambda row:_serialize(row,False))


def get_license(user,device_id,license_id):
    _enabled();return _serialize(_owned(user,device_id,license_id))


def refresh_license(user,device_id,license_id):
    _enabled();row=_owned(user,device_id,license_id)
    if _status(row)!='active':raise DomainError('license_inactive','Renew or download again after online authorization.',409)
    return _serialize(row)


def revoke_license(user,device_id,license_id,key):
    _enabled()
    def mutate():
        row=_owned(user,device_id,license_id,True)
        if row.revoked_at is None:row.revoked_at=timezone.now();row.save(update_fields=['revoked_at']);audit(user,'download.revoked',row)
        return 204,{},1
    return apply_operation(user,key,'download.revoke',{'license_id':str(license_id)},mutate)


def renew_license(user,device_id,license_id,key,territory):
    _enabled()
    def mutate():
        old=_owned(user,device_id,license_id,True)
        if old.revoked_at:raise DomainError('license_revoked','Request a new download explicitly.',409)
        if territory!=old.territory:raise DomainError('region_changed','Request a new download for the current region.',403)
        data={'edition_revision_id':str(old.revision_id),'device_id':str(device_id),'format':old.format,'unit_ids':old.unit_ids}
        row=_create(user,device_id,data,territory)
        old.revoked_at=timezone.now();old.save(update_fields=['revoked_at'])
        return 200,{'license_id':str(row.id)},1
    status,result=apply_operation(user,key,'download.renew',{'license_id':str(license_id)},mutate)
    return status,_serialize(_owned(user,device_id,result['license_id']))


def _local_piece_url(row,asset,seconds):
    if not settings.LOCAL:raise DomainError('feature_disabled','Local manifest delivery is unavailable.',404)
    expiry=min(timezone.now()+timedelta(seconds=seconds),row.expires_at)
    token=signing.dumps({'license':str(row.id),'asset':str(asset.id),'user':str(row.user.public_id),'device':str(row.device_id),
        'territory':row.territory,'exp':int(expiry.timestamp())},salt='maison-local-offline-pieces')
    return urljoin(settings.PUBLIC_BASE_URL,f'/api/v1/me/downloads/{row.id}/pieces/{asset.id}?token={token}')


def local_piece_manifest(user,device_id,license_id,asset_id,token,territory):
    from library import storage
    if not settings.LOCAL or storage.is_r2():raise DomainError('feature_disabled','Local manifest delivery is unavailable.',404)
    _enabled()
    try:data=signing.loads(token,salt='maison-local-offline-pieces',max_age=120)
    except (signing.BadSignature,TypeError,ValueError):raise DomainError('invalid_grant','Manifest grant is invalid or expired.',403)
    expected={'license':str(license_id),'asset':str(asset_id),'user':str(user.public_id),'device':str(device_id),'territory':territory}
    if any(data.get(key)!=value for key,value in expected.items()) or data.get('exp',0)<=timezone.now().timestamp():
        raise DomainError('invalid_grant','Manifest grant is invalid or expired.',403)
    row=_owned(user,device_id,license_id)
    asset=Asset.objects.filter(pk=asset_id,revision=row.revision,state='ready').first()
    if not asset:raise DomainError('not_found','Manifest asset is unavailable.',404)
    validate_delivery_license(user,license_id,asset,device_id,territory)
    bound=next((item for item in row.manifest['assets'] if item['asset_id']==str(asset.id)),{})
    prepared=bound.get('piece_manifest')
    if not prepared or not 1<=prepared.get('bytes',0)<=1048576:raise DomainError('not_found','Prepared audio pieces are unavailable.',404)
    return storage.verify_private(prepared['storage_key'],prepared['bytes'],prepared['sha256'],'application/json',max_seconds=8,return_bytes=True)
