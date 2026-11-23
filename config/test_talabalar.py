"""Guruh talabalari: kafedra bo'yicha cheklov, soni sinxronlash, Excel import; yuklama o'quv yili."""
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook
from rest_framework.test import APIClient

from apps.academics.models import Group, Talaba
from apps.accounts.models import User
from apps.core.testing import StoreTestCase
from apps.departments.models import OTM, Department, Faculty
from apps.teachers.models import Teacher

URL = '/api/crud/talabalar/'
IMPORT = '/api/crud/talabalar-import/'


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return SimpleUploadedFile('talabalar.xlsx', buf.getvalue(),
                              content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


class TalabalarTests(StoreTestCase):
    def setUp(self):
        otm = OTM.objects.create(name='Universitet')
        fac = Faculty.objects.create(name='KIF', otm=otm)
        self.dep1 = Department.objects.create(name='Dasturlash', faculty=fac)
        self.dep2 = Department.objects.create(name='Tarmoqlar', faculty=fac)
        self.g1 = Group.objects.create(name='DI-21', department=self.dep1)
        self.g2 = Group.objects.create(name='TT-21', department=self.dep2)
        user = User.objects.create_user('mudir', email='mudir@t.test', password='x')
        head = Teacher.objects.create(user=user, full_name='Mudir', email=user.email)
        self.dep1.teachers.add(head)
        self.dep1.head_of_department = head
        self.dep1.save()
        self.client = APIClient()
        self.client.force_authenticate(user)

    def test_head_manages_own_group_students_and_count_syncs(self):
        res = self.client.post(URL, {'group': self.g1.id, 'fio': '  Aliyev   Anvar ', 'telefon': '+998901112233'}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['fio'], 'Aliyev Anvar')
        self.client.post(URL, {'group': self.g1.id, 'fio': 'Valiyev Bobur'}, format='json')
        self.g1.refresh_from_db()
        self.assertEqual(self.g1.students, 2)
        self.assertEqual(len(self.client.get(URL, {'guruhId': self.g1.id}).data), 2)
        self.client.delete(f"{URL}{res.data['id']}/")
        self.g1.refresh_from_db()
        self.assertEqual(self.g1.students, 1)

    def test_other_department_forbidden_and_hidden(self):
        res = self.client.post(URL, {'group': self.g2.id, 'fio': 'Begona Talaba'}, format='json')
        self.assertEqual(res.status_code, 403)
        Talaba.objects.create(group=self.g2, fio='Begona Talaba')
        self.assertEqual(self.client.get(URL).data, [])
        file = _xlsx([['FIO'], ['Kimdir']])
        self.assertEqual(self.client.post(IMPORT, {'guruh_id': self.g2.id, 'file': file}, format='multipart').status_code, 403)

    def test_excel_import_preview_save_and_dedupe(self):
        Talaba.objects.create(group=self.g1, fio='Aliyev Anvar')
        rows = [['T/r', 'F.I.O', 'Telefon'], [1, 'Aliyev Anvar', ''], [2, 'Karimova Dilnoza', '+998 90 123 45 67'],
                [3, 'Saidov Jasur', None], [None, None, None]]
        preview = self.client.post(IMPORT, {'guruh_id': self.g1.id, 'file': _xlsx(rows)}, format='multipart')
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual((preview.data['yangi'], preview.data['takror'], preview.data['saved']), (2, 1, False))
        self.assertEqual(preview.data['talabalar'][0], {'fio': 'Karimova Dilnoza', 'telefon': '+998 90 123 45 67'})
        self.assertEqual(Talaba.objects.filter(group_id=self.g1.id).count(), 1)
        saved = self.client.post(IMPORT, {'guruh_id': self.g1.id, 'file': _xlsx(rows), 'save': 'true'}, format='multipart')
        self.assertTrue(saved.data['saved'])
        self.g1.refresh_from_db()
        self.assertEqual(self.g1.students, 3)

    def test_workload_upload_stores_academic_year(self):
        from unittest import mock
        fake = {'meta': {'title': 'X'}, 'kuzgi': [], 'bahorgi': [], 'totals': {'yillik': {'jami': 10}}}
        with mock.patch('apps.workload.views.parse_workload_excel', return_value=fake), \
                mock.patch('apps.workload.views.import_rows_to_yuklama', return_value={'kuzgi': [], 'bahorgi': []}):
            res = self.client.post('/api/crud/yuklama-excel/', {
                'file': _xlsx([['x']]), 'save': 'true', 'department_id': self.dep1.id, 'oquv_yili': '2026-2027',
            }, format='multipart')
        self.assertEqual(res.status_code, 200, res.data)
        self.dep1.refresh_from_db()
        self.assertEqual(self.dep1.yuklama_data['meta'], {'title': 'X', 'oquv_yili': '2026-2027'})
