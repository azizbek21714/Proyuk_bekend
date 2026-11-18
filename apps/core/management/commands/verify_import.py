"""SQLite bazadagi har bir yozuvni store'dagi hujjat bilan solishtiradi."""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.sqlite_import import verify
from apps.core.store import get_store


class Command(BaseCommand):
    help = "Import to'g'riligini tekshiradi"

    def add_arguments(self, parser):
        parser.add_argument('path', nargs='?', default=str(Path(settings.BASE_DIR) / 'db.sqlite3'))

    def handle(self, *args, path, **options):
        diffs = verify(get_store(), path)
        for diff in diffs[:200]:
            self.stderr.write(f'  ! {diff}')
        if diffs:
            raise CommandError(f'{len(diffs)} ta farq topildi.')
        self.stdout.write(self.style.SUCCESS('Hamma yozuvlar mos keldi.'))
