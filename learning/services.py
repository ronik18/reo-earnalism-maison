from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from core.pagination import paginate_queryset
from django.utils import timezone
from core.api import DomainError
from library.services import authorize_revision, iso, content_locale
from .models import Track,Lesson,LessonCompletion,InterviewQuestion,Quiz,QuizAttempt,Certificate

def _territory(user):
    return getattr(user,'request_territory','IN' if settings.LOCAL else 'ZZ')


def _free_rollout_gate(user):
    if getattr(settings,'FREE_ACCESS_ENABLED',False):
        if not getattr(user,'is_authenticated',False) or not getattr(user,'is_active',False):raise DomainError('authentication_required','Sign in to continue.',401)
        if not getattr(user,'is_verified',False):raise DomainError('verification_required','Verify your account.',403)
        if _territory(user) not in settings.MAISON_PUBLICATION_TERRITORIES:raise DomainError('region_unavailable','Learning is unavailable in this territory.',403)


def _track(user,value,allow_locked=False):
    try: track=Track.objects.select_related('edition','edition__live_revision').get(pk=value,published=True)
    except (Track.DoesNotExist,ValueError,ValidationError): raise DomainError('not_found','Track not found.',404)
    if track.access=='deny': raise DomainError('access_denied','This track is not offered.',403)
    _free_rollout_gate(user)
    if track.access=='paid':
        try:
            if not track.edition or not track.edition.live_revision: raise DomainError('access_denied','Track has no access authority.',403)
            authorize_revision(user,track.edition.live_revision,territory=_territory(user))
        except DomainError:
            if not allow_locked: raise
    return track

def track_dto(user,track,included=None):
    """included: {revision_id: allowed} from one batch authorization; a single track authorizes itself."""
    access='free' if track.access=='free' else 'locked'
    if track.access=='paid':
        revision_id=track.edition.live_revision_id if track.edition_id else None
        if included is None and revision_id:
            from library.services import authorize_revisions
            included=authorize_revisions(user,[revision_id],territory=_territory(user))
        if revision_id and (included or {}).get(revision_id):access='included'
    return {'track_id':str(track.id),'title':track.title,'locale':track.locale,'kind':track.kind,'description':track.description,
            'duration_days':track.duration_days,'company_style':track.company_style or None,'access':access,
            'lesson_count':track.page_lesson_count if hasattr(track,'page_lesson_count') else track.lessons.count()}

def _track_rows(user,locale=None,kind=''):
    locale=content_locale(locale)
    if kind not in ('','learning','sde_interview'):
        raise DomainError('invalid_filter','Choose a supported track kind.',422)
    rows=Track.objects.filter(published=True).exclude(access='deny').select_related('edition').annotate(page_lesson_count=Count('lessons'))
    if locale:rows=rows.filter(locale=locale)
    if kind:rows=rows.filter(kind=kind)
    if getattr(settings,'FREE_ACCESS_ENABLED',False) and _territory(user) not in settings.MAISON_PUBLICATION_TERRITORIES:return rows.none()
    return rows


def _dtos(user,tracks):
    from library.services import authorize_revisions
    included=authorize_revisions(user,[t.edition.live_revision_id for t in tracks if t.access=='paid' and t.edition_id and t.edition.live_revision_id],territory=_territory(user))
    return [track_dto(user,t,included) for t in tracks]


def list_tracks(user,locale=None):
    return _dtos(user,list(_track_rows(user,locale).order_by('title','id')))


def tracks_page(request,user,locale=None,kind=''):
    locale=content_locale(locale)
    result=paginate_queryset(request,_track_rows(user,locale,kind),f'tracks:{locale or "all"}:{kind}',ordering='title')
    result['items']=_dtos(user,result['items'])
    return result

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
    lessons=list(track.lessons.select_related('quiz').all())
    result['lessons']=[{'lesson_id':str(l.id),'title':l.title,'ordinal':l.ordinal,'completed':completion_is_current(completed.get(l.id),l)} for l in lessons]
    result['has_quiz']=any(hasattr(l,'quiz') for l in lessons)
    existing=Certificate.objects.filter(user=user,track=track).first() if getattr(user,'is_authenticated',False) else None
    result['certificate']={'certificate_id':str(existing.id) if existing else None,
                           'eligible':bool(result['lessons']) and all(l['completed'] for l in result['lessons'])
                                      and result['access']!='locked' and not getattr(user,'guardian_managed',False)}
    return result


def _certificate_name(value):
    name=' '.join(str(value or '').split())
    if not 1<=len(name)<=100 or any(ord(c)<32 or 0x7f<=ord(c)<0xa0 for c in name):
        raise DomainError('validation_error','Enter the name to show on the certificate (up to 100 characters).',422)
    return name


@transaction.atomic
def issue_certificate(user,track_id,display_name):
    """One certificate per member and track, only after every current lesson is complete."""
    track=_track(user,track_id)
    if not getattr(user,'is_authenticated',False):raise DomainError('authentication_required','Sign in to continue.',401)
    if getattr(user,'guardian_managed',False):
        raise DomainError('certificate_unavailable','Certificates are not offered for accounts managed by a parent or guardian.',403)
    name=_certificate_name(display_name)
    from django.contrib.auth import get_user_model
    get_user_model().objects.select_for_update().get(pk=user.pk)
    existing=Certificate.objects.filter(user=user,track=track).first()
    if existing:return existing
    lessons=list(track.lessons.select_related('quiz').all())
    done={row.lesson_id:row for row in LessonCompletion.objects.filter(user=user,lesson__track=track)}
    if not lessons or not all(completion_is_current(done.get(l.id),l) for l in lessons):
        raise DomainError('completion_rule_unmet','Finish every lesson in this track first.',409)
    return Certificate.objects.create(user=user,track=track,display_name=name,lessons_completed=len(lessons))


def withdraw_certificate(user,certificate_id):
    deleted,_=Certificate.objects.filter(pk=certificate_id,user=user).delete() if getattr(user,'is_authenticated',False) else (0,None)
    if not deleted:raise DomainError('not_found','Certificate not found.',404)


def certificate_public(certificate_id):
    """Public verification view: the chosen name, the track and the date; nothing else."""
    try:cert=Certificate.objects.select_related('track').get(pk=certificate_id,user__is_active=True)
    except (Certificate.DoesNotExist,ValueError,ValidationError):raise DomainError('not_found','Certificate not found.',404)
    return {'certificate_id':str(cert.id),'display_name':cert.display_name,'track_id':str(cert.track_id),
            'track_title':cert.track.title,'track_locale':cert.track.locale,'lessons_completed':cert.lessons_completed,
            'issued_at':cert.issued_at,'owner_id':cert.user_id}

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
        authorize_revision(user,lesson.unit.revision,territory=_territory(user))
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

def _question_rows(user,track_id,topic='',difficulty='',company_style=''):
    track=_track(user,track_id)
    if (not isinstance(topic,str) or len(topic)>120 or not isinstance(company_style,str) or len(company_style)>120
        or difficulty not in ('','foundation','intermediate','advanced')):
        raise DomainError('invalid_filter','Choose bounded supported interview filters.',422)
    qs=track.interview_questions.all()
    if topic: qs=qs.filter(topic=topic)
    if difficulty: qs=qs.filter(difficulty=difficulty)
    if company_style: qs=qs.filter(company_style=company_style)
    return qs


def _question_dto(q):
    return {'question_id':str(q.id),'track_id':str(q.track_id),'topic':q.topic,'difficulty':q.difficulty,
            'company_style':q.company_style or None,'prompt':q.prompt,'model_answer':q.model_answer,'rubric':q.rubric}


def interview_questions(user,track_id,topic='',difficulty='',company_style=''):
    return [_question_dto(q) for q in _question_rows(user,track_id,topic,difficulty,company_style).order_by('id')]


def interview_question(user,track_id,question_id):
    rows=_question_rows(user,track_id)
    try:question=rows.filter(pk=question_id).first()
    except (ValueError,ValidationError):question=None
    if not question:raise DomainError('not_found','Question not found in this track.',404)
    return _question_dto(question)


def interview_questions_page(request,user,track_id,topic='',difficulty='',company_style=''):
    result=paginate_queryset(request,_question_rows(user,track_id,topic,difficulty,company_style),f'interview:{track_id}',ordering='id')
    result['items']=[_question_dto(row) for row in result['items']]
    return result

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
