import hashlib
import unicodedata
import uuid
from functools import lru_cache
from decimal import Decimal
from django.db import transaction
from django.db.models import Count,Exists,OuterRef,Q
from django.db.models.functions import Length
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from core.api import DomainError,public_uuid
from core.services import apply_operation
from library.models import Asset,Edition,Revision,Unit,Paragraph
from library.services import authorize_revision
from .models import Progress,Completion,Annotation,SavedItem,PersonalList,PersonalListItem


def iso(value):return value.isoformat().replace('+00:00','Z') if value else None


def _edition(value,user=None):
    row=Edition.objects.select_related('live_revision').filter(pk=public_uuid(value)).first()
    if row:
        from library.services import reviewable_edition
        row=reviewable_edition(row,user)
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


def _layout(revision,key,table):
    """Book-wide character/audio offsets. Frozen content is immutable (DB trigger), so it is cached
    by revision and content hash; an unknown anchor or unit forces a fresh build."""
    layout=None if revision.state=='draft' else _frozen_layout(revision.id,revision.content_sha256)
    return layout if layout and key in layout[table] else _build_layout(revision.id)


def _build_layout(revision_id):
    units=list(Unit.objects.filter(revision_id=revision_id).order_by('ordinal').values_list('id','duration_ms'))
    chars={};total_chars=0
    for anchor,size in Paragraph.objects.filter(unit__revision_id=revision_id).order_by('unit__ordinal','ordinal').values_list('anchor_id',Length('text')):
        chars[anchor]=total_chars;total_chars+=size
    ms={};total_ms=0
    for unit,duration in units:
        ms[unit]=total_ms;total_ms+=duration or 0
    return {'chars_before':chars,'total_chars':total_chars,'ms_before':ms,'total_ms':total_ms}


@lru_cache(maxsize=32)  # ~1 MiB per 10k-paragraph book; bounded per worker
def _frozen_layout(revision_id,content_sha256):
    return _build_layout(revision_id)


def _film_durations(revision):
    """Unit id -> (ordinal, duration) of its ready film from the configured provider (one query)."""
    from library.services import video_provider
    rows=Asset.objects.filter(revision=revision,kind='video',state='ready',provider=video_provider(),
                              unit__isnull=False,duration_ms__isnull=False).values_list('unit_id','unit__ordinal','duration_ms')
    return {unit:(ordinal,duration) for unit,ordinal,duration in rows}


def _location(revision,format,loc):
    if not isinstance(loc,dict) or loc.get('format')!=format:raise DomainError('validation_error','Location format does not match.',422)
    allowed={'format','unit_id','anchor_id','offset_chars'} if format=='reader' else {'format','unit_id','position_ms'}
    if set(loc)!=allowed:raise DomainError('validation_error','Invalid location fields.',422)
    unit=Unit.objects.filter(pk=public_uuid(loc['unit_id']),revision=revision).first()
    if not unit:raise DomainError('invalid_anchor','Unit does not belong to this revision.',422)
    if format=='reader':
        para=Paragraph.objects.filter(anchor_id=public_uuid(loc['anchor_id']),unit=unit).first()
        if not para or not _boundary(para.text,loc['offset_chars']):raise DomainError('invalid_anchor','Invalid text boundary.',422)
        layout=_layout(revision,para.anchor_id,'chars_before')
        fraction=min(Decimal(1),Decimal(layout['chars_before'][para.anchor_id]+loc['offset_chars'])/Decimal(layout['total_chars'] or 1))
    elif format=='video':
        # Films carry their own duration on the ready film asset; unit.duration_ms belongs to audio.
        films=_film_durations(revision)
        if type(loc['position_ms'])!=int or loc['position_ms']<0 or unit.id not in films or loc['position_ms']>films[unit.id][1]:raise DomainError('invalid_position','Position exceeds known media duration.',422)
        before=sum(duration for ordinal,duration in films.values() if ordinal<unit.ordinal)
        fraction=min(Decimal(1),Decimal(before+loc['position_ms'])/Decimal(sum(d for _,d in films.values()) or 1))
    else:
        if type(loc['position_ms'])!=int or loc['position_ms']<0 or unit.duration_ms is None or loc['position_ms']>unit.duration_ms:raise DomainError('invalid_position','Position exceeds known media duration.',422)
        layout=_layout(revision,unit.id,'ms_before')
        fraction=min(Decimal(1),Decimal(layout['ms_before'][unit.id]+loc['position_ms'])/Decimal(layout['total_ms'] or 1))
    return {k:str(v) if k.endswith('_id') else v for k,v in loc.items()},fraction


def progress_data(row,edition=None,format='reader'):
    if row is None:
        return {'edition_id':str(edition.id),'edition_revision_id':str(edition.live_revision_id),'format':format,'location':None,'fraction_complete':0,'version':0,'last_operation_id':None,'updated_at':None}
    return {'edition_id':str(row.edition_id),'edition_revision_id':str(row.revision_id),'format':row.format,'location':row.location,'fraction_complete':float(row.fraction_complete),'version':row.version,'last_operation_id':str(row.last_operation_id),'updated_at':iso(row.updated_at)}


def get_progress(user,edition_id,format='reader',territory='IN'):
    edition=_edition(edition_id,user);authorize_revision(user,edition.live_revision,format,territory=territory)
    row=Progress.objects.filter(user=user,edition=edition,format=format).first()
    return progress_data(row,edition,format)


def set_progress(user,edition_id,format,data,base_version,territory='IN'):
    payload={'edition_id':str(edition_id),'format':format,'base_version':base_version,**data}
    def mutate():
        edition=_edition(edition_id,user)
        if str(data.get('edition_revision_id'))!=str(edition.live_revision_id):raise DomainError('edition_revision_changed','Reload this edition revision before choosing a position.',409)
        revision=authorize_revision(user,edition.live_revision,format,territory=territory)
        loc,fraction=_location(revision,format,data.get('location'))
        row=Progress.objects.select_for_update().filter(user=user,edition=edition,format=format).first()
        current=progress_data(row,edition,format)
        if current['version']!=base_version:raise DomainError('version_conflict','Progress changed on another device.',412,current)
        try:occurred=parse_datetime(data.get('occurred_at',''))
        except (ValueError,TypeError):raise DomainError('validation_error','Use a valid aware UTC occurrence time.',422)
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
    edition=_edition(edition_id,user);authorize_revision(user,edition.live_revision,format,territory=territory)
    return completion_data(Completion.objects.filter(user=user,edition=edition,format=format).first(),edition,format)


def set_completion(user,edition_id,format,data,base_version,territory='IN'):
    if type(data.get('is_complete'))!=bool:raise DomainError('validation_error','is_complete must be a boolean.',422)
    payload={'edition_id':str(edition_id),'format':format,'base_version':base_version,**data}
    def mutate():
        edition=_edition(edition_id,user);revision=authorize_revision(user,edition.live_revision,format,territory=territory)
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


def annotation_data(row,user=None):
    valid=row.revision.edition.live_revision_id==row.revision_id
    if not row.revision.edition.live_revision_id:
        from library.services import can_review_draft
        if can_review_draft(user,row.revision):
            try:
                _,quote,truncated=_range(row.revision,row.range,row.kind)
                valid=quote==row.quoted_text and truncated==row.quoted_text_truncated
            except DomainError:valid=False
    return {'annotation_id':str(row.id),'edition_revision_id':str(row.revision_id),'kind':row.kind,'range':row.range,'color':row.color,'note_text':row.note_text,'quoted_text':row.quoted_text,'quoted_text_truncated':row.quoted_text_truncated,'version':row.version,'created_at':iso(row.created_at),'updated_at':iso(row.updated_at),'anchor_status':'valid' if valid else 'orphaned'}


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
        return 201,annotation_data(row,user),row.version
    return apply_operation(user,operation_id,'annotation.create',data,mutate)


def patch_annotation(user,annotation_id,data,operation_id,base_version):
    def mutate():
        row=Annotation.objects.select_for_update().select_related('revision__edition').filter(pk=annotation_id,user=user,deleted_at=None).first()
        if not row:raise DomainError('not_found','Annotation not found.',404)
        if row.version!=base_version:raise DomainError('version_conflict','Annotation changed.',412,annotation_data(row,user))
        if not data or set(data)-{'color','note_text'}:raise DomainError('validation_error','Invalid annotation change.',422)
        if 'color' in data:
            if data['color'] not in [None,'gold','mint','rose','lavender'] or (row.kind=='highlight' and data['color'] is None):raise DomainError('validation_error','Invalid highlight color.',422)
            row.color=data['color']
        if 'note_text' in data:row.note_text=_note(data['note_text'])
        row.version+=1;row.save();return 200,annotation_data(row,user),row.version
    return apply_operation(user,operation_id,'annotation.patch',{'annotation_id':str(annotation_id),'base_version':base_version,'patch':data},mutate)


def delete_annotation(user,annotation_id,operation_id,base_version):
    def mutate():
        row=Annotation.objects.select_for_update().filter(pk=annotation_id,user=user).first()
        if not row:raise DomainError('not_found','Annotation not found.',404)
        if row.deleted_at:return 204,{},row.version
        if row.version!=base_version:raise DomainError('version_conflict','Annotation changed.',412,annotation_data(row,user))
        row.deleted_at=timezone.now();row.version+=1;row.save();return 204,{},row.version
    return apply_operation(user,operation_id,'annotation.delete',{'annotation_id':str(annotation_id),'base_version':base_version},mutate)


def edition_summary(edition):
    return {'edition_id':str(edition.id),'work_id':str(edition.work_id),'slug':edition.slug,'title':edition.live_revision.title if edition.live_revision_id else edition.work.title,'locale':edition.locale,'available':bool(edition.live_revision_id)}


def _savable(edition_id,adding,user):
    """New saves need a published (or reviewer-visible) edition; removal works for anything already saved."""
    if adding:return _edition(edition_id,user)
    edition=Edition.objects.filter(pk=public_uuid(edition_id)).first()
    if not edition:raise DomainError('not_found','Edition not found.',404)
    return edition


def saved_set(user,edition_id,saved,operation_id):
    def mutate():
        edition=_savable(edition_id,saved,user)
        if saved:
            row,_=SavedItem.objects.get_or_create(user=user,edition=edition)
            return 200,{'edition_id':str(edition.id),'saved_at':iso(row.created_at),'available':bool(edition.live_revision_id)},1
        SavedItem.objects.filter(user=user,edition=edition).delete();return 204,{},1
    return apply_operation(user,operation_id,'saved.set',{'edition_id':str(edition_id),'saved':saved},mutate)


def list_data(row,detail=False):
    count=row.item_total if hasattr(row,'item_total') else row.items.count()
    result={'list_id':str(row.id),'name':row.name,'version':row.version,'item_count':count,'created_at':iso(row.created_at),'updated_at':iso(row.updated_at)}
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
                eid=_savable(payload['edition_id'],action=='add',user).pk
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


VAULT_SUMMARY_SCAN_LIMIT=500


class Shelf:
    """Batch shelf serialization: one catalog query per prepared slice, one for corrected-edition resumes."""
    def __init__(self,territory,user=None):
        self.territory=territory;self.user=user;self.cards={};self.resume={}

    def prepare(self,rows):
        from library.services import catalog_cards_for
        self.cards.update(catalog_cards_for([row.edition for row in rows if row.edition_id not in self.cards],self.territory,self.user))
        self._prepare_resume([row for row in rows if isinstance(row,Progress) and row.revision_id!=row.edition.live_revision_id
                              and self.cards.get(row.edition_id) and row.location and row.pk not in self.resume])

    def available(self,edition_id):
        return self.cards.get(edition_id) is not None

    def _prepare_resume(self,stale):
        """A correction keeps the book on the shelf and resumes at the same chapter's start (LLD 7, 10)."""
        if not stale:return
        old=dict(Unit.objects.filter(pk__in=[r.location['unit_id'] for r in stale]).values_list('pk','ordinal'))
        wanted=Q()
        for row in stale:wanted|=Q(revision_id=row.edition.live_revision_id,ordinal__in=[old.get(public_uuid(row.location['unit_id'])),1])
        chapters={(u.revision_id,u.ordinal):u for u in Unit.objects.filter(wanted)}
        first=dict(Paragraph.objects.filter(unit__in=list(chapters.values())).order_by('unit_id','ordinal').distinct('unit_id').values_list('unit_id','anchor_id'))
        for row in stale:
            revision=row.edition.live_revision_id
            unit=chapters.get((revision,old.get(public_uuid(row.location['unit_id'])))) or chapters.get((revision,1))
            if unit is None or (row.format=='reader' and unit.pk not in first):self.resume[row.pk]=None;continue
            location={'format':'reader','unit_id':str(unit.pk),'anchor_id':str(first[unit.pk]),'offset_chars':0} if row.format=='reader' else {'format':row.format,'unit_id':str(unit.pk),'position_ms':0}
            self.resume[row.pk]={**progress_data(row),'edition_revision_id':str(revision),'location':location}

    def entry(self,row,kind):
        card=self.cards.get(row.edition_id)
        if card is None:return None
        if kind=='completion':return {'card':card,'completion':completion_data(row)}
        progress=self.resume[row.pk] if row.pk in self.resume else progress_data(row)
        return {'card':card,'progress':progress} if progress else None

    def take(self,rows,kind,bound=20):
        """First `bound` eligible entries, preparing growing slices so a full shelf costs one slice."""
        rows=list(rows[:VAULT_SUMMARY_SCAN_LIMIT]);values=[];start=0;size=bound+1
        while start<len(rows) and len(values)<bound:
            chunk=rows[start:start+size];self.prepare(chunk)
            values+=[entry for row in chunk if (entry:=self.entry(row,kind)) is not None]
            start+=len(chunk);size*=2
        return values[:bound]


def vault_data(user,territory='IN',request=None):
    from core.pagination import paginate_queryset
    from .models import DownloadLicense
    section=request.GET.get('section','summary') if request else 'summary'
    if section not in ('summary','continue','finished','lists'):raise DomainError('validation_error','Invalid Vault section.',422)
    if section=='summary' and request and any(k in request.GET for k in ('cursor','limit')):raise DomainError('validation_error','Choose an explicit Vault section to paginate.',422)
    progress=Progress.objects.filter(user=user).annotate(finished=Exists(Completion.objects.filter(user=user,edition_id=OuterRef('edition_id'),format=OuterRef('format'),is_complete=True))).filter(finished=False).select_related('edition').order_by('-updated_at','-id')
    completions=Completion.objects.filter(user=user,is_complete=True).select_related('edition').order_by('-updated_at','-id')
    lists=PersonalList.objects.filter(user=user).annotate(item_total=Count('items'))
    shelf=Shelf(territory,user)
    result={'continue':[],'saved_count':SavedItem.objects.filter(user=user).count(),'download_count':DownloadLicense.objects.filter(user=user,revoked_at=None,expires_at__gt=timezone.now()).count(),'finished_count':Completion.objects.filter(user=user,is_complete=True).count(),'finished':[],'lists':[],'legacy_obligations':[]}
    if section=='summary':
        result.update({'continue':shelf.take(progress,'progress'),'finished':shelf.take(completions,'completion'),'lists':[list_data(x) for x in lists.order_by('name','id')[:20]]})
    else:
        if section=='lists':
            page=paginate_queryset(request,lists,'vault:lists',ordering='name',maximum=20)
            page['items']=[list_data(x) for x in page['items']]
        else:
            kind='progress' if section=='continue' else 'completion'
            page=paginate_queryset(request,progress if section=='continue' else completions,'vault:'+section+':'+territory,ordering='-updated_at',maximum=20,
                                   prepare=shelf.prepare,serialize=lambda row:shelf.entry(row,kind))
        result[section]=page['items']
        result.update(section=section,next_cursor=page['next_cursor'],has_more=page['has_more'])
    return result


def export_personal_data(user):
    return {'reader':vault_data(user),'completion':[completion_data(x) for x in Completion.objects.filter(user=user)],'annotations':[annotation_data(x,user) for x in Annotation.objects.filter(user=user,deleted_at=None).select_related('revision__edition')]}


def delete_personal_data(user):
    Annotation.objects.filter(user=user).delete();Progress.objects.filter(user=user).delete();Completion.objects.filter(user=user).delete();SavedItem.objects.filter(user=user).delete();PersonalList.objects.filter(user=user).delete()
