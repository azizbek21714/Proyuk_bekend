"""O'quv bo'limi boshqaruv paneli: ruxsat, rejalar holati, dinamika, filtr, ilmiy salohiyat."""
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core.testing import StoreTestCase
from apps.departments.models import OTM, Department, Faculty
from apps.teachers.models import Teacher
from apps.workload.models import Reja

URL = '/api/dashboard/rol/oquv-bolimi/'


class OquvBolimiPanelTests(StoreTestCase):
    def setUp(self):
        self.client = APIClient()
        otm = OTM.objects.create(name='Universitet')
        self.fac_a = Faculty.objects.create(name='KIF', otm=otm)
        self.fac_b = Faculty.objects.create(name='Fizika', otm=otm)
        self.dep_a = Department.objects.create(name='Dasturlash', faculty=self.fac_a)
        self.dep_b = Department.objects.create(name='Optika', faculty=self.fac_b)
        self.admin = User.objects.create_superuser('admin', email='admin@t.test', password='x')
        self.oquv = User.objects.create_user('oquv', email='oquv@t.test', password='x', groups=['oquv_bolimi'])
        self.mudir, mudir_t = self._teacher('mudir', self.dep_a, degree='phd')
        self.dekan, dekan_t = self._teacher('dekan', self.dep_a, degree='dsc')
        self.oqit, self.oqit_t = self._teacher('oqit', self.dep_a)
        self.boshqa, self.boshqa_t = self._teacher('boshqa', self.dep_b)
        self.dep_a.head_of_department = mudir_t
        self.dep_a.save()
        self.fac_a.dean = dekan_t
        self.fac_a.save()
        self.reja_a = Reja.objects.create(teacher=self.oqit_t, department=self.dep_a, oquv_yili='2026-2027')
        self.reja_b = Reja.objects.create(teacher=self.boshqa_t, department=self.dep_b, oquv_yili='2026-2027')

    def _teacher(self, name, department, degree='bachelor'):
        user = User.objects.create_user(name, email=f'{name}@t.test', password='x')
        teacher = Teacher.objects.create(user=user, full_name=name.title(), email=user.email, degree=degree)
        department.teachers.add(teacher)
        return user, teacher

    def as_(self, user):
        self.client.force_authenticate(user)
        return self.client

    def get(self, user=None, **params):
        return self.as_(user or self.oquv).get(URL, {'oquvYili': '2026-2027', **params})

    def decide(self, user, reja):
        return self.as_(user).post(f'/api/crud/rejalar/{reja.id}/qaror/', {'qaror': 'tasdiqlash'}, format='json')

    def test_only_oquv_bolimi_and_admin(self):
        self.assertEqual(self.get().status_code, 200)
        self.assertEqual(self.get(self.admin).status_code, 200)
        for user in (self.mudir, self.dekan, self.oqit):
            self.assertEqual(self.get(user).status_code, 403)

    def test_status_flow_and_dynamics(self):
        d = self.get().data
        self.assertEqual(d['holat']['yuborilmagan'], 2)
        self.assertEqual(d['kpi']['jamiReja'], 2)
        self.assertEqual(d['haftalar'][-1]['yuborilgan'], 0)

        # O'qituvchi yuboradi -> mudirda; submit vaqti saqlanadi
        self.assertEqual(self.as_(self.oqit).post(f'/api/crud/rejalar/{self.reja_a.id}/yuborish/').status_code, 200)
        self.assertIsNotNone(Reja.objects.get(pk=self.reja_a.id).yuborilgan_at)
        self.assertEqual(self.get().data['holat']['mudirda'], 1)

        self.assertEqual(self.decide(self.mudir, self.reja_a).status_code, 200)
        self.assertEqual(self.get().data['holat']['dekanda'], 1)
        self.assertEqual(self.decide(self.dekan, self.reja_a).status_code, 200)
        d = self.get().data
        self.assertEqual((d['holat']['menda'], d['kpi']['menda']), (1, 1))

        self.assertEqual(self.decide(self.oquv, self.reja_a).status_code, 200)
        d = self.get().data
        self.assertEqual((d['holat']['tasdiqlangan'], d['holat']['yuborilmagan']), (1, 1))
        self.assertEqual((d['haftalar'][-1]['yuborilgan'], d['haftalar'][-1]['tasdiqlangan']), (1, 1))
        self.assertEqual(len(d['haftalar']), 10)
        self.assertEqual(len(d['oylar']), 10)

    def test_filter_and_breakdown(self):
        d = self.get().data
        self.assertEqual(d['kesimTuri'], 'fakultet')   # bitta OTM — fakultetlar kesimi
        self.assertEqual(sorted(k['nomi'] for k in d['kesim']), ['Fizika', 'KIF'])
        d = self.get(fakultetId=self.fac_b.id).data
        self.assertEqual((d['kesimTuri'], d['kpi']['jamiReja'], d['kpi']['oqituvchi']), ('kafedra', 1, 1))
        self.assertEqual([k['nomi'] for k in d['kesim']], ['Optika'])

    def test_research_capacity(self):
        s = self.get().data['salohiyat']
        self.assertEqual((s['dsc'], s['phd'], s['bachelor']), (1, 1, 2))
