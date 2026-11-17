from django.contrib import admin,messages
from core.api import DomainError
from .models import Work,Edition,Revision,Unit,Paragraph,Asset,Rights,TimingMap
from .services import transition_revision,clone_revision

@admin.register(Work)
class WorkAdmin(admin.ModelAdmin):
    list_display=('title','house','slug')
    search_fields=('title','slug')

@admin.register(Edition)
class EditionAdmin(admin.ModelAdmin):
    list_display=('slug','locale','live_revision','version')
    readonly_fields=('live_revision','version')

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
    def save_model(self,request,obj,form,change):
        if change: obj.version+=1
        super().save_model(request,obj,form,change)
