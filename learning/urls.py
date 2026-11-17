from django.urls import path
from . import views
urlpatterns=[path('learning/tracks',views.tracks),path('learning/tracks/<uuid:track_id>',views.track),
 path('learning/tracks/<uuid:track_id>/questions',views.questions),path('learning/lessons/<uuid:lesson_id>',views.lesson),
 path('learning/lessons/<uuid:lesson_id>/complete',views.complete),path('learning/quizzes/<uuid:quiz_id>',views.quiz),
 path('learning/quizzes/<uuid:quiz_id>/attempts',views.start),path('learning/attempts/<uuid:attempt_id>',views.attempt),
 path('learning/attempts/<uuid:attempt_id>/submit',views.submit)]
