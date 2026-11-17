from core.api import json_endpoint,api_response,operation_key,expected_version
from core.services import apply_operation,audit
from library.views import context,page
from library.validation import body
from . import services as svc

@json_endpoint(auth=False)
def tracks(request):
    locale,_=context(request)
    return api_response(page(request,svc.list_tracks(request.user,locale),'tracks'))

@json_endpoint()
def track(request,track_id):
    return api_response(svc.track_detail(request.user,track_id))

@json_endpoint()
def lesson(request,lesson_id):
    data=svc.lesson_detail(request.user,lesson_id)
    return api_response(data,version=data['version'])

@json_endpoint(methods=('POST',))
def complete(request,lesson_id):
    key=operation_key(request)
    def execute():
        data=svc.complete_lesson(request.user,lesson_id)
        return 200,data,data['version']
    status,data=apply_operation(request.user,key,'lesson.complete',{'lesson_id':str(lesson_id)},execute)
    return api_response(data,status,version=data['version'])

@json_endpoint()
def questions(request,track_id):
    data=svc.interview_questions(request.user,track_id,**{k:request.GET.get(k,'') for k in ('topic','difficulty','company_style')})
    return api_response(page(request,data,'interview:'+str(track_id)))

@json_endpoint()
def quiz(request,quiz_id):
    data=svc.quiz_public(request.user,quiz_id)
    return api_response(data,version=data['version'])

@json_endpoint(methods=('POST',))
def start(request,quiz_id):
    data=body(request,'QuizAttemptInput');key=operation_key(request)
    def execute():
        attempt=svc.start_attempt(request.user,quiz_id,data['quiz_version'])
        return 201,svc.attempt_dto(attempt),attempt.version
    status,result=apply_operation(request.user,key,'quiz.start',{**data,'quiz_id':str(quiz_id)},execute)
    return api_response(result,status,version=result['version'])

@json_endpoint()
def attempt(request,attempt_id):
    result=svc.attempt_dto(svc.own_attempt(request.user,attempt_id))
    return api_response(result,version=result['version'])

@json_endpoint(methods=('POST',))
def submit(request,attempt_id):
    data=body(request,'QuizSubmission');key=operation_key(request);version=expected_version(request)
    def execute():
        attempt=svc.submit_attempt(request.user,attempt_id,data['answers'],version)
        audit(request.user,'quiz.submit',attempt,{'score':attempt.score})
        return 200,svc.attempt_dto(attempt),attempt.version
    status,result=apply_operation(request.user,key,'quiz.submit',{**data,'attempt_id':str(attempt_id),'expected_version':version},execute)
    return api_response(result,status,version=result['version'])
