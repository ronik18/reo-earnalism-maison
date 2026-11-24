"""Grant, revoke or list the classroom-pilot teacher role (revenue plan Step 4.1).

  python manage.py classroom_teacher grant <email> --by <staff email> --reason "<pilot agreement ref>"
  python manage.py classroom_teacher revoke <email> --by <staff email> --reason "<why>"
  python manage.py classroom_teacher list

The role is the 'Classroom teachers' group holding learning.teach_classroom. Every change is audited.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.services import audit

GROUP = 'Classroom teachers'


def teacher_group():
    group, _ = Group.objects.get_or_create(name=GROUP)
    group.permissions.add(Permission.objects.get(codename='teach_classroom', content_type__app_label='learning'))
    return group


class Command(BaseCommand):
    help = 'Grant, revoke or list classroom-pilot teachers (audited).'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['grant', 'revoke', 'list'])
        parser.add_argument('email', nargs='?')
        parser.add_argument('--by')
        parser.add_argument('--reason')

    def handle(self, *args, action, email, by, reason, **options):
        User = get_user_model()
        if action == 'list':
            for user in teacher_group().user_set.order_by('email'):
                self.stdout.write(f'{user.email}\t{"verified" if user.is_verified else "UNVERIFIED"}')
            return
        if not email or not by or not (reason or '').strip():
            raise CommandError('grant/revoke need <email>, --by <staff email> and --reason')
        staff = User.objects.filter(email=by.strip().casefold(), is_staff=True, is_active=True).first()
        if not staff:
            raise CommandError('--by must be an active staff account')
        user = User.objects.filter(email=email.strip().casefold(), is_active=True).first()
        if not user:
            raise CommandError('No active account with that email')
        if action == 'grant' and (not user.is_verified or user.guardian_managed):
            raise CommandError('Teachers must be verified adult accounts, not parent-managed ones')
        with transaction.atomic():
            group = teacher_group()
            (group.user_set.add if action == 'grant' else group.user_set.remove)(user)
            audit(staff, f'classroom.teacher_{action}', user, {'reason': reason.strip()[:500]})
        self.stdout.write(f"{'Granted' if action == 'grant' else 'Revoked'} the classroom teacher role for {user.email}")
