"""Keep packaged staff-admin assets inside the isolated public namespace."""
from django.conf import settings
from django.contrib.staticfiles.storage import StaticFilesStorage


class MaisonStaticFilesStorage(StaticFilesStorage):
    def url(self, name):
        if not settings.LOCAL and name.startswith('admin/'):
            name = 'maison/framework/' + name
        return super().url(name)
