"""Teacher-only classroom licence (revenue plan Phase 4): projection mode, usage and worksheets.

Teachers are granted by staff (``manage.py classroom_teacher grant``); there are no student
accounts and no student data. Access to the text is the normal reader authorization, so the
licence never widens rights, territory or publication.
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.db.models.functions import TruncWeek
from django.utils import timezone

from core.api import DomainError
from .models import ClassroomSession

PERMISSION = 'learning.teach_classroom'
REPEAT_WINDOW = timedelta(minutes=30)


def is_teacher(user):
    return bool(getattr(user, 'is_authenticated', False) and user.is_active and getattr(user, 'is_verified', False)
                and not getattr(user, 'guardian_managed', False) and user.has_perm(PERMISSION))


def require_teacher(user):
    if not getattr(user, 'is_authenticated', False):
        raise DomainError('authentication_required', 'Sign in to continue.', 401)
    if not is_teacher(user):
        raise DomainError('classroom_licence_required', 'Classroom mode is for teachers in the Earnalism classroom pilot.', 403)


def open_classroom(user, edition_id, unit_id, territory):
    """Authorize exactly like the reader, then count one session (refreshes within 30 minutes count once)."""
    require_teacher(user)
    from library.services import get_reader_document
    document = get_reader_document(user, edition_id, unit_id, territory=territory)
    if not document['edition'].get('published_at'):
        # Staff reviewers can read drafts; classroom projection is for published editions only.
        raise DomainError('content_unavailable', 'This edition is not published.', 404)
    with transaction.atomic():
        recent = ClassroomSession.objects.select_for_update().filter(
            teacher=user, edition_id=edition_id, unit_id=unit_id, started_at__gte=timezone.now() - REPEAT_WINDOW).exists()
        if not recent:
            ClassroomSession.objects.create(teacher=user, edition_id=edition_id, unit_id=unit_id)
    return document


def weekly_sessions(since, until):
    """Sessions per teacher per week, for the pilot report (staff-only)."""
    rows = (ClassroomSession.objects.filter(started_at__gte=since, started_at__lt=until)
            .annotate(week=TruncWeek('started_at')).values('week', 'teacher__email')
            .annotate(sessions=Count('id'), titles=Count('edition', distinct=True)).order_by('week', 'teacher__email'))
    return [{'week': r['week'].date().isoformat(), 'teacher': r['teacher__email'], 'sessions': r['sessions'],
             'titles': r['titles']} for r in rows]
