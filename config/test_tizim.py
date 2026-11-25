"""Admin boshqaruv paneli: tizim holati (tuzilma, rollar, muammolar, filtr, ruxsat)."""
from rest_framework.test import APIClient

from apps.academics.models import Group, Talaba
from apps.accounts.models import User
from apps.core.testing import StoreTestCase
from apps.departments.models import OTM, Department, Faculty
from apps.teachers.models import Teacher

URL = '/api/dashboard/rol/tizim/'


class TizimHolatiTests(StoreTestCase):
    def setUp(self):
        otm = OTM.objects.create(name='Universitet')
        self.fac1 = Faculty.objects.create(name='KIF', otm=otm)
        self.fac2 = Faculty.objects.create(name='Iqtisod', otm=otm)
        self.dep1 = Department.objects.create(name='Dasturlash', faculty=self.fac1, yillik_yuklama=100)
        self.dep2 = Department.objects.create(name='Moliya', faculty=self.fac2)
        user = User.objects.create_user('mudir', email='mudir@t.test', password='x')
        self.head = Teacher.objects.create(user=user, full_name='Mudirov Murod', email=user.email)
        self.dep1.teachers.add(self.head)
        self.dep1.head_of_department = self.head
        self.dep1.save()
        self.hisobsiz = Teacher.objects.create(full_name='Hisobsiz Hamid', email='h@t.test')
        self.dep1.teachers.add(self.hisobsiz)
        g = Group.objects.create(name='DI-21', department=self.dep1)
        Talaba.objects.create(group=g, fio='Aliyev Anvar')
        Group.objects.create(name='MO-21', department=self.dep2)
        self.admin = User.objects.create_superuser('admin', email='admin@t.test', password='x')

    def get(self, user, **params):
        client = APIClient()
        client.force_authenticate(user)
        return client.get(URL, params)

    def test_admin_only(self):
        self.assertEqual(self.get(User.objects.get(email='mudir@t.test')).status_code, 403)

    def test_overview_and_problems(self):
        d = self.get(self.admin).data
        self.assertEqual((d['tuzilma']['fakultet'], d['tuzilma']['kafedra'], d['tuzilma']['guruh'], d['tuzilma']['talaba']),
                         (2, 2, 2, 1))
        self.assertEqual(d['rollar']['kafedra_mudiri'], 1)
        self.assertEqual(d['rollar']['admin'], 1)
        problems = {p['key']: p for p in d['muammolar']}
        self.assertEqual(problems['dekansiz_fakultet']['soni'], 2)
        self.assertEqual([i['nomi'] for i in problems['mudirsiz_kafedra']['items']], ['Moliya'])
        self.assertEqual(problems['hisobsiz_xodim']['items'][0]['nomi'], 'Hisobsiz Hamid')
        self.assertEqual([i['nomi'] for i in problems['yuklamasiz_kafedra']['items']], ['Moliya'])
        self.assertEqual([i['nomi'] for i in problems['oqituvchisiz_kafedra']['items']], ['Moliya'])
        self.assertEqual([i['nomi'] for i in problems['talabasiz_guruh']['items']], ['MO-21'])

    def test_filter_by_faculty(self):
        d = self.get(self.admin, fakultetId=self.fac1.id).data
        self.assertEqual((d['tuzilma']['fakultet'], d['tuzilma']['kafedra'], d['tuzilma']['oqituvchi']), (1, 1, 2))
        problems = {p['key']: p['soni'] for p in d['muammolar']}
        self.assertEqual((problems['mudirsiz_kafedra'], problems['talabasiz_guruh']), (0, 0))
        self.assertEqual(d['rollar']['admin'], 0)
