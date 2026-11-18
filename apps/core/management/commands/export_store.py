"""Store'dagi barcha hujjatlarni JSON faylga zaxira qiladi."""
import json
from datetime import date, datetime

from django.core.management.base import BaseCommand

from apps.core.store import get_store


def _default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


class Command(BaseCommand):
    help = "Store'ni JSON faylga eksport qiladi"

    def add_arguments(self, parser):
        parser.add_argument('output')

    def handle(self, *args, output, **options):
        store = get_store()
        data = {coll: store.query(coll) for coll in store.collections()}
        with open(output, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1, default=_default)
        self.stdout.write(self.style.SUCCESS(f'{sum(map(len, data.values()))} ta hujjat -> {output}'))
