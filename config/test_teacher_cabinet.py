"""O'qituvchi kabineti: guruhlar, ish qiymatlari va tasdiqlangan rejani himoyalash."""
from rest_framework.test import APIClient

from apps.academics.models import Group, Talaba
from apps.accounts.models import User
from apps.core.testing import StoreTestCase
from apps.departments.models import OTM, Department, Faculty
from apps.teachers.models import Teacher
from apps.workload.models import Reja

YIL = '2026-2027'


def _doc(ilmiy=None, uslubiy=None):
    return {'uslubiy': uslubiy or [], 'ilmiy': ilmiy or [], 'ustozShogird': [], 'reyting': {}}


class TeacherCabinetTests(StoreTestCase):
    def setUp(self):
        otm = OTM.objects.create(name='Universitet')
        fac = Faculty.objects.create(name='KIF', otm=otm)
        self.dep = Department.objects.create(name='Dasturlash', faculty=fac)
        self.g1 = Group.objects.create(name='DI-21', department=self.dep, students=2)
        self.g2 = Group.objects.create(name='DI-22', department=self.dep)
        self.g3 = Group.objects.create(name='Begona-11', department=self.dep)
        Talaba.objects.create(group=self.g1, fio='Aliyev Anvar')
        user = User.objects.create_user('oqit', email='oqit@t.test', password='x')
        self.teacher = Teacher.objects.create(user=user, full_name='Oqituvchi', email=user.email)
        self.dep.teachers.add(self.teacher)
        ilmiy = [{'id': 'i1', 'nomi': 'Scopus maqola', 'scopus': '0.25', 'respub': '', 'muddatReja': '10.05.2027'}]
        uslubiy = [{'id': 'u1', 'nomi': "O'quv qo'llanma", 'rejaBet': '12', 'muddatReja': '20.12.2026'}]
        fanlar = [
            {'id': 'f1', 'nomi': 'Python', 'baseNomi': 'Python', 'lessonType': 'maruza', 'soat': 30, 'semestr': 'kuzgi',
             'guruhlar': [{'id': self.g1.id, 'nomi': 'DI-21'}, {'id': self.g2.id, 'nomi': 'DI-22'}]},
            {'id': 'f2', 'nomi': 'Amaliyot', 'workloadKind': 'amaliyot', 'soat': 40, 'semestr': 'bahorgi',
             'guruhlar': [{'id': self.g1.id, 'nomi': 'DI-21'}]},
            {'id': 'f3', 'nomi': 'Java', 'lessonType': 'amaliyot', 'soat': 20, 'semestr': 'kuzgi'},
        ]
        self.reja = Reja.objects.create(teacher=self.teacher, department=self.dep, oquv_yili=YIL,
                                        data={'stavka': 'rate_1', 'variants': {'rate_1': {
                                            'fanlar': fanlar, 'doc': _doc(ilmiy, uslubiy)}}})
        self.client = APIClient()
        self.client.force_authenticate(user)

    def test_groups_from_own_plan_with_students(self):
        res = self.client.get('/api/teacher/guruhlar/')
        self.assertEqual(res.status_code, 200)
        names = [g['nomi'] for g in res.data['guruhlar']]
        self.assertEqual(names, ['DI-21', 'DI-22'])  # Begona-11 rejada yo'q
        di21 = res.data['guruhlar'][0]
        self.assertEqual([f['turi'] for f in di21['fanlar']], ["Ma'ruza", 'Amaliyot (praktika)'])
        self.assertEqual(di21['talabalar'][0]['fio'], 'Aliyev Anvar')
        self.assertEqual([f['nomi'] for f in res.data['biriktirilmagan']], ['Java'])

    def test_work_rows_carry_plan_values(self):
        rows = {r['id']: r for r in self.client.get('/api/teacher/bajarilgan-ishlar/').data['qatorlar']}
        self.assertEqual(rows['i1']['scopus'], '0.25')
        self.assertEqual(rows['u1']['rejaBet'], '12')

    def _save(self, ilmiy, uslubiy=None):
        uslubiy = uslubiy if uslubiy is not None else self.reja.data['variants']['rate_1']['doc']['uslubiy']
        return self.client.patch('/api/teacher/dashboard/', {
            'action': 'save_personal_plan', 'rejaId': self.reja.id, 'activeStavka': 'rate_1',
            'variants': {'rate_1': _doc(ilmiy, uslubiy)}}, format='json')

    def test_submitted_plan_allows_only_new_rows(self):
        self.reja.status = 'tekshiruvda'
        self.reja.save()
        old = self.reja.data['variants']['rate_1']['doc']['ilmiy']
        changed = [{**old[0], 'scopus': '1'}]
        self.assertEqual(self._save(changed).status_code, 403)
        self.assertEqual(self._save([]).status_code, 403)  # o'chirish ham taqiqlangan
        added = old + [{'id': 'i2', 'nomi': 'DGU guvohnoma'}]
        self.assertEqual(self._save(added).status_code, 200)
        self.reja.refresh_from_db()
        self.assertEqual(len(self.reja.data['variants']['rate_1']['doc']['ilmiy']), 2)

    def test_draft_plan_is_freely_editable(self):
        self.assertEqual(self._save([]).status_code, 200)
