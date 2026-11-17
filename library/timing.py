"""Measured, exact-revision audio/text mappings; never percentage-based estimates."""
from django.conf import settings
from core.api import DomainError
from .validation import validate_schema


def validated_segments(mapping):
    from .models import Paragraph
    from .services import prepared_audio
    asset=mapping.asset;revision=mapping.revision
    prepared=prepared_audio(asset)
    if not mapping.measured or mapping.precision not in {'paragraph','sentence'} or mapping.text_sha256!=revision.content_sha256 or mapping.asset_sha256!=asset.sha256:
        raise DomainError('map_unavailable','Measured mapping does not match the released text/audio.',409)
    paragraphs={str(p.anchor_id):p for p in Paragraph.objects.filter(unit=asset.unit)}
    segments=mapping.segments
    if not isinstance(segments,list) or not 1<=len(segments)<=2000:
        raise DomainError('map_unavailable','Mapping requires bounded measured segments.',409)
    last_ms=0;seen={};last_ordinal=0
    for segment in segments:
        validate_schema(segment,'TimingSegment')
        para=paragraphs.get(segment['anchor_id'])
        if (not para or para.ordinal<last_ordinal or segment['start_ms']<last_ms or segment['end_ms']<=segment['start_ms']
            or segment['end_ms']>prepared['duration_ms'] or segment['start_offset_chars']!=seen.get(str(para.anchor_id),0)
            or not segment['start_offset_chars']<segment['end_offset_chars']<=len(para.text)):
            raise DomainError('map_unavailable','Mapping intervals, text bounds or ordering are invalid.',409)
        seen[str(para.anchor_id)]=segment['end_offset_chars'];last_ms=segment['end_ms'];last_ordinal=para.ordinal
    if seen!={key:len(p.text) for key,p in paragraphs.items()}:
        raise DomainError('map_unavailable','Measured map does not cover every paragraph in its audio unit.',409)
    return segments


def map_dto(mapping):
    segments=validated_segments(mapping)
    return {'map_id':str(mapping.id),'edition_revision_id':str(mapping.revision_id),'asset_id':str(mapping.asset_id),
        'asset_sha256':mapping.asset_sha256,'text_sha256':mapping.text_sha256,'anchor_revision':mapping.revision.anchor_revision,
        'format':'audio','precision':mapping.precision,'measured':True,'segments':segments,'next_cursor':None}


def mappings(user,revision_id,territory='IN',unit_id=None):
    from .services import authorize_revision
    revision=authorize_revision(user,revision_id,territory=territory)
    if not settings.FEATURES.get('audio'):return {'edition_revision_id':str(revision.id),'status':'feature_disabled','maps':[]}
    try:authorize_revision(user,revision,'audio',territory=territory)
    except DomainError:return {'edition_revision_id':str(revision.id),'status':'unreleased','maps':[]}
    rows=revision.timing_maps.filter(asset__state='ready',asset__kind='audio_chapter').select_related('revision','asset','asset__unit','asset__revision').order_by('asset__unit__ordinal','id')
    if unit_id:rows=rows.filter(asset__unit_id=unit_id)
    maps=[]
    for row in rows[:5]:
        try:maps.append(map_dto(row))
        except DomainError:continue
    return {'edition_revision_id':str(revision.id),'status':'mapped' if maps else 'unmapped','maps':maps}


def switch_position(user,data,territory='IN'):
    from .services import authorize_revision
    from reader.services import _location
    source=data['from_location'];from_format=source['format'];target=data['to_format']
    revision=authorize_revision(user,data['edition_revision_id'],from_format,territory=territory)
    location,_=_location(revision,from_format,source)
    def result(outcome,to=None,row=None,reason=None):return {'outcome':outcome,'to_location':to,'map_id':str(row.id) if row else None,'precision':row.precision if row else None,'reason_code':reason}
    if from_format==target:return result('mapped',location)
    if 'video' in {from_format,target}:return result('feature_disabled',reason='video_switching_not_enabled')
    if not settings.FEATURES.get('audio'):return result('feature_disabled',reason='audio_not_enabled')
    try:authorize_revision(user,revision,target,territory=territory)
    except DomainError:return result('unreleased',reason='target_format_unavailable')
    rows=revision.timing_maps.filter(asset__unit_id=location['unit_id'],asset__kind='audio_chapter',asset__state='ready').select_related('revision','asset','asset__unit','asset__revision').order_by('id')
    for row in rows:
        try:segments=validated_segments(row)
        except DomainError:continue
        if from_format=='reader':
            chosen=next((s for s in segments if s['anchor_id']==location['anchor_id'] and s['start_offset_chars']<=location['offset_chars']<s['end_offset_chars']),None)
            if chosen is None:
                chosen=next((s for s in reversed(segments) if s['anchor_id']==location['anchor_id'] and s['end_offset_chars']==location['offset_chars']),None)
            if chosen:return result('mapped',{'format':'audio','unit_id':location['unit_id'],'position_ms':chosen['start_ms']},row)
        else:
            chosen=next((s for s in segments if s['start_ms']<=location['position_ms']<s['end_ms']),None)
            if chosen:return result('mapped',{'format':'reader','unit_id':location['unit_id'],'anchor_id':chosen['anchor_id'],'offset_chars':chosen['start_offset_chars']},row)
    return result('unmapped',reason='choose_chapter_or_start')
