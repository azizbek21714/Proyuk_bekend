"""Eski SQLite bazani (db.sqlite3) joriy store'ga (Firestore / JSON fayl) ko'chiradi, id'lar saqlanadi."""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.sqlite_import import plan_import, run_import
from apps.core.store import get_store


class Command(BaseCommand):
    help = "db.sqlite3 dagi ma'lumotlarni store'ga ko'chiradi"

    def add_arguments(self, parser):
        parser.add_argument('path', nargs='?', default=str(Path(settings.BASE_DIR) / 'db.sqlite3'))
        parser.add_argument('--dry-run', action='store_true', help='Faqat tekshirish, yozmaslik')
        parser.add_argument('--wipe', action='store_true', help="Avval store'dagi hamma narsani o'chirish")

    def handle(self, *args, path, dry_run=False, wipe=False, **options):
        if not Path(path).exists():
            raise CommandError(f'Fayl topilmadi: {path}')
        per_model, markers, blacklist, problems = plan_import(path)
        for model, docs, counter in per_model:
            self.stdout.write(f'  {model._meta.collection:28} {len(docs):6} ta  (oxirgi id {counter})')
        self.stdout.write(f'  {"_unique":28} {len(markers):6} ta')
        self.stdout.write(f'  {"token_blacklist":28} {len(blacklist):6} ta')
        if problems:
            for problem in problems:
                self.stderr.write(f'  ! {problem}')
            raise CommandError("Muammolar bor, import qilinmadi.")
        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry-run: muammo yo'q."))
            return
        store = get_store()
        if wipe:
            store.drop_all()
        elif any(store.query(m._meta.collection) for m, _, _ in per_model):
            raise CommandError("Store bo'sh emas. Qayta yozish uchun --wipe bering.")
        problems, counts = run_import(store, path)
        if problems:
            raise CommandError('; '.join(problems))
        self.stdout.write(self.style.SUCCESS(f'Import tugadi: {sum(counts.values())} ta hujjat.'))
