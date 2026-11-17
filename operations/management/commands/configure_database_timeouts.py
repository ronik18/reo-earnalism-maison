"""Provision database-scoped role defaults through the direct endpoint."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from psycopg import sql


class Command(BaseCommand):
    help = 'Set 5s statement, 2s lock and 10s idle-transaction limits for the current database role.'

    def handle(self, *args, **options):
        if settings.DATABASE_CONNECTION_ROLE != 'direct' or '-pooler.' in connection.settings_dict['HOST']:
            raise CommandError('Use MAISON_DATABASE_ROLE=direct and the unpooled database URL.')
        with connection.cursor() as cursor:
            cursor.execute('SELECT current_user, current_database()')
            role, database = cursor.fetchone()
            for key, value in [('statement_timeout', '5s'), ('lock_timeout', '2s'), ('idle_in_transaction_session_timeout', '10s')]:
                cursor.execute(sql.SQL('ALTER ROLE {} IN DATABASE {} SET {} TO {}').format(
                    sql.Identifier(role), sql.Identifier(database), sql.Identifier(key), sql.Literal(value)))
        self.stdout.write(self.style.SUCCESS('Database-scoped role defaults configured: statement=5s, lock=2s, idle transaction=10s. Verify on a fresh pooled connection.'))
