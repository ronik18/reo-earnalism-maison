from django.contrib import admin
from .models import Track,Lesson,InterviewQuestion,Quiz,Question,QuestionOption,QuizAttempt,LessonCompletion

class OptionInline(admin.TabularInline):
    model=QuestionOption
    extra=0

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    inlines=(OptionInline,)
    list_display=('prompt','quiz','ordinal')

admin.site.register([Track,Lesson,InterviewQuestion,Quiz])

@admin.register(QuizAttempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display=('id','user','quiz','status','score','version')
    def has_add_permission(self,request): return False
    def has_change_permission(self,request,obj=None): return False
    def has_delete_permission(self,request,obj=None): return False

@admin.register(LessonCompletion)
class CompletionAdmin(admin.ModelAdmin):
    def has_add_permission(self,request): return False
    def has_change_permission(self,request,obj=None): return False
