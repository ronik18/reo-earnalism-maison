import uuid
from django.conf import settings
from django.db import models
from django.db.models.functions import Lower


class Progress(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    edition=models.ForeignKey('library.Edition',on_delete=models.PROTECT)
    revision=models.ForeignKey('library.Revision',on_delete=models.PROTECT)
    format=models.CharField(max_length=8,choices=[(x,x) for x in ['reader','audio','video']])
    location=models.JSONField(null=True)
    fraction_complete=models.DecimalField(max_digits=7,decimal_places=6,default=0)
    version=models.PositiveBigIntegerField(default=1)
    last_operation_id=models.UUIDField()
    client_occurred_at=models.DateTimeField(null=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        db_table='maison_progress'
        constraints=[models.UniqueConstraint(fields=['user','edition','format'],name='maison_progress_scope_uq'),
                     models.CheckConstraint(condition=models.Q(fraction_complete__gte=0,fraction_complete__lte=1),name='maison_progress_fraction')]
        indexes=[models.Index(fields=['user','-updated_at'],name='maison_progress_continue_idx')]


class Completion(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    edition=models.ForeignKey('library.Edition',on_delete=models.PROTECT)
    revision=models.ForeignKey('library.Revision',on_delete=models.PROTECT)
    format=models.CharField(max_length=8,choices=[(x,x) for x in ['reader','audio','video']])
    is_complete=models.BooleanField(default=False)
    completed_at=models.DateTimeField(null=True)
    version=models.PositiveBigIntegerField(default=1)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        db_table='maison_completion'
        constraints=[models.UniqueConstraint(fields=['user','edition','format'],name='maison_completion_scope_uq'),
                     models.CheckConstraint(condition=models.Q(is_complete=False,completed_at__isnull=True)|models.Q(is_complete=True,completed_at__isnull=False),name='maison_completion_state')]


class Annotation(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    revision=models.ForeignKey('library.Revision',on_delete=models.PROTECT)
    kind=models.CharField(max_length=12,choices=[(x,x) for x in ['bookmark','highlight','note']])
    range=models.JSONField()
    color=models.CharField(max_length=12,null=True,choices=[(x,x) for x in ['gold','mint','rose','lavender']])
    note_text=models.TextField(null=True)
    quoted_text=models.TextField(default='')
    quoted_text_truncated=models.BooleanField(default=False)
    version=models.PositiveBigIntegerField(default=1)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    deleted_at=models.DateTimeField(null=True)
    class Meta:
        db_table='maison_annotation'
        constraints=[models.CheckConstraint(condition=models.Q(color__isnull=True)|models.Q(color__in=['gold','mint','rose','lavender']),name='maison_annotation_palette')]
        indexes=[models.Index(fields=['user','revision','deleted_at'],name='maison_annotation_reader_idx')]


class SavedItem(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    edition=models.ForeignKey('library.Edition',on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='maison_saved_item'
        constraints=[models.UniqueConstraint(fields=['user','edition'],name='maison_saved_scope_uq')]


class PersonalList(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    name=models.CharField(max_length=100)
    version=models.PositiveBigIntegerField(default=1)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        db_table='maison_personal_list'
        constraints=[models.UniqueConstraint('user',Lower('name'),name='maison_list_name_uq')]


class PersonalListItem(models.Model):
    personal_list=models.ForeignKey(PersonalList,on_delete=models.CASCADE,related_name='items')
    edition=models.ForeignKey('library.Edition',on_delete=models.PROTECT)
    sort_order=models.PositiveIntegerField()
    added_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='maison_personal_list_item'
        ordering=['sort_order']
        constraints=[models.UniqueConstraint(fields=['personal_list','edition'],name='maison_list_edition_uq'),
                     models.UniqueConstraint(fields=['personal_list','sort_order'],name='maison_list_order_uq',deferrable=models.Deferrable.DEFERRED)]
