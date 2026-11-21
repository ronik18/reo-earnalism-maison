"""Small staff-only intake into the existing revision/asset pipeline. Always draft."""
import json
import uuid
from pathlib import Path
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from core.api import json_endpoint,json_body,api_response,operation_key,DomainError
from core.services import apply_operation,audit
from core.models import OperationReceipt
from .models import Work,Edition,Revision,Unit,Paragraph,Rights
from .services import prepare_reader_package,paragraph_dto,digest,canonical_bytes

def staff_permission(user):
    if not user.is_active or not user.is_staff or not user.has_perm("library.publish_revision"):
        raise DomainError("permission_denied","Content publisher permission is required.",403)

PACKET=Path(__file__).parent/'intake/selfish-giant-en.json'
RIGHTS_REVIEW=Path(__file__).resolve().parent.parent/'docs/evidence/selfish-giant-global-rights.json'

def reviewed_territories(packet, paragraphs_sha256):
    """Bind this fixed intake packet to its reviewed text and explicit country decisions."""
    review=json.loads(RIGHTS_REVIEW.read_text())
    countries=packet['rights']['territories']
    decisions={row['territory'] for row in review['research'] if row['internal_reader_decision']=='approved_content_scope'}
    if (paragraphs_sha256!=review['paragraphs_sha256'] or digest(canonical_bytes(packet['paragraphs']))!=review['paragraphs_sha256'] or packet['rights'].get('review_id')!=review['review_id']
        or not isinstance(countries,list) or not countries or len(set(countries))!=len(countries)
        or set(countries)!=decisions or countries!=review['runtime_approved_territories']
        or set(countries)!=set(settings.MAISON_PUBLICATION_TERRITORIES)
        or any(not isinstance(c,str) or len(c)!=2 or not c.isascii() or not c.isupper() or not c.isalpha() for c in countries)
        or set(countries)&set(review['held_territories']) or packet['rights'].get('commercial_use_allowed') is not True):
        raise DomainError('rights_review_mismatch','Intake text or territories differ from the private rights review.',409)
    return countries


@json_endpoint(('POST',))
def intake(request):
    staff_permission(request.user)
    if "manifest" in json_body(request):
        from .general_import_api import start
        return start(request)
    data=json_body(request,{'manifest_id'},['manifest_id'])
    if data['manifest_id']!='EN-071':raise DomainError('not_found','No approved intake packet for this ID.',404)
    operation=operation_key(request)
    old=OperationReceipt.objects.filter(actor=request.user,operation_id=operation).first()
    if old:
        # A successful replay needs no storage/network preparation, even during a provider outage.
        def never_create():raise DomainError('operation_reconciliation_required','The receipt changed; retry this same operation.',409)
        status,result=apply_operation(request.user,operation,'book.draft_import',data,never_create)
        return api_response(result,status)
    packet_bytes=PACKET.read_bytes();packet=json.loads(packet_bytes)
    packet_sha=digest(packet_bytes)
    countries=reviewed_territories(packet,digest(canonical_bytes(packet['paragraphs'])))
    if Edition.objects.filter(slug=packet['slug']).exists():raise DomainError('already_imported','Reconcile the existing draft; do not overwrite it.',409)
    # Stable private keys reconcile a timed-out write/retry without preparing unrelated orphan objects.
    def identifier(label):
        raw=digest(canonical_bytes([str(request.user.public_id),str(operation),packet_sha,label]))
        return uuid.UUID(hex=raw[:32],version=4)
    work=Work(id=identifier('work'),slug='the-selfish-giant',title=packet['title'],creators=[packet['author']],house=packet['house'])
    edition=Edition(id=identifier('edition'),work=work,slug=packet['slug'],locale='en')
    revision=Revision(id=identifier('revision'),edition=edition,title=packet['title'],description=packet['description'],access_policy={'reader':'free','audio':'deny','video':'deny'})
    unit=Unit(id=identifier('unit'),revision=revision,title=packet['title'],ordinal=1)
    paragraphs=[Paragraph(id=identifier(f'paragraph:{n}'),anchor_id=identifier(f'anchor:{n}'),unit=unit,ordinal=n,text=text) for n,text in enumerate(packet['paragraphs'],1)]
    revision.content_sha256=digest(canonical_bytes([{'unit_id':str(unit.id),'title':unit.title,'ordinal':unit.ordinal,'paragraphs':[paragraph_dto(p) for p in paragraphs]}]))
    revision.preview=[{'anchor_id':str(paragraphs[0].anchor_id),'text':packet['paragraphs'][0][:130]}]
    asset=prepare_reader_package(unit,paragraphs,asset_id=identifier('reader-package'))
    def create():
        # Snapshot CAS is local filesystem/DB only. No object calls run inside the receipt transaction.
        if digest(PACKET.read_bytes())!=packet_sha:raise DomainError('version_conflict','Intake packet changed during preparation.',412)
        reviewed_territories(packet,digest(canonical_bytes(packet['paragraphs'])))
        current_work,_=Work.objects.get_or_create(slug=work.slug,defaults={'id':work.id,'title':work.title,'creators':work.creators,'house':work.house})
        current_work=Work.objects.select_for_update().get(pk=current_work.pk)
        if current_work.title!=work.title or current_work.creators!=work.creators:
            raise DomainError('intake_identity_conflict','Existing work differs from this reviewed intake packet.',409)
        if Edition.objects.filter(slug=packet['slug']).exists():raise DomainError('already_imported','Reconcile the existing draft; do not overwrite it.',409)
        edition.work=current_work;edition.save();revision.save();unit.save()
        Paragraph.objects.bulk_create(paragraphs);asset.save()
        now=timezone.now()
        for action in ['read','preview']:
            Rights.objects.create(revision=revision,format='reader',action=action,territories=countries,starts_at=now,ends_at=now+timedelta(days=3650),approved=True,test_only=False,evidence=json.dumps(packet['rights']))
        revision.refresh_from_db()
        audit(request.user,'book.draft_import',revision,{'manifest_id':'EN-071'})
        return 201,{'edition_id':str(edition.id),'edition_revision_id':str(revision.id),'slug':edition.slug,'state':'draft','sha256':revision.content_sha256,'paragraph_count':len(packet['paragraphs'])},revision.version
    status,result=apply_operation(request.user,operation,'book.draft_import',data,create)
    return api_response(result,status)

@json_endpoint(('GET',))
def draft_document(request,revision_id):
    staff_permission(request.user)
    revision=Revision.objects.filter(pk=revision_id,state='draft').first()
    if not revision:raise DomainError('not_found','Draft not found.',404)
    return api_response({'title':revision.title,'state':'draft','edition_revision_id':str(revision.id),'sha256':revision.content_sha256,'units':[{'unit_id':str(u.id),'title':u.title,'paragraphs':[paragraph_dto(p) for p in u.paragraphs.all()]} for u in revision.units.all()]})


@json_endpoint(('GET',))
def draft_cover(request,asset_id):
    from django.http import HttpResponse
    from .models import Asset
    from .services import _asset_valid
    staff_permission(request.user)
    asset=Asset.objects.filter(pk=asset_id,kind='cover',state='ready',revision__state='draft').first()
    if not asset: raise DomainError('not_found','Draft cover not found.',404)
    response=HttpResponse(_asset_valid(asset),content_type=asset.content_type)
    response['Cache-Control']='private, no-store'
    return response


@json_endpoint(('GET',))
def draft_edition(request,edition_id):
    from .services import edition_detail
    staff_permission(request.user)
    if not Edition.objects.filter(pk=edition_id,live_revision__isnull=True).exists():
        raise DomainError('not_found','Unpublished draft edition not found.',404)
    return api_response(edition_detail(edition_id,territory=getattr(request,'territory','ZZ'),user=request.user))
