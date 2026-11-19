"""Rights-filtered public editorial outlines and separate private series state."""
import re
from uuid import UUID
from django.core.exceptions import ValidationError
from core.api import DomainError
from core.pagination import paginate_queryset
from .collection_models import CatalogCollection,CatalogItem
from . import services as svc


def _context(locale,territory):
    if locale not in ('en','bn') or not isinstance(territory,str) or not re.fullmatch('[A-Z]{2}',territory) or territory=='ZZ':
        raise DomainError('invalid_context','A supported locale and trusted territory are required.',422)


def get_collection(identifier,*,series_only=False):
    rows=CatalogCollection.objects.filter(published=True)
    if series_only:rows=rows.filter(kind='series')
    try:
        try:identifier=UUID(str(identifier));row=rows.get(pk=identifier)
        except (ValueError,TypeError):row=rows.get(slug=identifier)
        return row
    except (CatalogCollection.DoesNotExist,ValidationError):
        raise DomainError('not_found','Collection not found.',404)


def _item_rows(collection,locale):
    return collection.items.filter(edition__locale=locale).select_related('edition__live_revision','edition__work').order_by('sort_order','id')


def _item_card(item,locale,territory):
    edition=item.edition;revision=edition.live_revision
    if not revision or edition.locale!=locale or not svc._live(revision):return None
    formats=svc.available_formats(revision,territory)
    if not formats:return None
    return {'work_id':str(edition.work_id),'edition_id':str(edition.id),'title':revision.title,'subtitle':None,'creators':edition.work.creators,'locale':edition.locale,'house':edition.work.house,'formats':formats,'cover':svc._cover(revision),'access_label':'free' if any(revision.access_policy.get(fmt)=='free' for fmt in formats) else 'pass_required','availability':'available'}


def eligible_items(collection,locale,territory):
    _context(locale,territory)
    return [card for item in _item_rows(collection,locale) if (card:=_item_card(item,locale,territory)) is not None]


def collection_summary(collection,locale,territory,*,cards=None):
    _context(locale,territory)
    cards=[] if cards is None else cards
    return {'collection_id':str(collection.id),'kind':collection.kind,'title':getattr(collection,'title_'+locale),'description':getattr(collection,'description_'+locale)[:2000],'cover':next((c['cover'] for c in cards if c['cover']),None)}


def list_collections(request,locale,territory,*,kind=None):
    _context(locale,territory)
    rows=CatalogCollection.objects.filter(published=True)
    if kind:
        if kind not in ('shelf','series','author','topic'):raise DomainError('invalid_filter','Unsupported collection kind.',422)
        rows=rows.filter(kind=kind)
    return paginate_queryset(request,rows,f'collections:{locale}:{territory}:{kind or "all"}',ordering='slug',serialize=lambda row:collection_summary(row,locale,territory),maximum=100,scan_limit=500)


def collection_detail(request,identifier,locale,territory,*,series_only=False):
    collection=get_collection(identifier,series_only=series_only)
    _context(locale,territory)
    from django.db.models import F
    from .catalog_query import catalog_queryset,card_from_edition
    rows=catalog_queryset(locale,territory).filter(catalog_items__collection=collection).annotate(catalog_item_order=F('catalog_items__sort_order'))
    result=paginate_queryset(request,rows,f'collection:{collection.id}:{collection.version}:{locale}:{territory}',ordering='catalog_item_order',maximum=100)
    return {'collection_id':str(collection.id),'kind':collection.kind,'title':getattr(collection,'title_'+locale),'description':getattr(collection,'description_'+locale),'items':[card_from_edition(row) for row in result['items']],'next_cursor':result['next_cursor']}


def series_member_state(user,collection,locale,territory,*,cards=None):
    """Private projection only; never include this in public Collection JSON/cache."""
    if not getattr(user,'is_authenticated',False):return None
    from reader.models import Progress,Completion
    cards=eligible_items(collection,locale,territory) if cards is None else cards
    ids=[c['edition_id'] for c in cards]
    available={c['edition_id']:set(c['formats']) for c in cards}
    progress={}
    for row in Progress.objects.filter(user=user,edition_id__in=ids).select_related('edition').order_by('-updated_at','-id'):
        if row.revision_id!=row.edition.live_revision_id or row.format not in available.get(str(row.edition_id),set()):continue
        try:svc.authorize_revision(user,row.revision_id,row.format,territory=territory)
        except DomainError:continue
        progress.setdefault(str(row.edition_id),[]).append({'format':row.format,'location':row.location,'updated_at':svc.iso(row.updated_at)})
    finished={str(row.edition_id):True for row in Completion.objects.filter(user=user,edition_id__in=ids,is_complete=True).select_related('edition') if row.revision_id==row.edition.live_revision_id and row.format in available.get(str(row.edition_id),set())}
    return {'items':[{'edition_id':c['edition_id'],'progress':progress.get(c['edition_id'],[]),'complete':finished.get(c['edition_id'],False)} for c in cards]}


def canonical_series_slug(identifier):
    """Published editorial slug, never caller-controlled URL/token data."""
    return get_collection(identifier,series_only=True).slug


def seed_local_collection():
    """Called only by the explicit local-fixture command, never from runtime GETs."""
    from django.conf import settings
    from .models import Edition
    if not settings.LOCAL or not settings.MAISON_LOCAL_FIXTURES:raise DomainError('access_denied','Local fixtures are disabled.',403)
    row,_=CatalogCollection.objects.get_or_create(id='90000000-0000-4000-8000-000000000001',defaults={'slug':'local-original-stories','title_en':'Local original stories','title_bn':'স্থানীয় মৌলিক গল্প','description_en':'Original technical acceptance fixtures; not commercially released.','description_bn':'মৌলিক প্রযুক্তিগত পরীক্ষার গল্প; বাণিজ্যিকভাবে প্রকাশিত নয়।','house':'golpo','kind':'shelf','published':True})
    for ordinal,edition in enumerate(Edition.objects.filter(id__in=['20000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000002']).order_by('locale','id')):
        CatalogItem.objects.get_or_create(collection=row,edition=edition,defaults={'sort_order':ordinal})
    return row
