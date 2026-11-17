import hashlib
import unicodedata
import uuid
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum,Q,Exists,OuterRef
from django.db.models.functions import Length
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from core.api import DomainError,public_uuid
from core.services import apply_operation
from library.models import Edition,Revision,Unit,Paragraph
from library.services import authorize_revision
from .models import Progress,Completion,Annotation,SavedItem,PersonalList,PersonalListItem


def iso(value):return value.isoformat().replace('+00:00','Z') if value else None


def _edition(value):
    row=Edition.objects.select_related('live_revision').filter(pk=public_uuid(value)).first()
    if not row or not row.live_revision_id:raise DomainError('not_found','Published edition not found.',404)
    return row


def _boundary(text,index):
    if type(index)!=int or not 0<=index<=len(text):return False
    try:
        import regex
        return index==0 or any(m.end()==index for m in regex.finditer(r'\X',text))
    except ImportError:
        if index in [0,len(text)]:return True
        return not (unicodedata.category(text[index]).startswith('M') or text[index] in '\u200c\u200d' or text[index-1] in '\u200c\u200d' or 'VIRAMA' in unicodedata.name(text[index-1],''))


def _location(revision,format,loc):
    if not isinstance(loc,dict) or loc.get('format')!=format:raise DomainError('validation_error','Location format does not match.',422)
    allowed={'format','unit_id','anchor_id','offset_chars'} if format=='reader' else {'format','unit_id','position_ms'}
    if set(loc)!=allowed:raise DomainError('validation_error','Invalid location fields.',422)
    unit=Unit.objects.filter(pk=public_uuid(loc['unit_id']),revision=revision).first()
    if not unit:raise DomainError('invalid_anchor','Unit does not belong to this revision.',422)
    if format=='reader':
        para=Paragraph.objects.filter(anchor_id=public_uuid(loc['anchor_id']),unit=unit).first()
        if not para or not _boundary(para.text,loc['offset_chars']):raise DomainError('invalid_anchor','Invalid text boundary.',422)
        total=Paragraph.objects.filter(unit__revision=revision).aggregate(n=Sum(Length('text')))['n'] or 1
        before=Paragraph.objects.filter(unit__revision=revision).filter(Q(unit__ordinal__lt=unit.ordinal)|Q(unit=unit,ordinal__lt=para.ordinal)).aggregate(n=Sum(Length('text')))['n'] or 0
        fraction=min(Decimal(1),Decimal(before+loc['offset_chars'])/Decimal(total))
    else:
        if type(loc['position_ms'])!=int or loc['position_ms']<0 or unit.duration_ms is None or loc['position_ms']>unit.duration_ms:raise DomainError('invalid_position','Position exceeds known media duration.',422)
        fraction=Decimal(loc['position_ms'])/Decimal(unit.duration_ms or 1)
    return {k:str(v) if k.endswith('_id') else v for k,v in loc.items()},fraction


def progress_data(row,edition=None,format='reader'):
    if row is None:
        return {'edition_id':str(edition.id),'edition_revision_id':str(edition.live_revision_id),'format':format,'location':None,'fraction_complete':0,'version':0,'last_operation_id':None,'updated_at':None}
    return {'edition_id':str(row.edition_id),'edition_revision_id':str(row.revision_id),'format':row.format,'location':row.location,'fraction_complete':float(row.fraction_complete),'version':row.version,'last_operation_id':str(row.last_operation_id),'updated_at':iso(row.updated_at)}


def get_progress(user,edition_id,format='reader',territory='IN'):
    edition=_edition(edition_id);authorize_revision(user,edition.live_revision,format,territory=territory)
    row=Progress.objects.filter(user=user,edition=edition,format=format).first()
    return progress_data(row,edition,format)


def set_progress(user,edition_id,format,data,base_version,territory='IN'):
    payload={'edition_id':str(edition_id),'format':format,'base_version':base_version,**data}
    def mutate():
        edition=_edition(edition_id)
        if str(data.get('edition_revision_id'))!=str(edition.live_revision_id):raise DomainError('edition_revision_changed','Reload this edition revision before choosing a position.',409)
        revision=authorize_revision(user,edition.live_revision,format,territory=territory)
        loc,fraction=_location(revision,format,data.get('location'))
        row=Progress.objects.select_for_update().filter(user=user,edition=edition,format=format).first()
        current=progress_data(row,edition,format)
        if current['version']!=base_version:raise DomainError('version_conflict','Progress changed on another device.',412,current)
        occurred=parse_datetime(data.get('occurred_at',''))
        if not occurred or timezone.is_naive(occurred):raise DomainError('validation_error','Use an aware UTC occurrence time.',422)
        if row is None:
            row=Progress.objects.create(user=user,edition=edition,revision=revision,format=format,location=loc,fraction_complete=fraction,last_operation_id=public_uuid(data['operation_id']),client_occurred_at=occurred)
        else:
            row.revision=revision;row.location=loc;row.fraction_complete=fraction;row.last_operation_id=public_uuid(data['operation_id']);row.client_occurred_at=occurred;row.version+=1;row.save()
        return 200,progress_data(row),row.version
    return apply_operation(user,data['operation_id'],'progress.set',payload,mutate)


def completion_data(row,edition=None,format='reader'):
    if row is None:return {'edition_id':str(edition.id),'edition_revision_id':str(edition.live_revision_id),'format':format,'is_complete':False,'completed_at':None,'version':0,'updated_at':None}
    return {'edition_id':str(row.edition_id),'edition_revision_id':str(row.revision_id),'format':row.format,'is_complete':row.is_complete,'completed_at':iso(row.completed_at),'version':row.version,'updated_at':iso(row.updated_at)}


def get_completion(user,edition_id,format='reader',territory='IN'):
    edition=_edition(edition_id);authorize_revision(user,edition.live_revision,format,territory=territory)
    return completion_data(Completion.objects.filter(user=user,edition=edition,format=format).first(),edition,format)


def set_completion(user,edition_id,format,data,base_version,territory='IN'):
    if type(data.get('is_complete'))!=bool:raise DomainError('validation_error','is_complete must be a boolean.',422)
    payload={'edition_id':str(edition_id),'format':format,'base_version':base_version,**data}
    def mutate():
        edition=_edition(edition_id);revision=authorize_revision(user,edition.live_revision,format,territory=territory)
        row=Completion.objects.select_for_update().filter(user=user,edition=edition,format=format).first()
        current=completion_data(row,edition,format)
        if current['version']!=base_version:raise DomainError('version_conflict','Completion changed on another device.',412,current)
        if row is None:row=Completion(user=user,edition=edition,revision=revision,format=format)
        else:row.version+=1
        row.is_complete=data['is_complete'];row.completed_at=timezone.now() if row.is_complete else None;row.save()
        return 200,completion_data(row),row.version
    return apply_operation(user,data['operation_id'],'completion.set',payload,mutate)


def _range(revision,value,kind):
    required={'unit_id','start_anchor_id','start_offset_chars','end_anchor_id','end_offset_chars','offset_unit'}
    if not isinstance(value,dict) or set(value)!=required or value['offset_unit']!='unicode_code_point':raise DomainError('validation_error','Invalid text range.',422)
    unit=Unit.objects.filter(pk=public_uuid(value['unit_id']),revision=revision).first()
    start=Paragraph.objects.filter(unit=unit,anchor_id=public_uuid(value['start_anchor_id'])).first() if unit else None
    end=Paragraph.objects.filter(unit=unit,anchor_id=public_uuid(value['end_anchor_id'])).first() if unit else None
    if not start or not end or not _boundary(start.text,value['start_offset_chars']) or not _boundary(end.text,value['end_offset_chars']) or (start.ordinal,value['start_offset_chars'])>(end.ordinal,value['end_offset_chars']):raise DomainError('invalid_anchor','Text range does not match this revision.',422)
    collapsed=(start.pk==end.pk and value['start_offset_chars']==value['end_offset_chars'])
    if (kind=='bookmark')!=collapsed:raise DomainError('validation_error','Bookmark must be collapsed; highlight/note needs a selection.',422)
    parts=[]
    for p in Paragraph.objects.filter(unit=unit,ordinal__gte=start.ordinal,ordinal__lte=end.ordinal).order_by('ordinal'):
        parts.append(p.text[value['start_offset_chars'] if p.pk==start.pk else 0:value['end_offset_chars'] if p.pk==end.pk else len(p.text)])
    quote='\n'.join(parts);bounded=quote[:2048]
    while len(bounded.encode())>8192:bounded=bounded[:-1]
    return value,bounded,bounded!=quote


def annotation_data(row):
    return {'annotation_id':str(row.id),'edition_revision_id':str(row.revision_id),'kind':row.kind,'range':row.range,'color':row.color,'note_text':row.note_text,'quoted_text':row.quoted_text,'quoted_text_truncated':row.quoted_text_truncated,'version':row.version,'created_at':iso(row.created_at),'updated_at':iso(row.updated_at),'anchor_status':'valid' if row.revision.edition.live_revision_id==row.revision_id else 'orphaned'}


def _note(value):
    if value is not None and (not isinstance(value,str) or len(value.encode())>8192):raise DomainError('validation_error','Notes must be plain text no larger than 8 KiB.',422)
    return value


def create_annotation(user,data,operation_id,territory='IN'):
    def mutate():
        revision=authorize_revision(user,data['edition_revision_id'],territory=territory)
        kind=data.get('kind');color=data.get('color');note=_note(data.get('note_text'))
        if kind not in ['bookmark','highlight','note'] or color not in [None,'gold','mint','rose','lavender'] or (kind=='highlight' and color is None) or (kind=='note' and not note):raise DomainError('validation_error','Invalid annotation fields.',422)
        location,quote,truncated=_range(revision,data['range'],kind);identifier=public_uuid(data['annotation_id'])
        if Annotation.objects.filter(pk=identifier).exists():raise DomainError('annotation_exists','This annotation ID is already used.',409)
        row=Annotation.objects.create(id=identifier,user=user,revision=revision,kind=kind,range=location,color=color,note_text=note,quoted_text=quote,quoted_text_truncated=truncated)
        return 201,annotation_data(row),row.version
    return apply_operation(user,operation_id,'annotation.create',data,mutate)


def patch_annotation(user,annotation_id,data,operation_id,base_version):
    def mutate():
        row=Annotation.objects.select_for_update().select_related('revision__edition').filter(pk=annotation_id,user=user,deleted_at=None).first()
        if not row:raise DomainError('not_found','Annotation not found.',404)
        if row.version!=base_version:raise DomainError('version_conflict','Annotation changed.',412,annotation_data(row))
        if not data or set(data)-{'color','note_text'}:raise DomainError('validation_error','Invalid annotation change.',422)
        if 'color' in data:
            if data['color'] not in [None,'gold','mint','rose','lavender'] or (row.kind=='highlight' and data['color'] is None):raise DomainError('validation_error','Invalid highlight color.',422)
            row.color=data['color']
        if 'note_text' in data:row.note_text=_note(data['note_text'])
        row.version+=1;row.save();return 200,annotation_data(row),row.version
    return apply_operation(user,operation_id,'annotation.patch',{'annotation_id':str(annotation_id),'base_version':base_version,'patch':data},mutate)


def delete_annotation(user,annotation_id,operation_id,base_version):
    def mutate():
        row=Annotation.objects.select_for_update().filter(pk=annotation_id,user=user).first()
        if not row:raise DomainError('not_found','Annotation not found.',404)
        if row.deleted_at:return 204,{},row.version
        if row.version!=base_version:raise DomainError('version_conflict','Annotation changed.',412,annotation_data(row))
        row.deleted_at=timezone.now();row.version+=1;row.save();return 204,{},row.version
    return apply_operation(user,operation_id,'annotation.delete',{'annotation_id':str(annotation_id),'base_version':base_version},mutate)


def edition_summary(edition):
    return {'edition_id':str(edition.id),'work_id':str(edition.work_id),'slug':edition.slug,'title':edition.live_revision.title if edition.live_revision_id else edition.work.title,'locale':edition.locale,'available':bool(edition.live_revision_id)}


def saved_set(user,edition_id,saved,operation_id):
    def mutate():
        edition=Edition.objects.select_related('work','live_revision').filter(pk=public_uuid(edition_id)).first()
        if not edition:raise DomainError('not_found','Edition not found.',404)
        if saved:
            row,_=SavedItem.objects.get_or_create(user=user,edition=edition)
            return 200,{'edition_id':str(edition.id),'saved_at':iso(row.created_at),'available':bool(edition.live_revision_id)},1
        SavedItem.objects.filter(user=user,edition=edition).delete();return 204,{},1
    return apply_operation(user,operation_id,'saved.set',{'edition_id':str(edition_id),'saved':saved},mutate)


def list_data(row,detail=False):
    result={'list_id':str(row.id),'name':row.name,'version':row.version,'item_count':row.items.count(),'created_at':iso(row.created_at),'updated_at':iso(row.updated_at)}
    if detail:result['edition_ids']=[str(x) for x in row.items.order_by('sort_order').values_list('edition_id',flat=True)]
    return result


def _list_name(user,name,exclude=None):
    if not isinstance(name,str) or not 1<=len(name.strip())<=80:raise DomainError('validation_error','Use a list name between 1 and 80 characters.',422)
    if PersonalList.objects.filter(user=user,name__iexact=name.strip()).exclude(pk=exclude).exists():raise DomainError('list_name_exists','This list name already exists.',409)
    return name.strip()


def create_list(user,name,operation_id):
    def mutate():
        if PersonalList.objects.filter(user=user).count()>=100:raise DomainError('list_limit','At most 100 lists are supported.',422)
        row=PersonalList.objects.create(user=user,name=_list_name(user,name));return 201,list_data(row),row.version
    return apply_operation(user,operation_id,'list.create',{'name':name},mutate)


def mutate_list(user,list_id,operation_id,base_version,action,payload):
    def mutate():
        row=PersonalList.objects.select_for_update().filter(pk=list_id,user=user).first()
        if not row:raise DomainError('not_found','List not found.',404)
        if row.version!=base_version:raise DomainError('version_conflict','List changed on another device.',412,list_data(row,True))
        if action=='rename':row.name=_list_name(user,payload['name'],row.pk)
        elif action=='delete':row.delete();return 204,{},base_version+1
        else:
            ids=list(row.items.order_by('sort_order').values_list('edition_id',flat=True))
            if action in ['add','remove']:
                eid=public_uuid(payload['edition_id'])
                if not Edition.objects.filter(pk=eid).exists():raise DomainError('not_found','Edition not found.',404)
                if action=='add' and eid not in ids:ids.append(eid)
                if action=='remove' and eid in ids:ids.remove(eid)
            elif action=='reorder':
                new=[public_uuid(x) for x in payload['edition_ids']]
                if len(new)!=len(set(new)) or set(new)!=set(ids):raise DomainError('validation_error','Reorder must contain exactly the list editions once.',422)
                ids=new
            if len(ids)>500:raise DomainError('list_limit','A list can contain at most 500 editions.',422)
            row.items.all().delete();PersonalListItem.objects.bulk_create([PersonalListItem(personal_list=row,edition_id=eid,sort_order=n) for n,eid in enumerate(ids)])
        row.version+=1;row.save();return 200,list_data(row,action!='rename'),row.version
    return apply_operation(user,operation_id,'list.'+action,{'list_id':str(list_id),'base_version':base_version,**payload},mutate)


def vault_data(user):
    from library.services import catalog_card
    progress=Progress.objects.filter(user=user).annotate(finished=Exists(Completion.objects.filter(user=user,edition_id=OuterRef('edition_id'),format=OuterRef('format'),is_complete=True))).filter(finished=False).select_related('edition__work','edition__live_revision').order_by('-updated_at')[:20]
    continuing=[];finished=[]
    for p in progress:
        try:card=catalog_card(p.edition)
        except DomainError:continue
        continuing.append({'card':card,'progress':progress_data(p)})
    for c in Completion.objects.filter(user=user,is_complete=True).select_related('edition__work','edition__live_revision').order_by('-updated_at')[:20]:
        try:card=catalog_card(c.edition)
        except DomainError:continue
        finished.append({'card':card,'completion':completion_data(c)})
    return {'continue':continuing,'saved_count':SavedItem.objects.filter(user=user).count(),'download_count':0,
        'finished_count':Completion.objects.filter(user=user,is_complete=True).count(),'finished':finished,
        'lists':[list_data(x) for x in PersonalList.objects.filter(user=user).order_by('name')[:20]],'legacy_obligations':[]}


def export_personal_data(user):
    return {'reader':vault_data(user),'completion':[completion_data(x) for x in Completion.objects.filter(user=user)],'annotations':[annotation_data(x) for x in Annotation.objects.filter(user=user,deleted_at=None).select_related('revision__edition')]}


def delete_personal_data(user):
    Annotation.objects.filter(user=user).delete();Progress.objects.filter(user=user).delete();Completion.objects.filter(user=user).delete();SavedItem.objects.filter(user=user).delete();PersonalList.objects.filter(user=user).delete()
