"""Bajarilgan ishlar: yuklash, ikki bosqichli tekshiruv, rad etish, qayta yuborish, foiz."""
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.accounts.models import User, Xabar
from apps.core.files import MemoryFileStorage, set_file_storage
from apps.core.testing import StoreTestCase
from apps.departments.models import OTM, Faculty, Department
from apps.teachers.models import Teacher
from apps.workload.models import IshDalili, Reja


def plan_data():
    return {'stavka': 'rate_1', 'variants': {'rate_1': {'fanlar': [], 'doc': {
        'uslubiy': [{'id': 'u1', 'nomi': "O'quv qo'llanma", 'rejaSoat': '60'},
                    {'id': 'u2', 'nomi': 'Uslubiy ko\'rsatma', 'rejaSoat': '40'}],
        'ilmiy': [{'id': 'i1', 'nomi': 'Scopus maqola', 'rejaSoat': '100'}],
        'ustozShogird': [{'id': 's1', 'nomi': 'Yosh o\'qituvchiga murabbiylik', 'rejaSoat': ''}],
    }}}}


class EvidenceTests(StoreTestCase):
    def setUp(self):
        self.storage = MemoryFileStorage()
        set_file_storage(self.storage)
        self.client = APIClient()
        otm = OTM.objects.create(name='U')
        fac = Faculty.objects.create(name='KIF', otm=otm)
        self.dep = Department.objects.create(name='Dasturlash', faculty=fac)
        self.mudir, self.mudir_t = self._teacher('mudir')
        self.oqit, self.oqit_t = self._teacher('oqit')
        self.oquv = User.objects.create_user('oquv', email='oquv@t.test', password='x', groups=['oquv_bolimi'])
        self.dep.head_of_department = self.mudir_t
        self.dep.save()
        self.reja = Reja.objects.create(teacher=self.oqit_t, department=self.dep, oquv_yili='2026-2027',
                                        data=plan_data())
        self.mudir_reja = Reja.objects.create(teacher=self.mudir_t, department=self.dep, oquv_yili='2026-2027',
                                              data=plan_data())

    def tearDown(self):
        set_file_storage(None)

    def _teacher(self, name):
        user = User.objects.create_user(name, email=f'{name}@t.test', password='x')
        teacher = Teacher.objects.create(user=user, full_name=name.title(), email=user.email)
        self.dep.teachers.add(teacher)
        return user, teacher

    def as_(self, user):
        self.client.force_authenticate(User.objects.get(pk=user.pk))
        return self.client

    def upload(self, user, reja, qator='u1', bolim='uslubiy', name='dalil.pdf', **extra):
        data = {'rejaId': reja.id, 'bolim': bolim, 'qatorId': qator, **extra}
        if name:
            data['fayllar'] = SimpleUploadedFile(name, b'%PDF-1.4 test', content_type='application/pdf')
        return self.as_(user).post('/api/crud/ish-dalillari/', data, format='multipart')

    def review(self, user, dalil_id, qaror, sabab=''):
        return self.as_(user).post(f'/api/crud/ish-dalillari/{dalil_id}/tekshirish/',
                                   {'qaror': qaror, 'sabab': sabab}, format='json')

    def test_full_flow_with_rejection_and_percent(self):
        res = self.upload(self.oqit, self.reja)
        self.assertEqual(res.status_code, 201, res.data)
        dalil_id = res.data['id']
        self.assertEqual(res.data['holat'], 'kafedrada')
        self.assertEqual(res.data['qatorNomi'], "O'quv qo'llanma")
        self.assertTrue(Xabar.objects.filter(user=self.mudir).exists())

        # O'quv bo'limi navbatni sakray olmaydi; mudir qabul qiladi
        self.assertEqual(self.review(self.oquv, dalil_id, 'qabul').status_code, 403)
        self.assertEqual(self.review(self.mudir, dalil_id, 'qabul').data['holat'], 'oquv_bolimida')
        # Rad etishda sabab majburiy
        self.assertEqual(self.review(self.oquv, dalil_id, 'rad').status_code, 400)
        self.assertEqual(self.review(self.oquv, dalil_id, 'rad', 'Fayl o\'qilmaydi').data['holat'], 'rad_etildi')
        self.assertTrue(any('Fayl o\'qilmaydi' in x.matn for x in Xabar.objects.filter(user=self.oqit)))

        # Qayta yuklash — yana kafedradan boshlanadi, fayllar qo'shiladi
        again = self.upload(self.oqit, self.reja, name='yangi.pdf')
        self.assertEqual((again.data['id'], again.data['holat'], len(again.data['fayllar'])),
                         (dalil_id, 'kafedrada', 2))
        self.review(self.mudir, dalil_id, 'qabul')
        self.assertEqual(self.review(self.oquv, dalil_id, 'qabul').data['holat'], 'qabul_qilindi')
        self.assertEqual(self.upload(self.oqit, self.reja).status_code, 400)  # qabul qilingan

        data = self.as_(self.oqit).get('/api/teacher/bajarilgan-ishlar/').data
        natija = data['natija']
        uslubiy = next(b for b in natija['bolimlar'] if b['bolim'] == 'uslubiy')
        self.assertEqual(uslubiy['foiz'], 60.0)            # 60 / (60+40)
        self.assertEqual(natija['umumiyFoiz'], 30.0)       # 60 / 200 soat
        self.assertEqual(len(data['qatorlar']), 4)

        # Faylni egasi va o'quv bo'limi yuklab oladi, begona — yo'q
        self.assertEqual(self.as_(self.oqit).get(f'/api/crud/ish-dalillari/{dalil_id}/fayl/?i=1').status_code, 200)
        self.assertEqual(self.as_(self.oquv).get(f'/api/crud/ish-dalillari/{dalil_id}/fayl/?i=0').status_code, 200)
        stranger = User.objects.create_user('st', email='st@t.test', password='x')
        Teacher.objects.create(user=stranger, full_name='St', email='st@t.test')
        self.assertEqual(self.as_(stranger).get(f'/api/crud/ish-dalillari/{dalil_id}/fayl/?i=0').status_code, 404)

    def test_head_own_work_skips_department_stage_and_label(self):
        res = self.upload(self.mudir, self.mudir_reja, qator='i1', bolim='ilmiy')
        self.assertEqual(res.data['holat'], 'oquv_bolimida')
        self.assertEqual(res.data['unvon'], 'Dasturlash kafedrasi mudiri')
        rows = self.as_(self.oquv).get('/api/crud/ish-dalillari/?holat=menga').data
        self.assertEqual([r['fio'] for r in rows], ['Mudir'])

    def test_validation(self):
        self.assertEqual(self.upload(self.oqit, self.reja, qator='nope').status_code, 400)
        self.assertEqual(self.upload(self.oqit, self.reja, name='virus.exe').status_code, 400)
        self.assertEqual(self.upload(self.oqit, self.reja, name=None).status_code, 400)  # fayl ham havola ham yo'q
        ok = self.upload(self.oqit, self.reja, qator='i1', bolim='ilmiy', name=None,
                         havola='https://doi.org/10.1000/xyz')
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(self.upload(self.mudir, self.reja).status_code, 404)  # boshqaning rejasi

    def test_owner_can_delete_pending_work(self):
        dalil_id = self.upload(self.oqit, self.reja).data['id']
        self.assertEqual(len(self.storage.files), 1)
        self.assertEqual(self.as_(self.mudir).delete(f'/api/crud/ish-dalillari/{dalil_id}/').status_code, 403)
        self.assertEqual(self.as_(self.oqit).delete(f'/api/crud/ish-dalillari/{dalil_id}/').status_code, 204)
        self.assertFalse(IshDalili.objects.filter(pk=dalil_id).exists())
        self.assertEqual(self.storage.files, {})

    def test_report_close_year_and_archive(self):
        dalil_id = self.upload(self.oqit, self.reja, qator='i1', bolim='ilmiy').data['id']
        self.review(self.mudir, dalil_id, 'qabul')
        self.review(self.oquv, dalil_id, 'qabul')
        report = self.as_(self.mudir).get('/api/hisobot/bajarilish/?oquvYili=2026-2027').data
        oqit_row = next(r for r in report if r['fio'] == 'Oqit')
        self.assertEqual(oqit_row['umumiyFoiz'], 50.0)  # 100 / 200 soat
        self.assertEqual(self.as_(self.oqit).get('/api/hisobot/bajarilish/?oquvYili=2026-2027').status_code, 403)
        xlsx = self.as_(self.oquv).get('/api/hisobot/bajarilish/?oquvYili=2026-2027&eksport=xlsx')
        self.assertEqual(xlsx.status_code, 200)
        self.assertTrue(xlsx.content.startswith(b'PK'))

        self.assertEqual(self.as_(self.mudir).post('/api/hisobot/yopish/', {'oquvYili': '2026-2027'},
                                                   format='json').status_code, 403)
        closed = self.as_(self.oquv).post('/api/hisobot/yopish/', {'oquvYili': '2026-2027'}, format='json').data
        self.assertEqual((closed['yopildi'], closed['jami']), (2, 2))
        # Yopilgan yilga yuklash bloklanadi, natija arxivda saqlanadi
        self.assertEqual(self.upload(self.oqit, self.reja, qator='u2').status_code, 400)
        archive = self.as_(self.oqit).get('/api/teacher/natijalar/').data
        self.assertEqual((archive[0]['oquvYili'], archive[0]['yopilgan'], archive[0]['umumiyFoiz']),
                         ('2026-2027', True, 50.0))
