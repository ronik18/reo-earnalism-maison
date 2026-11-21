from django.urls import path
from . import views, intake_api, production_handoff_api, general_import_api
urlpatterns=[
    path("staff/draft-editions/<uuid:edition_id>",intake_api.draft_edition),
    path("staff/draft-covers/<uuid:asset_id>",intake_api.draft_cover),
    path("staff/books/imports",intake_api.intake),
    path("staff/drafts/<uuid:revision_id>/document",intake_api.draft_document),
    path('home',views.home),path('catalog',views.catalog),path('search',views.catalog),
    path('catalog/collections',views.collections),path('catalog/collections/<uuid:collection_id>',views.collection),
    path('catalog/works/<uuid:work_id>',views.work),path('catalog/editions/<uuid:edition_id>',views.edition),
    path('catalog/editions/<uuid:edition_id>/units',views.units),path('content/audio-previews/<uuid:asset_id>',views.audio_preview),path('content/previews/<uuid:revision_id>',views.preview),
    path('content/covers/<uuid:asset_id>',views.cover),path('content/manifests/<uuid:revision_id>',views.manifest),
    path('content/packages/grants',views.packages),path('media/grants',views.media),
    path('content/local-assets/<uuid:asset_id>',views.local_asset),path('content/mappings/<uuid:revision_id>',views.mappings),
    path('content/switch-position',views.switch),path('staff/editions/<uuid:edition_id>/review',views.staff_review),
    path('staff/editions/<uuid:edition_id>/production-handoffs',production_handoff_api.production_handoffs),
    path('staff/editions/<uuid:edition_id>/source-imports',general_import_api.finalize),
    path('staff/editions/<uuid:edition_id>/<str:action>',views.staff_action),path('staff/assets/uploads',views.upload),
    path('staff/assets/<uuid:asset_id>',views.staff_asset),path('staff/assets/<uuid:asset_id>/local-upload',views.local_upload),
    path('staff/assets/<uuid:asset_id>/complete',views.complete_upload),
]
