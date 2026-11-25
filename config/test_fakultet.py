"""Rahbarlar uchun fakultet kafedralari va guruhlari: hudud cheklovi, sardor/murabbiy/yo'nalish belgilash."""
from rest_framework.test import APIClient

from apps.academics.models import Group, Talaba
from apps.accounts.models import User
from apps.core.testing import StoreTestCase
from apps.departments.models import OTM, Department, Faculty
from apps.teachers.models import Teacher

KAF = '/api/dashboard/rol/kafedralar/'
GUR = '/api/dashboard/rol/guruhlar/'


class FakultetTests(StoreTestCase):
    def setUp(self):
        otm = OTM.objects.create(name='Universitet')
        self.fac = Faculty.objects.create(name='KIF', otm=otm)
        other_fac = Faculty.objects.create(name='Iqtisod', otm=otm)
        self.dep1 = Department.objects.create(name='Dasturlash', faculty=self.fac)
        self.dep2 = Department.objects.create(name='Tarmoqlar', faculty=self.fac)
        self.dep3 = Department.objects.create(name='Moliya', faculty=other_fac)
        self.g1 = Group.objects.create(name='DI-21', department=self.dep1)
        self.g2 = Group.objects.create(name='TT-21', department=self.dep2)
        self.g3 = Group.objects.create(name='MO-21', department=self.dep3)
        self.t1 = Talaba.objects.create(group=self.g1, fio='Aliyev Anvar', telefon='+998901112233')
        self.t3 = Talaba.objects.create(group=self.g3, fio='Begona Talaba')

        def make(name, email, dep=None):
            user = User.objects.create_user(email.split('@')[0], email=email, password='x')
            teacher = Teacher.objects.create(user=user, full_name=name, email=email, phone_number='+998900000000')
            if dep:
                dep.teachers.add(teacher)
            return user, teacher

        self.dekan_user, dekan = make('Dekanov Dilshod', 'dekan@t.test')
        self.fac.dean = dekan
        self.fac.save()
        self.mudir_user, self.mudir = make('Mudirov Murod', 'mudir@t.test', self.dep1)
        self.dep1.head_of_department = self.mudir
        self.dep1.save()
        self.oqit_user, self.oqit = make('Oqituvchi Olim', 'oqit@t.test', self.dep2)
        _, self.begona = make('Begona Oqituvchi', 'begona@t.test', self.dep3)

    def as_(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_dean_sees_faculty_departments_with_heads(self):
        rows = self.as_(self.dekan_user).get(KAF).data
        self.assertEqual([r['nomi'] for r in rows], ['Dasturlash', 'Tarmoqlar'])
        self.assertEqual(rows[0]['mudir']['fio'], 'Mudirov Murod')
        self.assertIsNone(rows[1]['mudir'])
        self.assertEqual((rows[0]['guruhlarSoni'], rows[0]['oqituvchilarSoni']), (1, 1))
        self.assertEqual(self.as_(self.oqit_user).get(KAF).status_code, 403)

    def test_dean_sets_leader_tutor_and_direction(self):
        client = self.as_(self.dekan_user)
        self.assertEqual({r['nomi'] for r in client.get(GUR).data}, {'DI-21', 'TT-21'})
        res = client.patch(f'{GUR}{self.g1.id}/', {'yonalish': '60610500 – Kompyuter injiniringi',
                                                   'sardorId': self.t1.id, 'murabbiyId': self.oqit.id}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['sardor'], {'id': self.t1.id, 'fio': 'Aliyev Anvar', 'telefon': '+998901112233'})
        self.assertEqual(res.data['murabbiy']['fio'], 'Oqituvchi Olim')
        self.assertEqual(res.data['yonalish'], '60610500 – Kompyuter injiniringi')
        row = next(r for r in client.get(GUR).data if r['id'] == self.g1.id)
        self.assertEqual((row['sardor']['id'], row['talabaSoni']), (self.t1.id, 1))
        cleared = client.patch(f'{GUR}{self.g1.id}/', {'sardorId': None}, format='json')
        self.assertIsNone(cleared.data['sardor'])

    def test_validation_and_scope(self):
        dekan = self.as_(self.dekan_user)
        bad = dekan.patch(f'{GUR}{self.g1.id}/', {'sardorId': self.t3.id, 'murabbiyId': self.begona.id}, format='json')
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(set(bad.data), {'sardorId', 'murabbiyId'})
        self.assertEqual(dekan.patch(f'{GUR}{self.g3.id}/', {'yonalish': 'X'}, format='json').status_code, 403)
        mudir = self.as_(self.mudir_user)
        self.assertEqual(mudir.patch(f'{GUR}{self.g1.id}/', {'yonalish': 'Y'}, format='json').status_code, 200)
        self.assertEqual(mudir.patch(f'{GUR}{self.g2.id}/', {'yonalish': 'Y'}, format='json').status_code, 403)
        self.assertEqual(self.as_(self.oqit_user).patch(f'{GUR}{self.g2.id}/', {'yonalish': 'Y'}, format='json').status_code, 403)
