from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from core.api import DomainError
from library.services import authorize_revision, iso
from .models import Track,Lesson,LessonCompletion,InterviewQuestion,Quiz,QuizAttempt

def _track(user,value,allow_locked=False):
    try: track=Track.objects.select_related('edition','edition__live_revision').get(pk=value,published=True)
    except (Track.DoesNotExist,ValueError,ValidationError): raise DomainError('not_found','Track not found.',404)
    if track.access=='deny': raise DomainError('access_denied','This track is not offered.',403)
    if getattr(settings,'FREE_ACCESS_ENABLED',False):
        if not getattr(user,'is_authenticated',False) or not getattr(user,'is_active',False):raise DomainError('authentication_required','Sign in to continue.',401)
        if not getattr(user,'is_verified',False):raise DomainError('verification_required','Verify your account.',403)
        if getattr(user,'request_territory','IN' if settings.LOCAL else 'ZZ') not in settings.MAISON_PUBLICATION_TERRITORIES:raise DomainError('region_unavailable','Learning is unavailable in this territory.',403)
    if track.access=='paid':
        try:
            if not track.edition or not track.edition.live_revision: raise DomainError('access_denied','Track has no access authority.',403)
            authorize_revision(user,track.edition.live_revision,territory=getattr(user,'request_territory','IN' if settings.LOCAL else 'ZZ'))
        except DomainError:
            if not allow_locked: raise
    return track

def track_dto(user,track):
    access='free' if track.access=='free' else 'locked'
    if track.access=='paid':
        try: _track(user,track.id);access='included'
        except DomainError: pass
    return {'track_id':str(track.id),'title':track.title,'locale':track.locale,'kind':track.kind,'description':track.description,
            'duration_days':track.duration_days,'company_style':track.company_style or None,'access':access,'lesson_count':track.lessons.count()}

def list_tracks(user,locale='en'):
    if getattr(settings,'FREE_ACCESS_ENABLED',False) and getattr(user,'request_territory','IN' if settings.LOCAL else 'ZZ') not in settings.MAISON_PUBLICATION_TERRITORIES:return []
    return [track_dto(user,t) for t in Track.objects.filter(published=True,locale=locale).exclude(access='deny').order_by('title','id')]

def completion_is_current(record,lesson):
    if not record or record.lesson_version!=lesson.version:return False
    if lesson.completion_rule=='quiz_pass':
        return hasattr(lesson,'quiz') and record.quiz_version==lesson.quiz.version
    return record.quiz_version is None


def lesson_is_complete(user,lesson):
    if not getattr(user,'is_authenticated',False):return False
    record=LessonCompletion.objects.filter(user=user,lesson=lesson).first()
    return completion_is_current(record,lesson)


def track_detail(user,track_id):
    track=_track(user,track_id,allow_locked=True)
    result=track_dto(user,track)
    completed={row.lesson_id:row for row in LessonCompletion.objects.filter(user=user,lesson__track=track)} if getattr(user,'is_authenticated',False) else {}
    result['lessons']=[{'lesson_id':str(l.id),'title':l.title,'ordinal':l.ordinal,'completed':completion_is_current(completed.get(l.id),l)} for l in track.lessons.select_related('quiz').all()]
    return result

def _lesson(user,value):
    try: lesson=Lesson.objects.select_related('track','track__edition').get(pk=value)
    except (Lesson.DoesNotExist,ValueError,ValidationError): raise DomainError('not_found','Lesson not found.',404)
    _track(user,lesson.track_id)
    if lesson.requires_previous:
        previous=lesson.track.lessons.filter(ordinal__lt=lesson.ordinal).order_by('-ordinal').first()
        if previous and (not lesson_is_complete(user,previous)):
            raise DomainError('prerequisite_unmet','Complete the previous lesson first.',409)
    if lesson.unit_id:
        if lesson.track.edition_id and lesson.unit.revision.edition_id!=lesson.track.edition_id:
            raise DomainError('lesson_not_ready','Lesson media belongs to another edition.',409)
        authorize_revision(user,lesson.unit.revision,territory=getattr(user,'request_territory','IN' if settings.LOCAL else 'ZZ'))
    return lesson

def lesson_detail(user,lesson_id):
    lesson=_lesson(user,lesson_id)
    return {'lesson_id':str(lesson.id),'track_id':str(lesson.track_id),'title':lesson.title,'locale':lesson.track.locale,
            'edition_id':str(lesson.unit.revision.edition_id) if lesson.unit_id else (str(lesson.track.edition_id) if lesson.track.edition_id else None),'unit_id':str(lesson.unit_id) if lesson.unit_id else None,
            'body':lesson.body,'quiz_id':str(lesson.quiz.id) if hasattr(lesson,'quiz') else None,
            'completed':lesson_is_complete(user,lesson),'version':lesson.version}

@transaction.atomic
def complete_lesson(user,lesson_id):
    lesson=_lesson(user,lesson_id)
    if lesson.completion_rule=='quiz_pass':
        if not hasattr(lesson,'quiz') or not QuizAttempt.objects.filter(user=user,quiz=lesson.quiz,quiz_version=lesson.quiz.version,status='submitted',score__gte=lesson.pass_score).exists():
            raise DomainError('completion_rule_unmet','Pass the current lesson quiz before completing it.',409)
    quiz_version=lesson.quiz.version if lesson.completion_rule=='quiz_pass' else None
    record,_=LessonCompletion.objects.get_or_create(user=user,lesson=lesson,defaults={'lesson_version':lesson.version,'quiz_version':quiz_version})
    if not completion_is_current(record,lesson):
        record.lesson_version=lesson.version;record.quiz_version=quiz_version;record.completed_at=timezone.now()
        record.save(update_fields=['lesson_version','quiz_version','completed_at'])
    return {'lesson_id':str(lesson.id),'completed':True,'completed_at':iso(record.completed_at),'version':lesson.version}

def interview_questions(user,track_id,topic='',difficulty='',company_style=''):
    track=_track(user,track_id)
    qs=track.interview_questions.all()
    if topic: qs=qs.filter(topic=topic)
    if difficulty: qs=qs.filter(difficulty=difficulty)
    if company_style: qs=qs.filter(company_style=company_style)
    return [{'question_id':str(q.id),'track_id':str(track.id),'topic':q.topic,'difficulty':q.difficulty,
             'company_style':q.company_style or None,'prompt':q.prompt,'model_answer':q.model_answer,'rubric':q.rubric} for q in qs.order_by('id')]

def quiz_public(user,quiz_id):
    try: quiz=Quiz.objects.select_related('lesson').get(pk=quiz_id)
    except (Quiz.DoesNotExist,ValueError,ValidationError): raise DomainError('not_found','Quiz not found.',404)
    _lesson(user,quiz.lesson_id)
    # Explicit allowlist; neither correct option nor explanation/scoring snapshot enters this DTO.
    return {'quiz_id':str(quiz.id),'lesson_id':str(quiz.lesson_id),'version':quiz.version,'max_attempts':quiz.max_attempts,
            'questions':[{'question_id':str(q.id),'prompt':q.prompt,'kind':'single_choice',
                          'options':[{'option_id':str(o.id),'text':o.text} for o in q.options.order_by('id')]} for q in quiz.questions.all()]}

def attempt_dto(attempt):
    return {'attempt_id':str(attempt.id),'quiz_id':str(attempt.quiz_id),'quiz_version':attempt.quiz_version,'status':attempt.status,
            'started_at':iso(attempt.started_at),'submitted_at':iso(attempt.submitted_at),'score':attempt.score if attempt.status=='submitted' else None,
            'result':attempt.result if attempt.status=='submitted' else None,'version':attempt.version}

@transaction.atomic
def start_attempt(user,quiz_id,quiz_version):
    try: quiz=Quiz.objects.select_for_update().select_related('lesson').get(pk=quiz_id)
    except (Quiz.DoesNotExist,ValueError,ValidationError): raise DomainError('not_found','Quiz not found.',404)
    _lesson(user,quiz.lesson_id)
    if quiz.version!=quiz_version: raise DomainError('version_conflict','Quiz changed. Reload the questions.',412,{'current_version':quiz.version})
    if quiz.max_attempts and quiz.attempts.filter(user=user,quiz_version=quiz.version).count()>=quiz.max_attempts:
        raise DomainError('attempt_limit','Maximum attempts reached.',409)
    snapshot=[]
    for q in quiz.questions.all():
        options=list(q.options.all());correct=[o for o in options if o.is_correct]
        if len(correct)!=1: raise DomainError('quiz_not_ready','Quiz has no unambiguous answer key.',409)
        snapshot.append({'question_id':str(q.id),'option_ids':[str(o.id) for o in options],
                         'correct_option_id':str(correct[0].id),'explanation':q.explanation})
    if not snapshot: raise DomainError('quiz_not_ready','Quiz has no questions.',409)
    return QuizAttempt.objects.create(user=user,quiz=quiz,quiz_version=quiz.version,scoring_snapshot=snapshot)

def own_attempt(user,attempt_id,lock=False):
    qs=QuizAttempt.objects.select_for_update() if lock else QuizAttempt.objects
    try: attempt=qs.select_related('quiz','quiz__lesson').get(pk=attempt_id,user=user)
    except (QuizAttempt.DoesNotExist,ValueError,ValidationError): raise DomainError('not_found','Attempt not found.',404)
    _lesson(user,attempt.quiz.lesson_id)
    return attempt

@transaction.atomic
def submit_attempt(user,attempt_id,answers,expected_version):
    attempt=own_attempt(user,attempt_id,lock=True)
    if attempt.version!=expected_version: raise DomainError('version_conflict','Attempt changed. Reload its state.',412,{'current_version':attempt.version})
    if attempt.status!='in_progress': raise DomainError('invalid_transition','Attempt has already been submitted.',409)
    if not isinstance(answers,list) or len(answers)!=len(attempt.scoring_snapshot): raise DomainError('invalid_answers','Answer every question exactly once.',400)
    try: mapping={a['question_id']:a['option_id'] for a in answers}
    except (KeyError,TypeError): raise DomainError('invalid_answers','Each answer requires question_id and option_id.',400)
    if len(mapping)!=len(answers) or set(mapping)!={q['question_id'] for q in attempt.scoring_snapshot}: raise DomainError('invalid_answers','Questions do not match this attempt.',400)
    result=[]
    for q in attempt.scoring_snapshot:
        chosen=mapping[q['question_id']]
        if chosen not in q['option_ids']: raise DomainError('invalid_answers','Option does not belong to its question.',400)
        result.append({'question_id':q['question_id'],'selected_option_id':chosen,'correct_option_id':q['correct_option_id'],
                       'correct':chosen==q['correct_option_id'],'explanation':q['explanation']})
    attempt.answers=answers;attempt.result=result;attempt.score=round(100*sum(r['correct'] for r in result)/len(result))
    attempt.status='submitted';attempt.submitted_at=timezone.now();attempt.version+=1;attempt.save()
    return attempt
