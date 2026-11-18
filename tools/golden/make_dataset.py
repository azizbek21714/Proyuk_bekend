"""Build tools/golden/golden.sqlite3: an anonymised copy of db.sqlite3 plus edge-case rows.

Run on the ORM code (git tag pre-firestore):
    venv/Scripts/python.exe tools/golden/make_dataset.py
The result stays local (it is derived from real data) — see .gitignore.
"""
import os
import shutil
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))

from common import GOLDEN_DB, GOLDEN_PASSWORD  # noqa: E402

shutil.copyfile(BACKEND / 'db.sqlite3', GOLDEN_DB)
os.environ['DATABASE_URL'] = f'sqlite:///{GOLDEN_DB.as_posix()}'
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ['DEBUG'] = 'True'

import django  # noqa: E402

django.setup()

from django.contrib.auth.hashers import make_password  # noqa: E402
from django.contrib.auth.models import Group as AuthGroup, User  # noqa: E402
from django.db import connection  # noqa: E402

from apps.academics.models import Dak, DlMd, Group, Subject  # noqa: E402
from apps.departments.models import OTM, Department, Faculty  # noqa: E402
from apps.teachers.models import Teacher  # noqa: E402
from apps.workload.models import (  # noqa: E402
    AcademicYear, Approval, Assignment, DlMdBiriktirma, Reja, WorkloadNorm, WorkloadType, Yuklama,
)

PASSWORD_HASH = make_password(GOLDEN_PASSWORD, salt='goldensalt')

# ---- 1. Anonymise existing personal data ----------------------------------
with connection.cursor() as cur:
    cur.execute('DELETE FROM token_blacklist_blacklistedtoken')
    cur.execute('DELETE FROM token_blacklist_outstandingtoken')
for i, user in enumerate(User.objects.order_by('id'), start=1):
    user.username = f'golden_user_{user.id}'
    user.email = 'super@golden.test' if user.is_superuser and i == 1 else f'user{user.id}@golden.test'
    user.first_name = f'Ism{user.id}'
    user.last_name = f'Familiya{user.id}'
    user.password = PASSWORD_HASH
    user.save()
for teacher in Teacher.objects.order_by('id'):
    teacher.full_name = f"Familiya{teacher.id} Ism{teacher.id} Otasining{teacher.id}"
    teacher.email = f'teacher{teacher.id}@golden.test'
    teacher.phone_number = f'+99890000{teacher.id:04d}'
    teacher.save()

if not User.objects.filter(email='super@golden.test').exists():
    User.objects.create(username='golden_super', email='super@golden.test', password=PASSWORD_HASH,
                        is_superuser=True, is_staff=True, first_name='Super', last_name='Admin')


def make_user(email, *, groups=(), active=True, first='', last=''):
    user = User.objects.create(username='email_' + email.split('@')[0], email=email, password=PASSWORD_HASH,
                               is_active=active, first_name=first, last_name=last)
    for name in groups:
        user.groups.add(AuthGroup.objects.get_or_create(name=name)[0])
    return user


make_user('admin-group@golden.test', groups=['admin'], first='Admin', last='Guruh')
make_user('dekan@golden.test', groups=['dekan'], first='Dekan', last='Dekanov')
make_user('kafedra@golden.test', groups=['kafedra_mudiri'])
make_user('oquv@golden.test', groups=['oquv_bolimi'])
make_user('noprofile@golden.test', first='Profilsiz')
make_user('inactive@golden.test', active=False)
teacher_user = make_user('teacher@golden.test', first='Oqituvchi', last='Birinchi')
teacher2_user = make_user('teacher2@golden.test', first='Oqituvchi', last='Ikkinchi')

# ---- 2. Edge-case rows ------------------------------------------------------
dep1 = Department.objects.order_by('id').first()
otm2 = OTM.objects.create(name='Andijon Davlat Universiteti', short_name='ADU')
fac2 = Faculty.objects.create(name='Fizika-matematika', otm=otm2)
dep2 = Department.objects.create(name='Algebra kafedrasi', faculty=fac2, yillik_yuklama=1200,
                                 yuklama_data={'meta': {'title': 'Test'}, 'kuzgi': [], 'bahorgi': []})
dep3 = Department.objects.create(name='Geometriya', faculty=fac2)

# Names sort differently from ids; one teacher in two departments.
t_a = Teacher.objects.create(user=teacher_user, full_name='Yusupov Bobur', email='teacher@golden.test',
                             position='senior_teacher', rate='rate_0_5_ichki', degree='phd',
                             academic_title='docent', speciality='mathematics', phone_number='+998901112233')
t_b = Teacher.objects.create(user=teacher2_user, full_name='Aliyev Anvar', email='teacher2@golden.test',
                             position='professor', rate='rate_1_5')
t_c = Teacher.objects.create(full_name='Karimova Dilnoza', position='assistant', rate='rate_0_25')
dep2.teachers.set([t_a, t_b, t_c])
dep1.teachers.add(t_a)
dep2.head_of_department = t_b
dep2.save()
fac2.dean = t_b
fac2.save()

g1 = Group.objects.create(name='MT-21', department=dep1, course='course_3', students=25, oquv_yili='2026-2027')
g2 = Group.objects.create(name='AL-11', department=dep2, course='course_1', program_type='master',
                          study_format='part_time', study_language='ru', students=12)
dlmd = DlMd.objects.create(name='Diplom loyiha', type='seminar', students=10)
dak = Dak.objects.create(type='thesis_defense', hours=12, body='DAK izohi')
s_alg = Subject.objects.create(name='Chiziqli algebra', department=dep2, course='course_1', semester='semester_1',
                               maruza_hours=30, amaliyot_hours=30, hours=60, study_languages='uz,ru')
s_geo = Subject.objects.create(name='Geometriya asoslari', department=dep2, course='course_2', semester='semester_4',
                               maruza_hours=20, laboratoriya_hours=20, hours=40)
Yuklama.objects.create(name='Chiziqli algebra', department=dep2, subject=s_alg, group=g2, dak=dak, dl_md=dlmd,
                       groups_count=2, thread_count=1, control=6)

year = AcademicYear.objects.get(name='2026-2027')
AcademicYear.objects.create(name='2025-2026', starts_on=date(2025, 9, 1), ends_on=date(2026, 8, 31))
fan = WorkloadType.objects.get(code='FAN')
maruza = WorkloadType.objects.get(code='MARUZA')
WorkloadNorm.objects.create(workload_type=maruza, institution_profile='barcha', coefficient='1.250',
                            minimum=10, maximum=200, valid_from=date(2026, 1, 1), note='Ochiq muddat')
WorkloadNorm.objects.create(workload_type=maruza, institution_profile='tibbiyot', coefficient='0.500',
                            valid_from=date(2025, 1, 1), valid_until=date(2025, 12, 31))

plan_a = Reja.objects.create(teacher=t_a, department=dep2, oquv_yili='2026-2027', jami_soat=132, data={
    'stavka': 'rate_0_5',
    'variants': {'rate_0_5': {
        'fanlar': [{'id': f'lesson:{s_alg.id}:kuzgi:1:maruza', 'subjectId': str(s_alg.id), 'nomi': "Ma'ruza: Chiziqli algebra",
                    'soat': 30, 'semestr': 'kuzgi', 'lessonType': 'maruza'},
                   {'id': 'manual-1', 'nomi': 'Qo\'shimcha', 'soat': 12, 'semestr': 'bahorgi'}],
        'doc': {'dekan': 'D. Dekanov', 'uslubiy': [{'id': 'u1', 'nomi': 'Qo\'llanma'}], 'reyting': {'a': '1'}},
    }},
})
Assignment.objects.create(reja=plan_a, workload_type=fan, subject=s_alg, group=g2, semester_number=1,
                          hours='30.00', calculation_type='reja_taqsimoti', lesson_type='maruza',
                          formula_input={'groupIndex': 1, 'groupCount': 2})
Assignment.objects.create(reja=plan_a, workload_type=fan, subject=None, semester_number=2,
                          hours='12.50', calculation_type='reja_taqsimoti', note="Qo'shimcha")
super_user = User.objects.get(email='super@golden.test')
Approval.objects.create(reja=plan_a, stage='kafedra', state='tasdiqlangan', comment='OK', acted_by=super_user,
                        acted_at='2026-11-01T10:00:00Z')
Approval.objects.create(reja=plan_a, stage='dekan', state='rad_etilgan', acted_by=super_user,
                        acted_at='2026-11-02T10:00:00Z')
Approval.objects.create(reja=plan_a, stage='oquv_bolimi')
plan_b = Reja.objects.create(teacher=t_b, department=dep2, oquv_yili='2025-2026', status='tasdiqlangan',
                             data={'fanlar': [{'id': str(s_geo.id), 'nomi': 'Geometriya asoslari', 'soat': 40}]})
Reja.objects.create(teacher=None, department=None, oquv_yili='', jami_soat=5)

DlMdBiriktirma.objects.create(teacher=t_a, department=dep2, tur='dl', talim_shakli='kunduzgi', semestr='bahorgi',
                              talaba_soni=3, soat_birligi=28, jami_soat=84, oquv_yili='2026-2027')
DlMdBiriktirma.objects.create(teacher=t_a, department=dep2, tur='md', semestr='kuzgi',
                              talaba_soni=1, soat_birligi=50, jami_soat=50, oquv_yili='')
DlMdBiriktirma.objects.create(teacher=t_b, department=dep2, tur='dl', talaba_soni=2, soat_birligi=28,
                              jami_soat=56, oquv_yili='2025-2026')

print('golden dataset ready:', GOLDEN_DB)
print('users', User.objects.count(), 'teachers', Teacher.objects.count(), 'rejalar', Reja.objects.count(),
      'subjects', Subject.objects.count(), 'departments', Department.objects.count())
