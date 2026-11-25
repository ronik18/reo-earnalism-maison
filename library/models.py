"""Revision-scoped local content authority. No provider credentials or legacy tables."""
import uuid
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Work(models.Model):
    HOUSES=('classics','golpo','learn','interview','series','collections')
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=240)
    creators = models.JSONField(default=list)
    house = models.CharField(max_length=32, default='golpo',choices=[(h,h) for h in HOUSES])
    topic = models.CharField(max_length=80, blank=True)
    level = models.CharField(max_length=32, blank=True)
    class Meta:
        db_table = 'maison_work'


class Edition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work = models.ForeignKey(Work, on_delete=models.PROTECT, related_name='editions')
    slug = models.SlugField(unique=True)
    locale = models.CharField(max_length=2, choices=[('en','English'),('bn','Bengali')])
    live_revision = models.ForeignKey('Revision', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    translated_from = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='translations')
    translation_method = models.CharField(max_length=16, blank=True, choices=[('', ''), ('ai', 'ai'), ('ai_edited', 'ai_edited')])
    translation_credit = models.CharField(max_length=160, blank=True)
    translation_model = models.CharField(max_length=80, blank=True)
    class Meta:
        db_table = 'maison_edition'
        constraints = [
            models.CheckConstraint(
                condition=(Q(translated_from__isnull=True, translation_method='')
                           | Q(translated_from__isnull=False, translation_method__in=['ai', 'ai_edited'])),
                name='maison_edition_translation_method'),
            models.CheckConstraint(
                condition=~Q(translation_method='ai_edited') | ~Q(translation_credit=''),
                name='maison_edition_edited_credit'),
        ]

    def clean(self):
        if self.translated_from_id and self.translated_from.locale == self.locale:
            raise ValidationError('A translation must be in a different language from its source.')
        if self.live_revision_id and self.live_revision.edition_id != self.id:
            raise ValidationError('Live revision must belong to this edition.')


class Revision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    edition = models.ForeignKey(Edition, on_delete=models.PROTECT, related_name='revisions')
    title = models.CharField(max_length=240)
    description = models.TextField(blank=True)
    state = models.CharField(max_length=12, default='draft', choices=[(s,s) for s in ('draft','ready','live','retired')])
    version = models.PositiveIntegerField(default=1)
    content_sha256 = models.CharField(max_length=64, blank=True)
    anchor_revision = models.PositiveIntegerField(default=1)
    access_policy = models.JSONField(default=dict, blank=True, help_text='Explicit reader/audio/video: deny, free or paid. Missing means deny.')
    download_policy = models.JSONField(default=dict, blank=True, help_text='Explicit per-format booleans; missing means false.')
    preview = models.JSONField(default=list, blank=True, help_text='Separate bounded public paragraphs, never a full-package URL.')
    validation_evidence = models.JSONField(default=dict, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        db_table = 'maison_edition_revision'
        permissions = [('publish_revision','Can validate, freeze, publish and withdraw revisions')]
        constraints = [models.CheckConstraint(condition=Q(state__in=['draft','ready','live','retired']),name='maison_revision_state')]

    def clean(self):
        if set(self.access_policy) - {'reader','audio','video'} or any(v not in {'deny','free','paid'} for v in self.access_policy.values()):
            raise ValidationError('Invalid explicit access policy.')
        if set(self.download_policy) - {'reader','audio','video'} or any(type(v) is not bool for v in self.download_policy.values()):
            raise ValidationError('Invalid download policy.')
        if len(self.preview) > 3 or sum(len(p.get('text','')) for p in self.preview) > 1200:
            raise ValidationError('Preview is bounded to three paragraphs / 1200 characters.')
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).first()
            frozen = ('title','description','content_sha256','anchor_revision','access_policy','download_policy','preview')
            if old and old.state != 'draft' and any(getattr(old,k) != getattr(self,k) for k in frozen):
                raise ValidationError('Frozen revision content requires a new revision.')

    def save(self, *args, **kwargs):
        self.full_clean()
        result=super().save(*args, **kwargs)
        self.refresh_from_db(fields=['version'])
        return result


class RevisionContent(models.Model):
    """Service and admin guard; PostgreSQL triggers also enforce frozen rows."""
    class Meta:
        abstract = True

    def content_revision(self):
        return self.revision

    def save(self, *args, **kwargs):
        if self.content_revision().state != 'draft':
            raise ValidationError('Only draft revision content may be changed.')
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self,*args,**kwargs):
        if self.content_revision().state != 'draft':
            raise ValidationError('Only draft revision content may be deleted.')
        return super().delete(*args,**kwargs)


class Unit(RevisionContent):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    revision = models.ForeignKey(Revision, on_delete=models.PROTECT, related_name='units')
    title = models.CharField(max_length=240)
    ordinal = models.PositiveIntegerField()
    kind = models.CharField(max_length=12, default='chapter', choices=[('chapter','chapter'),('lesson','lesson'),('episode','episode')])
    duration_ms = models.PositiveBigIntegerField(null=True, blank=True)
    preview = models.BooleanField(default=False)
    class Meta:
        db_table = 'maison_unit'
        ordering = ['ordinal']
        constraints = [models.UniqueConstraint(fields=['revision','ordinal'],name='maison_unit_revision_ordinal')]


class Paragraph(RevisionContent):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    anchor_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='paragraphs')
    ordinal = models.PositiveIntegerField()
    kind = models.CharField(max_length=12, default='paragraph', choices=[('paragraph','paragraph'),('heading','heading'),('verse','verse')])
    text = models.TextField()
    class Meta:
        db_table = 'maison_paragraph_anchor'
        ordering = ['ordinal']
        constraints = [models.UniqueConstraint(fields=['unit','ordinal'],name='maison_paragraph_unit_ordinal')]

    def content_revision(self):
        return self.unit.revision


class Asset(RevisionContent):
    KINDS = ('cover','reader_source','reader_package','audio_chapter','preview_audio','video','timing_map','rights_document')
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    revision = models.ForeignKey(Revision, on_delete=models.PROTECT, related_name='assets')
    unit = models.ForeignKey(Unit, null=True, blank=True, on_delete=models.PROTECT, related_name='assets')
    kind = models.CharField(max_length=24, choices=[(k,k) for k in KINDS])
    state = models.CharField(max_length=12, default='uploading', choices=[(s,s) for s in ('uploading','processing','failed','ready')])
    storage_key = models.CharField(max_length=512, unique=True)
    sha256 = models.CharField(max_length=64)
    bytes = models.PositiveBigIntegerField()
    compressed_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    provider = models.CharField(max_length=8,choices=[('r2','R2'),('stream','Stream')],default='r2')
    duration_ms = models.PositiveBigIntegerField(null=True,blank=True)
    content_type = models.CharField(max_length=100)
    version = models.PositiveIntegerField(default=1)
    copy_verified_bytes = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'maison_asset'
        constraints = [models.CheckConstraint(condition=Q(state__in=['uploading','processing','failed','ready']),name='maison_asset_state'),
            models.CheckConstraint(condition=Q(provider__in=['r2','stream']),name='maison_asset_provider'),
            models.CheckConstraint(condition=Q(duration_ms__isnull=True)|Q(duration_ms__gt=0),name='maison_asset_duration'),
            models.CheckConstraint(condition=Q(provider='r2')|Q(provider='stream',kind='video',storage_key__regex=r'^[a-f0-9]{32}$',duration_ms__isnull=False,duration_ms__gt=0),name='maison_stream_asset_identity'),
            models.CheckConstraint(condition=~Q(kind='preview_audio')|Q(provider='r2',unit__isnull=False,duration_ms__isnull=False,duration_ms__gt=0,duration_ms__lte=120000,bytes__lte=2097152,content_type='audio/mpeg'),name='maison_audio_preview_bounds')]

    def clean(self):
        if self.unit_id and self.unit.revision_id != self.revision_id:
            raise ValidationError('Asset unit must belong to the same revision.')
        if self.provider=='stream':
            import re
            if self.kind!='video' or not re.fullmatch(r'[a-f0-9]{32}',self.storage_key) or not self.duration_ms:
                raise ValidationError('Stream video requires an exact provider UID and measured duration.')
        elif not self.storage_key.startswith(f'revisions/{self.revision_id}/'):
            raise ValidationError('Storage key must be revision scoped.')


class Rights(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    revision = models.ForeignKey(Revision, on_delete=models.PROTECT, related_name='rights')
    format = models.CharField(max_length=12, choices=[(s,s) for s in ('reader','audio','video')])
    action = models.CharField(max_length=12, choices=[(s,s) for s in ('read','preview','download')])
    territories = models.JSONField(default=list)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    approved = models.BooleanField(default=False)
    test_only = models.BooleanField(default=True)
    evidence = models.TextField(blank=True, help_text='Private admin-only evidence. Never serialized publicly.')
    version = models.PositiveIntegerField(default=1)
    class Meta:
        db_table = 'maison_rights_record'
        constraints = [models.CheckConstraint(condition=Q(ends_at__gt=models.F('starts_at')),name='maison_rights_valid_window')]


class TimingMap(RevisionContent):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    revision = models.ForeignKey(Revision, on_delete=models.PROTECT, related_name='timing_maps')
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT)
    text_sha256 = models.CharField(max_length=64)
    asset_sha256 = models.CharField(max_length=64)
    precision = models.CharField(max_length=12, default='paragraph')
    measured = models.BooleanField(default=False)
    segments = models.JSONField(default=list)
    class Meta:
        db_table = 'maison_timing_map'

    def clean(self):
        if self.asset.revision_id != self.revision_id or self.asset.kind != 'audio_chapter':
            raise ValidationError('Timing map must reference the same revision audio output.')
        if self.asset_sha256 != self.asset.sha256 or self.text_sha256 != self.revision.content_sha256:
            raise ValidationError('Timing map hashes must match immutable media and text.')
        if not self.measured:
            raise ValidationError('Estimated timing maps cannot be accepted.')


from .collection_models import CatalogCollection,CatalogItem

from .search_models import SearchDocument,SearchAlias
