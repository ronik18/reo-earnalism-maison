from django.urls import path
from . import views,download_views
urlpatterns=[path('me/progress',views.list_progress),path('me/progress/<uuid:edition_id>/<str:format>',views.progress),
 path('me/completion/<uuid:edition_id>/<str:format>',views.completion),path('me/sync',views.sync),
 path('me/annotations',views.annotations),path('me/annotations/<uuid:annotation_id>',views.annotation),
 path('me/saved-items',views.saved_items),path('me/saved-items/<uuid:edition_id>',views.saved_item),
 path('me/lists',views.lists),path('me/lists/<uuid:list_id>',views.personal_list),path('me/lists/<uuid:list_id>/items/<uuid:edition_id>',views.list_edition),path('me/lists/<uuid:list_id>/order',views.list_order),path('me/vault',views.vault)]

urlpatterns += [path("me/downloads",download_views.downloads),path("me/downloads/<uuid:license_id>",download_views.download),path("me/downloads/<uuid:license_id>/refresh",download_views.refresh),path("me/downloads/<uuid:license_id>/renew",download_views.renew)]

urlpatterns += [path("me/downloads/<uuid:license_id>/pieces/<uuid:asset_id>",download_views.pieces)]
