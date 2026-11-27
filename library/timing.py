"""Measured, exact-revision audio/text mappings; never percentage-based estimates."""
from django.conf import settings
from core.api import DomainError
from .validation import validate_schema


def _media_duration_ms(asset):
    """Measured duration of the map's media: prepared audio evidence, or the ready film of the configured provider."""
    if asset.kind=='video':
        from .services import video_provider
        if asset.provider!=video_provider() or not asset.unit_id or not asset.duration_ms:
            raise DomainError('map_unavailable','Film mapping requires a measured film of the configured provider.',409)
        return asset.duration_ms
    from .services import prepared_audio
    return prepared_audio(asset)['duration_ms']


def validated_segments(mapping,paragraphs=None):
    """Segments of an exact, measured audio or film map. `paragraphs` ({anchor: Paragraph} of the map's unit) saves
    the per-map query when one unit's maps are checked together."""
    from .models import Paragraph
    asset=mapping.asset;revision=mapping.revision
    duration_ms=_media_duration_ms(asset)
    if not mapping.measured or mapping.precision not in {'paragraph','sentence'} or mapping.text_sha256!=revision.content_sha256 or mapping.asset_sha256!=asset.sha256:
        raise DomainError('map_unavailable','Measured mapping does not match the released text/audio.',409)
    if paragraphs is None:paragraphs={str(p.anchor_id):p for p in Paragraph.objects.filter(unit=asset.unit)}
    segments=mapping.segments
    if not isinstance(segments,list) or not 1<=len(segments)<=2000:
        raise DomainError('map_unavailable','Mapping requires bounded measured segments.',409)
    last_ms=0;seen={};last_ordinal=0
    for segment in segments:
        validate_schema(segment,'TimingSegment')
        para=paragraphs.get(segment['anchor_id'])
        if (not para or para.ordinal<last_ordinal or segment['start_ms']<last_ms or segment['end_ms']<=segment['start_ms']
            or segment['end_ms']>duration_ms or segment['start_offset_chars']!=seen.get(str(para.anchor_id),0)
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


def _precision_rank():
    """Sentence first, then paragraph, then word; anything else last."""
    from django.db.models import Case,IntegerField,Value,When
    return Case(When(precision='sentence',then=Value(0)),When(precision='paragraph',then=Value(1)),When(precision='word',then=Value(2)),default=Value(3),output_field=IntegerField())


def mappings(user,revision_id,territory='IN',unit_id=None,asset_id=None):
    from .services import authorize_revision
    revision=authorize_revision(user,revision_id,territory=territory)
    if not settings.FEATURES.get('audio'):return {'edition_revision_id':str(revision.id),'status':'feature_disabled','maps':[]}
    try:authorize_revision(user,revision,'audio',territory=territory)
    except DomainError:return {'edition_revision_id':str(revision.id),'status':'unreleased','maps':[]}
    rows=revision.timing_maps.filter(asset__state='ready',asset__kind='audio_chapter').select_related('revision','asset','asset__unit','asset__revision').annotate(_rank=_precision_rank()).order_by('asset__unit__ordinal','asset_id','_rank','id')
    if unit_id:rows=rows.filter(asset__unit_id=unit_id)
    from .services import chosen_audio
    chosen,by_unit=chosen_audio(user,revision)
    chosen_ids=[asset.id for asset,_ in chosen]
    if asset_id:  # a listener's quality override: that rendition's own map, when it is one of this revision's ready renditions
        wanted=str(asset_id)
        if any(str(asset.id)==wanted for options in by_unit.values() for _,(asset,_data) in options):chosen_ids=[a.id for a in [x for options in by_unit.values() for _,(x,_d) in options] if str(a.id)==wanted]
    rows=rows.filter(asset_id__in=chosen_ids)  # the rendition the player bootstrap lists for each unit
    maps=[]
    done=set()  # one map per unit (best precision that validates); the cap counts units
    for row in rows:
        if row.asset_id in done:continue
        try:maps.append(map_dto(row))
        except DomainError:continue
        done.add(row.asset_id)
        if len(done)==5:break
    return {'edition_revision_id':str(revision.id),'status':'mapped' if maps else 'unmapped','maps':maps}


def _unit_paragraphs(unit_id):
    from .models import Paragraph
    return {str(p.anchor_id):p for p in Paragraph.objects.filter(unit_id=unit_id)}


def _film_maps(revision,unit_id):
    """Maps of the one film the Watch player opens for this unit (web.views.video: the configured provider's ready
    film with a duration, lowest id first; Stream films must match the unit duration), best precision first."""
    from django.db.models import F
    from .models import Asset
    from .services import video_provider
    provider=video_provider()
    films=Asset.objects.filter(revision=revision,unit_id=unit_id,kind='video',state='ready',provider=provider,duration_ms__gt=0)
    if provider=='stream':films=films.filter(duration_ms=F('unit__duration_ms'))
    film=films.order_by('id').values('id')[:1]
    return revision.timing_maps.filter(asset_id__in=film).select_related('revision','asset','asset__unit','asset__revision').annotate(_rank=_precision_rank()).order_by('_rank','id')[:4]


def _audio_maps(revision,unit_id):
    return revision.timing_maps.filter(asset__unit_id=unit_id,asset__kind='audio_chapter',asset__state='ready').select_related('revision','asset','asset__unit','asset__revision').annotate(_rank=_precision_rank()).order_by('_rank','id')[:10]


def _checked(rows,unit_id):
    """(row, segments) for each map that validates; one paragraph query for the unit, not one per map."""
    paragraphs=None
    for row in rows:
        if paragraphs is None:paragraphs=_unit_paragraphs(unit_id)
        try:yield row,validated_segments(row,paragraphs)
        except DomainError:continue


def _segment_at_anchor(segments,anchor_id,offset_chars):
    chosen=next((s for s in segments if s['anchor_id']==anchor_id and s['start_offset_chars']<=offset_chars<s['end_offset_chars']),None)
    if chosen is None:  # the paragraph's very end belongs to its last segment
        chosen=next((s for s in reversed(segments) if s['anchor_id']==anchor_id and s['end_offset_chars']==offset_chars),None)
    return chosen


def _segment_at_ms(segments,position_ms,between=False):
    """The segment playing at position_ms. A film also holds picture with no narration (scene lead-ins and tails,
    the credits): with between=True such a position belongs to the segment last narrated before it. Before the
    first narrated segment (the title card) nothing is mapped."""
    chosen=next((s for s in segments if s['start_ms']<=position_ms<s['end_ms']),None)
    if chosen is None and between:
        chosen=next((s for s in reversed(segments) if s['start_ms']<=position_ms),None)
    return chosen


def switch_position(user,data,territory='IN'):
    """Map a Read, Listen or Watch position to another format through exact measured maps only.

    reader <-> audio and reader <-> video use the target's (or source's) own map; audio <-> video goes through the
    text: the source map gives the anchor, the target map gives the time. A video target or source needs the video
    feature, rights and access for both formats, and a live revision: a draft's film timing is never served."""
    from .services import authorize_revision,_live
    from reader.services import _location
    source=data['from_location'];from_format=source['format'];target=data['to_format']
    revision=authorize_revision(user,data['edition_revision_id'],from_format,territory=territory)
    location,_=_location(revision,from_format,source)
    def result(outcome,to=None,row=None,reason=None):return {'outcome':outcome,'to_location':to,'map_id':str(row.id) if row else None,'precision':row.precision if row else None,'reason_code':reason}
    if from_format==target:return result('mapped',location)
    formats={from_format,target}
    if 'video' in formats and settings.FEATURES.get('video') is not True:return result('feature_disabled',reason='video_not_enabled')
    if 'audio' in formats and not settings.FEATURES.get('audio'):return result('feature_disabled',reason='audio_not_enabled')
    try:authorize_revision(user,revision,target,territory=territory)
    except DomainError:return result('unreleased',reason='target_format_unavailable')
    if 'video' in formats and not _live(revision):return result('unreleased',reason='target_format_unavailable')
    unit_id=location['unit_id']
    maps={'audio':_audio_maps,'video':_film_maps}
    unmapped=result('unmapped',reason='choose_chapter_or_start')
    if from_format=='reader':
        anchor_id,offset_chars,source_row=location['anchor_id'],location['offset_chars'],None
    else:
        for source_row,segments in _checked(maps[from_format](revision,unit_id),unit_id):
            chosen=_segment_at_ms(segments,location['position_ms'],between=from_format=='video')
            if chosen:break
        else:return unmapped
        anchor_id,offset_chars=chosen['anchor_id'],chosen['start_offset_chars']
        if target=='reader':return result('mapped',{'format':'reader','unit_id':unit_id,'anchor_id':anchor_id,'offset_chars':offset_chars},source_row)
    for row,segments in _checked(maps[target](revision,unit_id),unit_id):
        chosen=_segment_at_anchor(segments,anchor_id,offset_chars)
        if chosen:return result('mapped',{'format':target,'unit_id':unit_id,'position_ms':chosen['start_ms']},row)
    return unmapped
