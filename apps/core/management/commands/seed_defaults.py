"""Boshlang'ich ma'lumotlar (eski migratsiyalar o'rnida): o'quv yili, yuklama turlari,
lavozim normalari. Faqat bir marta ishlaydi: keyin `_meta/seeded` belgisi qo'yiladi,
shuning uchun har deployda chaqirilsa ham admin o'chirgan yozuvlar qayta paydo bo'lmaydi.
"""
from datetime import datetime, timezone

from django.core.management.base import BaseCommand

from apps.core.sqlite_import import SEEDED
from apps.core.store import Set, get_store

WORKLOAD_TYPES = [
    ('MARUZA', "Ma'ruza mashg'uloti", 1, 'soat', False),
    ('AMALIY', "Amaliy mashg'ulot", 2, 'soat', False),
    ('LABORATORIYA', "Laboratoriya mashg'uloti", 3, 'soat', False),
    ('SEMINAR', "Seminar mashg'uloti", 4, 'soat', False),
    ('DL', 'Diplom loyihasi rahbarligi', 5, 'talaba × koeffitsient', True),
    ('MD', 'Magistrlik dissertatsiyasi rahbarligi', 6, 'talaba × koeffitsient', True),
]


def seed():
    from apps.workload.models import AcademicYear, PositionNorm, WorkloadType
    from apps.workload.norms import POSITION_NORM_DEFAULTS
    year, _ = AcademicYear.objects.get_or_create(
        name='2026-2027',
        defaults={'starts_on': '2026-09-01', 'ends_on': '2027-08-31', 'is_active': True},
    )
    for code, name, clause, formula, hourly in WORKLOAD_TYPES:
        WorkloadType.objects.get_or_create(code=code, defaults={
            'name': name, 'clause_number': clause, 'formula_expression': formula, 'is_hourly': hourly})
    for position, (minimum, maximum) in POSITION_NORM_DEFAULTS.items():
        PositionNorm.objects.get_or_create(position=position, academic_year=year, defaults={
            'minimum_hours': minimum, 'maximum_hours': maximum})


def mark_seeded(source):
    get_store().commit([Set(*SEEDED, {'id': SEEDED[1], 'source': source,
                                      'at': datetime.now(timezone.utc)})])


class Command(BaseCommand):
    help = "Bo'sh bazaga boshlang'ich ma'lumotlarni yozadi (bir marta)"

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help="Belgi bo'lsa ham qayta ishlatish")

    def handle(self, *args, force=False, **options):
        if get_store().get(*SEEDED) is not None and not force:
            self.stdout.write("Boshlang'ich ma'lumotlar allaqachon yozilgan.")
            return
        seed()
        mark_seeded('seed_defaults')
        self.stdout.write(self.style.SUCCESS("Boshlang'ich ma'lumotlar yozildi."))
