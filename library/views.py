import json
import re
import uuid
from datetime import timedelta
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from core.api import (DomainError,api_response,json_endpoint,expected_version,operation_key)
from core.services import apply_operation,audit
from .models import Work,Edition,Revision,Asset,Unit,TimingMap
from . import services as svc
from .validation import body,validate_schema

def context(request):
    trusted=getattr(request,'territory','IN' if getattr(settings,'LOCAL',False) else 'ZZ')
    locale=request.GET.get('locale','en');territory=request.GET.get('territory',trusted)
    if locale not in {'en','bn'} or not re.fullmatch('[A-Z]{2}',territory):
        raise DomainError('invalid_context','Use locale en/bn and a two-letter territory.',422)
    # Client query controls cache context, never the authorization territory authority.
    if territory!=trusted or trusted=='ZZ':
        raise DomainError('territory_unavailable','A qualified trusted territory context is required.',403)
    return locale,territory

def page(request,items,scope):
    try: limit=int(request.GET.get('limit',20))
    except ValueError: raise DomainError('invalid_limit','Limit must be an integer.',422)
    if not 1<=limit<=100: raise DomainError('invalid_limit','Limit must be 1–100.',422)
    offset=0
    if request.GET.get('cursor'):
        try:
            cursor=signing.loads(request.GET['cursor'],salt='maison-list-cursor',max_age=3600)
            query={k:v for k,v in request.GET.items() if k!='cursor'}
            if cursor['scope']!=scope or cursor['query']!=query: raise ValueError()
            offset=cursor['offset']
            if type(offset) is not int or offset<0: raise ValueError()
        except (signing.BadSignature,KeyError,ValueError,TypeError): raise DomainError('invalid_cursor','Invalid page cursor.',422)
    selected=items[offset:offset+limit];more=offset+limit<len(items)
    return {'items':selected,'next_cursor':signing.dumps({'scope':scope,'offset':offset+limit,'query':{k:v for k,v in request.GET.items() if k!='cursor'}},salt='maison-list-cursor') if more else None,'has_more':more}

def public_response(data,ttl=0):
    response=api_response(data)
    # Authenticated cookies always bypass shared cache, even for identical public DTOs.
    response['Cache-Control']='public, max-age=0, s-maxage='+str(max(0,ttl))+', must-revalidate'
    response['Vary']='Cookie'
    return response

def _catalog_ttl(cards,territory):
    ids=[c['edition_id'] for c in cards]
    revisions=Revision.objects.filter(edition__id__in=ids,edition__live_revision_id=__import__('django.db.models',fromlist=['F']).F('id'))
    return min([svc.public_ttl(r,30,territory=territory) for r in revisions] or [0])

def _summary(locale):
    return {'collection_id':'90000000-0000-4000-8000-000000000001','title':'Local original stories' if locale=='en' else 'স্থানীয় মৌলিক গল্প',
            'kind':'shelf','description':'Original technical acceptance fixtures; not commercially released.','cover':None}

@json_endpoint(auth=False)
def home(request):
    locale,territory=context(request);cards=svc.catalog_cards(locale,territory)
    data={'locale':locale,'territory':territory,'hero':cards[0] if cards else None,
          'shelves':[{'collection':_summary(locale),'items':cards[:12]}] if cards else [],
          'catalog_version':svc.digest(svc.canonical_bytes(cards))}
    return public_response(data,_catalog_ttl(cards,territory))

@json_endpoint(auth=False)
def catalog(request):
    locale,territory=context(request)
    if len(request.GET.get('q',''))>120: raise DomainError('query_too_long','Search query is limited to 120 characters.',422)
    cards=svc.catalog_cards(locale,territory,query=request.GET.get('q',''),house=request.GET.get('house',''),format=request.GET.get('format',''),
        **{k:request.GET.get(k,'') for k in ('author','topic','level','duration_min','duration_max','access','recency_days')})
    result=page(request,cards,'catalog')
    if request.path.endswith('/search'):
        result.update({'query':request.GET.get('q',''),'locale':locale,'territory':territory,'match_mode':'prefix' if cards else 'none'})
    return public_response(result,_catalog_ttl(cards,territory))

@json_endpoint(auth=False)
def collections(request):
    locale,territory=context(request)
    return public_response(page(request,[_summary(locale)],'collections'),0)

@json_endpoint(auth=False)
def collection(request,collection_id):
    locale,territory=context(request)
    if str(collection_id)!='90000000-0000-4000-8000-000000000001': raise DomainError('not_found','Collection not found.',404)
    cards=svc.catalog_cards(locale,territory)
    summary=_summary(locale);summary.pop('cover')
    return public_response({**summary,'items':cards[:100],'next_cursor':None},_catalog_ttl(cards,territory))

@json_endpoint(auth=False)
def work(request,work_id):
    locale,territory=context(request)
    try: obj=Work.objects.get(pk=work_id)
    except Work.DoesNotExist: raise DomainError('not_found','Work not found.',404)
    cards=[c for c in svc.catalog_cards(locale,territory) if c['work_id']==str(work_id)]
    if not cards: raise DomainError('not_found','Work not found.',404)
    return public_response({'work_id':str(obj.id),'title':obj.title,'description':obj.editions.filter(live_revision__isnull=False).first().live_revision.description,
                            'creators':obj.creators,'editions':cards,'related_collections':[_summary(locale)]},_catalog_ttl(cards,territory))

@json_endpoint(auth=False)
def edition(request,edition_id):
    _,territory=context(request);data=svc.edition_detail(edition_id,territory)
    return public_response(data,svc.public_ttl(svc._revision(data['edition_revision_id']),30,territory=territory))

@json_endpoint(auth=False)
def units(request,edition_id):
    _,territory=context(request);items=svc.edition_units(edition_id,territory)
    return public_response(page(request,items,'units:'+str(edition_id)),0)

@json_endpoint(auth=False)
def preview(request,revision_id):
    _,territory=context(request);revision=svc._revision(revision_id)
    if not svc._live(revision) or not revision.preview or not svc.current_right(revision,'reader','preview',territory):
        raise DomainError('preview_unavailable','No public preview is available.',404)
    unit=revision.units.first()
    paragraphs=revision.preview
    if not unit or len(paragraphs)>3 or sum(len(p['text']) for p in paragraphs)>1200:
        raise DomainError('preview_unavailable','Preview does not pass its bounds.',409)
    data={'schema_version':1,'edition_revision_id':str(revision.id),'locale':revision.edition.locale,
          'preview_sha256':svc.digest(svc.canonical_bytes(paragraphs)),
          'units':[{'unit_id':str(unit.id),'title':unit.title,'paragraphs':paragraphs}],
          'boundary':{'end_anchor_id':paragraphs[-1]['anchor_id'],'end_offset_chars':len(paragraphs[-1]['text']),'audio_end_ms':None,'video_end_ms':None},
          'full_content_included':False}
    return public_response(data,svc.public_ttl(revision,60,'preview',territory))

@json_endpoint(auth=False)
def cover(request,asset_id):
    _,territory=context(request)
    try: asset=Asset.objects.select_related('revision','revision__edition').get(pk=asset_id,kind='cover',state='ready')
    except Asset.DoesNotExist: raise DomainError('not_found','Cover not found.',404)
    if not svc._live(asset.revision) or not svc.available_formats(asset.revision,territory): raise DomainError('not_found','Cover unavailable.',404)
    response=HttpResponse(svc._asset_valid(asset),content_type=asset.content_type)
    response['Cache-Control']=f'public, max-age=0, s-maxage={svc.public_ttl(asset.revision,3600,territory=territory)}, must-revalidate'
    response['X-Content-Type-Options']='nosniff'
    return response

@json_endpoint()
def manifest(request,revision_id):
    _,territory=context(request)
    return api_response(svc.get_reader_manifest(request.user,revision_id,territory,request.GET.get('cursor')))

@json_endpoint(methods=('POST',))
def packages(request):
    data=body(request,'PackageGrantInput');_,territory=context(request)
    result=svc.package_grant(request.user,data,territory)
    for asset in result['assets']: asset['url']=request.build_absolute_uri(asset['url'])
    return api_response(result,201)

@json_endpoint(methods=('POST',))
def media(request):
    if not settings.FEATURES.get('audio',False) and not settings.FEATURES.get('video',False):
        raise DomainError('feature_disabled','Media providers are not enabled in this launch slice.',503)
    data=body(request,'MediaGrantInput');_,territory=context(request)
    result=svc.media_grant(request.user,data,territory);result['url']=request.build_absolute_uri(result['url'])
    return api_response(result,201)

@json_endpoint()
def local_asset(request,asset_id):
    if not getattr(settings,'LOCAL',False): raise DomainError('feature_disabled','Local storage is unavailable.',404)
    asset,raw=svc.resolve_signed_asset(request.user,asset_id,request.GET.get('token',''))
    status=200;headers={}
    if request.headers.get('Range'):
        if asset.kind!='audio_chapter': raise DomainError('range_not_supported','This asset does not support ranges.',416)
        match=re.fullmatch(r'bytes=(\d+)-(\d*)',request.headers['Range'])
        if not match: raise DomainError('invalid_range','Use one bounded bytes range.',416)
        start=int(match[1]);end=int(match[2]) if match[2] else len(raw)-1
        if start>end or start>=len(raw) or end>=len(raw): raise DomainError('invalid_range','Range lies outside the asset.',416)
        total=len(raw);raw=raw[start:end+1];status=206;headers['Content-Range']=f'bytes {start}-{end}/{total}'
    response=HttpResponse(raw,status=status,content_type=asset.content_type)
    response['Cache-Control']='private, no-store';response['X-Content-Type-Options']='nosniff'
    response['Content-Length']=str(len(raw));response['Content-Disposition']='inline'
    if asset.kind=='audio_chapter': response['Accept-Ranges']='bytes'
    for key,value in headers.items(): response[key]=value
    return response

@json_endpoint()
def mappings(request,revision_id):
    _,territory=context(request);revision=svc.authorize_revision(request.user,revision_id,territory=territory)
    # No estimated map, fallback audio, or fake synchronized state.
    return api_response({'edition_revision_id':str(revision.id),'status':'feature_disabled' if not settings.FEATURES.get('audio') else 'unmapped','maps':[]})

@json_endpoint(methods=('POST',))
def switch(request):
    data=body(request,'SwitchInput');_,territory=context(request)
    revision=svc.authorize_revision(request.user,data['edition_revision_id'],territory=territory)
    location=data['from_location']
    if not revision.units.filter(pk=location['unit_id']).exists(): raise DomainError('unit_revision_mismatch','Location unit is not in this revision.',409)
    return api_response({'outcome':'feature_disabled','to_location':None,'map_id':None,'precision':None,'reason_code':'media_provider_not_qualified'})

def staff_permission(user):
    if not user.is_active or not user.is_staff or not user.has_perm('library.publish_revision'):
        raise DomainError('permission_denied','Content publisher permission is required.',403)

def asset_state(asset):
    return {'asset_id':str(asset.id),'edition_revision_id':str(asset.revision_id),'state':asset.state,'sha256':asset.sha256,'bytes':asset.bytes,'version':asset.version}

@json_endpoint()
def staff_review(request,edition_id):
    staff_permission(request.user)
    revision=Revision.objects.filter(edition_id=edition_id).order_by('-created_at').first()
    if not revision: raise DomainError('not_found','Edition not found.',404)
    assets=list(revision.assets.order_by('id')[:100])
    return api_response({'state':svc.staff_state(revision),'validation':svc.validate_revision(revision),
                         'assets':[asset_state(a) for a in assets],'next_asset_cursor':None},version=revision.version)

@json_endpoint(methods=('POST',))
def staff_action(request,edition_id,action):
    staff_permission(request.user)
    data=body(request,'WithdrawalInput' if action=='withdraw' else 'ScheduleInput' if action=='schedule' else 'PublicationAction')
    version=expected_version(request);operation=operation_key(request)
    def execute():
        revision=Revision.objects.filter(edition_id=edition_id,pk=data.get('edition_revision_id')).first() if action!='withdraw' else Revision.objects.filter(edition_id=edition_id,state='live').first()
        if not revision: raise DomainError('not_found','Edition revision not found.',404)
        result=svc.transition_revision(request.user,revision.id,action,version,data.get('expected_sha256',revision.content_sha256),data.get('reason',''),parse_datetime(data['publish_at']) if action=='schedule' else None)
        audit(request.user,'content.'+action,revision,{'reason':data.get('reason',''),'sha256':revision.content_sha256})
        return 200,result,result.get('version',version)
    status,result=apply_operation(request.user,operation,'content.'+action,{**data,'edition_id':str(edition_id),'expected_version':version},execute)
    return api_response(result,status,version=result.get('version'))

@json_endpoint()
def staff_asset(request,asset_id):
    staff_permission(request.user)
    try: asset=Asset.objects.get(pk=asset_id)
    except Asset.DoesNotExist: raise DomainError('not_found','Asset not found.',404)
    return api_response(asset_state(asset),version=asset.version)

@json_endpoint(methods=('POST',))
def upload(request):
    staff_permission(request.user);data=body(request,'UploadInput')
    if not getattr(settings,'LOCAL',False): raise DomainError('provider_unconfigured','A qualified direct upload adapter is required.',503)
    operation=operation_key(request)
    if data['bytes']>262144: raise DomainError('local_upload_limit','Local acceptance uploads are limited to 256 KiB.',413)
    mime_types={'cover':{'image/png','image/jpeg','image/webp'},'reader_source':{'text/plain','application/json'},
                'reader_package':{'application/json'},'timing_map':{'application/json'},'rights_document':{'application/pdf','text/plain'},
                'audio':{'audio/mpeg'},'video':{'video/mp4'}}
    if data['content_type'] not in mime_types.get(data['kind'],set()):
        raise DomainError('invalid_content_type','Content type is not permitted for this input kind.',422)
    def execute():
        revision=Revision.objects.select_for_update().get(pk=data['edition_revision_id'])
        if revision.state!='draft': raise DomainError('revision_frozen','Upload only into a draft revision.',409)
        asset_id=uuid.uuid4();kind='audio_chapter' if data['kind']=='audio' else data['kind']
        asset=Asset.objects.create(id=asset_id,revision=revision,kind=kind,storage_key=f'revisions/{revision.id}/{asset_id}',sha256=data['sha256'],bytes=data['bytes'],content_type=data['content_type'])
        expiry=timezone.now()+timedelta(seconds=120)
        token=signing.dumps({'asset':str(asset.id),'actor':str(request.user.public_id),'exp':int(expiry.timestamp()),'method':'PUT'},salt='maison-local-upload')
        result={'asset_id':str(asset.id),'version':asset.version,'protocol':'local_put','method':'PUT',
                'upload_url':request.build_absolute_uri(f'/api/v1/staff/assets/{asset.id}/local-upload?token={token}'),
                'required_headers':{'Content-Type':asset.content_type},'expires_at':svc.iso(expiry),'max_bytes':asset.bytes}
        return 201,result,asset.version
    status,result=apply_operation(request.user,operation,'asset.upload',data,execute)
    return api_response(result,status,version=result['version'])

@json_endpoint(methods=('PUT',))
def local_upload(request,asset_id):
    staff_permission(request.user)
    if not getattr(settings,'LOCAL',False): raise DomainError('feature_disabled','Local storage is unavailable.',404)
    try: token=signing.loads(request.GET.get('token',''),salt='maison-local-upload',max_age=120)
    except signing.BadSignature: raise DomainError('invalid_grant','Upload authorization expired.',403)
    if token.get('asset')!=str(asset_id) or token.get('actor')!=str(request.user.public_id) or token.get('method')!='PUT' or token.get('exp',0)<=timezone.now().timestamp(): raise DomainError('invalid_grant','Invalid upload authorization.',403)
    with transaction.atomic():
        try: asset=Asset.objects.select_for_update().select_related('revision').get(pk=asset_id)
        except Asset.DoesNotExist: raise DomainError('not_found','Asset not found.',404)
        if asset.revision.state!='draft' or asset.state!='uploading': raise DomainError('invalid_transition','Asset no longer accepts uploads.',409)
        raw=request.body
        if request.content_type!=asset.content_type or len(raw)!=asset.bytes or svc.digest(raw)!=asset.sha256: raise DomainError('upload_integrity_failed','Bytes, type and SHA-256 must match the upload intent.',422)
        path=svc.asset_path(asset.storage_key);path.parent.mkdir(parents=True,exist_ok=True)
        # An exclusive first write prevents replacing an already accepted object under the same key.
        if path.exists():
            if path.read_bytes()!=raw: raise DomainError('object_exists','Content key already contains different bytes.',409)
        else:
            with path.open('xb') as f: f.write(raw)
    return api_response({'accepted':True},200)

@json_endpoint(methods=('POST',))
def complete_upload(request,asset_id):
    staff_permission(request.user);data=body(request,'UploadCompleteInput');version=expected_version(request);operation=operation_key(request)
    def execute():
        try: asset=Asset.objects.select_for_update().select_related('revision','revision__edition').get(pk=asset_id)
        except Asset.DoesNotExist: raise DomainError('not_found','Asset not found.',404)
        if asset.version!=version: raise DomainError('version_conflict','Asset changed.',412,{'current_version':asset.version})
        if asset.state!='uploading' or asset.revision.state!='draft': raise DomainError('invalid_transition','Only uploading draft assets can complete.',409)
        if data['bytes']!=asset.bytes or data['sha256']!=asset.sha256: raise DomainError('upload_integrity_failed','Completion does not match intent.',422)
        raw=svc._asset_valid(asset)
        if asset.kind=='reader_package':
            try: package=json.loads(raw)
            except (ValueError,UnicodeDecodeError): raise DomainError('invalid_package','Reader package must be valid JSON.',422)
            validate_schema(package,'ReaderChunk')
            if package['edition_revision_id']!=str(asset.revision_id) or package['chunk_id']!=str(asset.id) or package['locale']!=asset.revision.edition.locale: raise DomainError('package_revision_mismatch','Reader package identity does not match its upload.',409)
            try: unit=Unit.objects.get(pk=package['unit_id'],revision=asset.revision)
            except Unit.DoesNotExist: raise DomainError('package_revision_mismatch','Package unit is not in this revision.',409)
            expected=[svc.paragraph_dto(p) for p in unit.paragraphs.all()]
            if package['paragraphs']!=expected or package['anchor_revision']!=asset.revision.anchor_revision: raise DomainError('package_text_mismatch','Package must match the canonical paragraph source.',409)
            asset.unit=unit
        # Private raw source/evidence is stored but never promoted into a deliverable kind.
        if asset.kind in {'audio_chapter','video'}:
            raise DomainError('provider_processing_required','Media and timing require a qualified processing/measurement adapter.',409)
        asset.state='ready';asset.version+=1;asset.save()
        audit(request.user,'asset.complete',asset,{'sha256':asset.sha256,'kind':asset.kind})
        return 200,asset_state(asset),asset.version
    status,result=apply_operation(request.user,operation,'asset.complete',{**data,'asset_id':str(asset_id),'expected_version':version},execute)
    return api_response(result,status,version=result['version'])
