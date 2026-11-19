from django.contrib import admin,messages
from django.db import transaction
from django.db.models import F
from core.api import DomainError
from .models import Work,Edition,Revision,Unit,Paragraph,Asset,Rights,TimingMap
from .services import transition_revision,clone_revision,queue_catalog_purge

def _queue_live_revisions(identifiers):
    # One call per affected live revision; bulk rights actions do not enqueue once per grant.
    for revision in Revision.objects.filter(pk__in=set(identifiers),state='live',edition__live_revision_id=F('id')).select_related('edition').order_by('id'):
        queue_catalog_purge(revision)


@admin.register(Work)
class WorkAdmin(admin.ModelAdmin):
    list_display=('title','house','slug')
    search_fields=('title','slug')

    @transaction.atomic
    def save_model(self,request,obj,form,change):
        fields=('slug','title','creators','house','topic','level')
        old=Work.objects.select_for_update().filter(pk=obj.pk).values(*fields).first() if change else None
        super().save_model(request,obj,form,change)
        if old and all(old[field]==getattr(obj,field) for field in fields):return
        # The existing helper includes work dependencies, so one live representative
        # invalidates every recorded edition/listing reference for this work.
        from .search import refresh_revision_search
        revisions=list(Revision.objects.filter(edition__work=obj,state='live',edition__live_revision_id=F('id')).select_related('edition__work').order_by('id'))
        for revision in revisions:refresh_revision_search(revision)
        if revisions:_queue_live_revisions([revisions[0].id])

@admin.register(Edition)
class EditionAdmin(admin.ModelAdmin):
    search_fields=('slug','work__title')
    list_display=('slug','locale','live_revision','version')
    readonly_fields=('live_revision','version')

    @transaction.atomic
    def save_model(self,request,obj,form,change):
        fields=('work_id','slug','locale')
        old=Edition.objects.select_for_update().filter(pk=obj.pk).values(*fields).first() if change else None
        super().save_model(request,obj,form,change)
        if old and all(old[field]==getattr(obj,field) for field in fields):return
        from .search import refresh_revision_search
        for revision in Revision.objects.filter(edition=obj,state='live',edition__live_revision_id=F('id')).select_related('edition__work'):refresh_revision_search(revision)
        _queue_live_revisions(Revision.objects.filter(edition=obj).values_list('id',flat=True))

@admin.register(Revision)
class RevisionAdmin(admin.ModelAdmin):
    list_display=('title','state','version','edition','published_at')
    readonly_fields=('state','version','published_at','scheduled_for','created_at','updated_at')
    actions=('mark_ready','publish','withdraw','clone_draft')

    def get_readonly_fields(self,request,obj=None):
        base=list(self.readonly_fields)
        if obj and obj.state!='draft':
            base += ['edition','title','description','content_sha256','anchor_revision','access_policy','download_policy','preview']
        return base

    def _transition(self,request,queryset,action):
        for revision in queryset:
            try:
                transition_revision(request.user,revision.id,action,revision.version,revision.content_sha256,'Explicit local admin '+action)
                self.message_user(request,f'{revision.title}: {action} completed.')
            except DomainError as exc:
                self.message_user(request,str(exc),messages.ERROR)

    @admin.action(description='Validate and mark selected exact revisions ready')
    def mark_ready(self,request,queryset): self._transition(request,queryset,'mark-ready')
    @admin.action(description='Publish selected ready revisions')
    def publish(self,request,queryset): self._transition(request,queryset,'publish')
    @admin.action(description='Withdraw selected live revisions')
    def withdraw(self,request,queryset): self._transition(request,queryset,'withdraw')
    @admin.action(description='Create new draft copies with verified separate locators')
    def clone_draft(self,request,queryset):
        if not request.user.has_perm('library.add_revision'):
            self.message_user(request,'Add revision permission required.',messages.ERROR);return
        for revision in queryset:
            clone=clone_revision(revision.id)
            self.message_user(request,f'Created draft {clone.id}; rights and browser review are pending.')

class ContentAdmin(admin.ModelAdmin):
    def has_change_permission(self,request,obj=None):
        return super().has_change_permission(request,obj) and (obj is None or obj.content_revision().state=='draft')
    def has_delete_permission(self,request,obj=None):
        return super().has_delete_permission(request,obj) and (obj is None or obj.content_revision().state=='draft')

admin.site.register(Unit,ContentAdmin)
admin.site.register(Paragraph,ContentAdmin)
admin.site.register(Asset,ContentAdmin)
admin.site.register(TimingMap,ContentAdmin)

@admin.register(Rights)
class RightsAdmin(admin.ModelAdmin):
    list_display=('revision','format','action','approved','test_only','ends_at','version')
    readonly_fields=('version',)
    @transaction.atomic
    def save_model(self,request,obj,form,change):
        fields=('revision_id','format','action','territories','starts_at','ends_at','approved','test_only','evidence')
        old=Rights.objects.select_for_update().filter(pk=obj.pk).values(*fields).first() if change else None
        if change:obj.version+=1
        super().save_model(request,obj,form,change)
        if old and all(old[field]==getattr(obj,field) for field in fields):return
        _queue_live_revisions([obj.revision_id]+([old['revision_id']] if old else []))

    @transaction.atomic
    def delete_model(self,request,obj):
        revision_id=Rights.objects.select_for_update().get(pk=obj.pk).revision_id
        super().delete_model(request,obj)
        _queue_live_revisions([revision_id])

    @transaction.atomic
    def delete_queryset(self,request,queryset):
        rows=list(queryset.select_for_update().order_by('pk').values_list('pk','revision_id'))
        super().delete_queryset(request,queryset.filter(pk__in=[row[0] for row in rows]))
        _queue_live_revisions([row[1] for row in rows])


from .collection_models import CatalogCollection,CatalogItem

class CatalogItemInline(admin.TabularInline):
    model=CatalogItem
    extra=0
    autocomplete_fields=('edition',)
    ordering=('sort_order','id')


@admin.register(CatalogCollection)
class CatalogCollectionAdmin(admin.ModelAdmin):
    list_display=('slug','kind','house','published','version')
    search_fields=('slug','title_en','title_bn')
    list_filter=('kind','house','published')
    readonly_fields=('version','updated_at')
    inlines=(CatalogItemInline,)

    def _invalidate_editorial_catalog(self):
        # Existing catalog:global URL dependencies cover editorial index/details.
        # If there are no live revisions there is no eligible shared catalog body.
        revision=Revision.objects.filter(state='live',edition__live_revision_id=F('id')).select_related('edition').order_by('id').first()
        if revision:queue_catalog_purge(revision)

    def save_related(self,request,form,formsets,change):
        super().save_related(request,form,formsets,change)
        self._invalidate_editorial_catalog()

    @transaction.atomic
    def delete_model(self,request,obj):
        super().delete_model(request,obj)
        self._invalidate_editorial_catalog()

    @transaction.atomic
    def delete_queryset(self,request,queryset):
        super().delete_queryset(request,queryset)
        self._invalidate_editorial_catalog()


from .search_models import SearchAlias


@admin.register(SearchAlias)
class SearchAliasAdmin(admin.ModelAdmin):
    list_display=('locale','alias_normalized','target_normalized','active','reviewed_by','reviewed_at')
    list_filter=('locale','active')
    search_fields=('alias_normalized','target_normalized')
    readonly_fields=('reviewed_by','reviewed_at')
    def save_model(self,request,obj,form,change):
        from django.utils import timezone
        obj.reviewed_by=request.user;obj.reviewed_at=timezone.now()
        super().save_model(request,obj,form,change)
