"""Small staff-only intake into the existing revision/asset pipeline. Always draft."""
import json
from pathlib import Path
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from core.api import json_endpoint,json_body,api_response,operation_key,DomainError
from core.services import apply_operation,audit
from .models import Work,Edition,Revision,Unit,Paragraph,Rights
from .services import write_reader_package,revision_hash,paragraph_dto,staff_state

def staff_permission(user):
    if not user.is_active or not user.is_staff or not user.has_perm("library.publish_revision"):
        raise DomainError("permission_denied","Content publisher permission is required.",403)

PACKET=Path(__file__).parent/'intake/selfish-giant-en.json'

@json_endpoint(('POST',))
def intake(request):
    staff_permission(request.user)
    data=json_body(request,{'manifest_id'},['manifest_id'])
    if data['manifest_id']!='EN-071':raise DomainError('not_found','No approved intake packet for this ID.',404)
    packet=json.loads(PACKET.read_text())
    def create():
        if Edition.objects.filter(slug=packet['slug']).exists():raise DomainError('already_imported','Reconcile the existing draft; do not overwrite it.',409)
        work=Work.objects.create(slug='the-selfish-giant',title=packet['title'],creators=[packet['author']],house=packet['house'])
        edition=Edition.objects.create(work=work,slug=packet['slug'],locale='en')
        revision=Revision.objects.create(edition=edition,title=packet['title'],description=packet['description'],access_policy={'reader':'free','audio':'deny','video':'deny'})
        unit=Unit.objects.create(revision=revision,title=packet['title'],ordinal=1)
        for n,text in enumerate(packet['paragraphs'],1):Paragraph.objects.create(unit=unit,ordinal=n,text=text)
        revision.content_sha256=revision_hash(revision);revision.save()
        write_reader_package(unit)
        now=timezone.now()
        for action in ['read','preview']:
            Rights.objects.create(revision=revision,format='reader',action=action,territories=['IN'],starts_at=now,ends_at=now+timedelta(days=3650),approved=True,test_only=False,evidence=json.dumps(packet['rights']))
        revision.preview=[{'anchor_id':str(unit.paragraphs.first().anchor_id),'text':packet['paragraphs'][0][:130]}];revision.save()
        audit(request.user,'book.draft_import',revision,{'manifest_id':'EN-071'})
        return 201,{'edition_id':str(edition.id),'edition_revision_id':str(revision.id),'slug':edition.slug,'state':'draft','sha256':revision.content_sha256,'paragraph_count':len(packet['paragraphs'])},revision.version
    status,result=apply_operation(request.user,operation_key(request),'book.draft_import',data,create)
    return api_response(result,status)

@json_endpoint(('GET',))
def draft_document(request,revision_id):
    staff_permission(request.user)
    revision=Revision.objects.filter(pk=revision_id,state='draft').first()
    if not revision:raise DomainError('not_found','Draft not found.',404)
    return api_response({'title':revision.title,'state':'draft','edition_revision_id':str(revision.id),'sha256':revision.content_sha256,'units':[{'unit_id':str(u.id),'title':u.title,'paragraphs':[paragraph_dto(p) for p in u.paragraphs.all()]} for u in revision.units.all()]})
