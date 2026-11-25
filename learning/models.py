import uuid
from django.conf import settings
from django.db import models,transaction
from django.db.models import Q,F

class Track(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    title=models.CharField(max_length=240)
    locale=models.CharField(max_length=2,choices=[('en','English'),('bn','Bengali')])
    kind=models.CharField(max_length=20,choices=[('learning','learning'),('sde_interview','sde_interview')],default='learning')
    description=models.TextField()
    duration_days=models.PositiveIntegerField(null=True,blank=True)
    company_style=models.CharField(max_length=80,blank=True)
    access=models.CharField(max_length=8,choices=[('free','free'),('paid','paid'),('deny','deny')],default='deny')
    edition=models.ForeignKey('library.Edition',on_delete=models.PROTECT,null=True,blank=True)
    published=models.BooleanField(default=False)
    sponsor_name=models.CharField(max_length=120,blank=True)
    sponsor_url=models.URLField(blank=True)
    sponsor_approved_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    class Meta:
        db_table='maison_track'
        constraints=[models.CheckConstraint(condition=Q(sponsor_name='')|Q(sponsor_approved_by__isnull=False),name='maison_track_sponsor_approved')]

class Lesson(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    track=models.ForeignKey(Track,on_delete=models.PROTECT,related_name='lessons')
    title=models.CharField(max_length=240)
    ordinal=models.PositiveIntegerField()
    body=models.JSONField(default=list)
    requires_previous=models.BooleanField(default=False)
    completion_rule=models.CharField(max_length=20,choices=[('explicit','explicit'),('quiz_pass','quiz_pass')],default='explicit')
    pass_score=models.PositiveSmallIntegerField(default=100)
    unit=models.ForeignKey('library.Unit',on_delete=models.PROTECT,null=True,blank=True)
    version=models.PositiveIntegerField(default=1)
    class Meta:
        db_table='maison_lesson'
        ordering=['ordinal']
        constraints=[models.UniqueConstraint(fields=['track','ordinal'],name='maison_lesson_track_ordinal'),models.CheckConstraint(condition=Q(pass_score__gte=0,pass_score__lte=100),name='maison_lesson_score_range')]

class LessonCompletion(models.Model):
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    lesson=models.ForeignKey(Lesson,on_delete=models.PROTECT)
    completed_at=models.DateTimeField(auto_now_add=True)
    lesson_version=models.PositiveIntegerField(default=1)
    quiz_version=models.PositiveIntegerField(null=True,blank=True)
    class Meta:
        db_table='maison_lesson_completion'
        constraints=[models.UniqueConstraint(fields=['user','lesson'],name='maison_completion_user_lesson')]

class InterviewQuestion(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    track=models.ForeignKey(Track,on_delete=models.PROTECT,related_name='interview_questions')
    topic=models.CharField(max_length=80)
    difficulty=models.CharField(max_length=16,choices=[(s,s) for s in ('foundation','intermediate','advanced')])
    company_style=models.CharField(max_length=80,blank=True)
    prompt=models.TextField()
    model_answer=models.TextField()
    rubric=models.JSONField(default=list)
    class Meta:
        db_table='maison_interview_question'

class Quiz(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    lesson=models.OneToOneField(Lesson,on_delete=models.PROTECT,related_name='quiz')
    version=models.PositiveIntegerField(default=1)
    max_attempts=models.PositiveIntegerField(null=True,blank=True)
    class Meta:
        db_table='maison_quiz'

class Question(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    quiz=models.ForeignKey(Quiz,on_delete=models.PROTECT,related_name='questions')
    ordinal=models.PositiveIntegerField()
    prompt=models.TextField()
    explanation=models.TextField()
    class Meta:
        db_table='maison_question'
        ordering=['ordinal']
        constraints=[models.UniqueConstraint(fields=['quiz','ordinal'],name='maison_question_quiz_ordinal')]

    @transaction.atomic
    def save(self,*args,**kwargs):
        ids={self.quiz_id}
        old=type(self).objects.filter(pk=self.pk).values_list('quiz_id',flat=True).first()
        if old:ids.add(old)
        list(Quiz.objects.select_for_update().filter(pk__in=ids).order_by('id'))
        super().save(*args,**kwargs)
        Quiz.objects.filter(pk__in=ids).update(version=F('version')+1)

class QuestionOption(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    question=models.ForeignKey(Question,on_delete=models.PROTECT,related_name='options')
    text=models.CharField(max_length=1000)
    is_correct=models.BooleanField(default=False)
    class Meta:
        db_table='maison_question_option'
        constraints=[models.UniqueConstraint(fields=['question'],condition=Q(is_correct=True),name='maison_one_correct_option')]

    @transaction.atomic
    def save(self,*args,**kwargs):
        ids={self.question.quiz_id}
        old=type(self).objects.filter(pk=self.pk).values_list('question__quiz_id',flat=True).first()
        if old:ids.add(old)
        list(Quiz.objects.select_for_update().filter(pk__in=ids).order_by('id'))
        super().save(*args,**kwargs)
        Quiz.objects.filter(pk__in=ids).update(version=F('version')+1)

class QuizAttempt(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    quiz=models.ForeignKey(Quiz,on_delete=models.PROTECT,related_name='attempts')
    quiz_version=models.PositiveIntegerField()
    # Server-only immutable scoring snapshot; DTO never exposes it before submission.
    scoring_snapshot=models.JSONField(default=list)
    status=models.CharField(max_length=12,default='in_progress',choices=[('in_progress','in_progress'),('submitted','submitted')])
    answers=models.JSONField(default=list)
    score=models.PositiveIntegerField(null=True,blank=True)
    result=models.JSONField(null=True,blank=True)
    version=models.PositiveIntegerField(default=1)
    started_at=models.DateTimeField(auto_now_add=True)
    submitted_at=models.DateTimeField(null=True,blank=True)
    class Meta:
        db_table='maison_quiz_attempt'
        constraints=[models.CheckConstraint(condition=Q(score__isnull=True)|Q(score__lte=100),name='maison_score_range')]


class Certificate(models.Model):
    """Completion certificate for one published track; its id is the public verification code.

    Holds only the name the member typed for it. Shown at /<locale>/certificates/<id>/ to anyone
    with the link; withdrawn (deleted) by its owner, and removed when the account is deleted.
    """
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='certificates')
    track=models.ForeignKey(Track,on_delete=models.PROTECT,related_name='certificates')
    display_name=models.CharField(max_length=100)
    lessons_completed=models.PositiveIntegerField()
    issued_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='maison_certificate'
        constraints=[models.UniqueConstraint(fields=['user','track'],name='maison_certificate_user_track'),
                     models.CheckConstraint(condition=~Q(display_name=''),name='maison_certificate_named'),
                     models.CheckConstraint(condition=Q(lessons_completed__gte=1),name='maison_certificate_lessons')]


class ClassroomSession(models.Model):
    """One projection of a chapter by a pilot teacher; the pilot's usage measure. No student data."""
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    teacher=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='classroom_sessions')
    edition=models.ForeignKey('library.Edition',on_delete=models.PROTECT)
    unit=models.ForeignKey('library.Unit',on_delete=models.PROTECT)
    started_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='maison_classroom_session'
        indexes=[models.Index(fields=['teacher','started_at'],name='maison_classroom_teacher_idx')]
        permissions=[('teach_classroom','Can use classroom mode and printable worksheets')]
