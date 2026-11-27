"""Rollar: hudud filtri, yozish cheklovlari, tasdiqlash oqimi, xabarlar."""
from rest_framework.test import APIClient

from apps.accounts.models import User, Xabar
from apps.core.testing import StoreTestCase
from apps.academics.models import Subject
from apps.departments.models import OTM, Faculty, Department
from apps.teachers.models import Teacher
from apps.workload.models import Approval, Reja


class RoleScopeTests(StoreTestCase):
    def setUp(self):
        self.client = APIClient()
        otm = OTM.objects.create(name='Universitet')
        self.fac_a = Faculty.objects.create(name='KIF', otm=otm)
        self.fac_b = Faculty.objects.create(name='Fizika', otm=otm)
        self.dep_a1 = Department.objects.create(name='Dasturlash', faculty=self.fac_a)
        self.dep_a2 = Department.objects.create(name='Tarmoqlar', faculty=self.fac_a)
        self.dep_b1 = Department.objects.create(name='Optika', faculty=self.fac_b)

        self.admin = User.objects.create_superuser('admin', email='admin@t.test', password='x')
        self.oquv = self._user('oquv', groups=['oquv_bolimi'])
        self.oquv.otm_id = otm.id
        self.oquv.save()
        self.mudir, self.mudir_t = self._teacher('mudir', self.dep_a1)
        self.dekan, self.dekan_t = self._teacher('dekan', self.dep_a2)
        self.oqit, self.oqit_t = self._teacher('oqit', self.dep_a1)
        self.boshqa, self.boshqa_t = self._teacher('boshqa', self.dep_b1)
        self.dep_a1.head_of_department = self.mudir_t
        self.dep_a1.save()
        self.fac_a.dean = self.dekan_t
        self.fac_a.save()

        self.reja_a1 = Reja.objects.create(teacher=self.oqit_t, department=self.dep_a1, oquv_yili='2026-2027')
        self.reja_b1 = Reja.objects.create(teacher=self.boshqa_t, department=self.dep_b1, oquv_yili='2026-2027')
        self.sub_a1 = Subject.objects.create(name='Python', department=self.dep_a1)
        self.sub_b1 = Subject.objects.create(name='Linzalar', department=self.dep_b1)

    def _user(self, name, groups=None):
        return User.objects.create_user(name, email=f'{name}@t.test', password='x', groups=groups or [])

    def _teacher(self, name, department):
        user = self._user(name)
        teacher = Teacher.objects.create(user=user, full_name=name.title(), email=user.email)
        department.teachers.add(teacher)
        return user, teacher

    def as_(self, user):
        self.client.force_authenticate(user)
        return self.client

    def ids(self, response):
        data = response.data
        rows = data['results'] if isinstance(data, dict) and 'results' in data else data
        return {int(r['id']) for r in rows}

    # --- scope ---------------------------------------------------------
    def test_scope_endpoint_roles(self):
        self.assertEqual(self.as_(self.admin).get('/api/auth/scope').data['role'], 'admin')
        self.assertEqual(self.as_(self.oquv).get('/api/auth/scope').data['role'], 'oquv_bolimi')
        dekan = self.as_(self.dekan).get('/api/auth/scope').data
        self.assertEqual(dekan['role'], 'dekan')
        self.assertEqual(set(dekan['kafedraIds']), {self.dep_a1.id, self.dep_a2.id})
        self.assertEqual(dekan['unvon'], 'KIF dekani')
        mudir = self.as_(self.mudir).get('/api/auth/scope').data
        self.assertEqual((mudir['role'], mudir['kafedraIds']), ('kafedra_mudiri', [self.dep_a1.id]))
        self.assertEqual(self.as_(self.oqit).get('/api/auth/scope').data['role'], 'oqituvchi')

    def test_read_scope_per_role(self):
        url = '/api/crud/rejalar/'
        self.assertEqual(self.ids(self.as_(self.admin).get(url)), {self.reja_a1.id, self.reja_b1.id})
        self.assertEqual(self.ids(self.as_(self.oquv).get(url)), {self.reja_a1.id, self.reja_b1.id})
        self.assertEqual(self.ids(self.as_(self.dekan).get(url)), {self.reja_a1.id})
        self.assertEqual(self.ids(self.as_(self.mudir).get(url)), {self.reja_a1.id})
        self.assertEqual(self.ids(self.as_(self.boshqa).get(url)), {self.reja_b1.id})
        teachers = self.ids(self.as_(self.mudir).get('/api/crud/oqituvchilar/'))
        self.assertEqual(teachers, {self.mudir_t.id, self.oqit_t.id})
        self.assertEqual(self.ids(self.as_(self.mudir).get('/api/crud/fanlar/')), {self.sub_a1.id})
        self.assertEqual(self.ids(self.as_(self.dekan).get('/api/crud/kafedralar/')),
                         {self.dep_a1.id, self.dep_a2.id})
        self.assertEqual(self.ids(self.as_(self.mudir).get('/api/crud/fakultetlar/')), {self.fac_a.id})
        self.assertEqual(self.as_(self.mudir).get(f'/api/crud/rejalar/{self.reja_b1.id}/').status_code, 404)

    def test_write_scope(self):
        mudir = self.as_(self.mudir)
        ok = mudir.post('/api/crud/fanlar/', {'name': 'Java', 'department': self.dep_a1.id}, format='json')
        self.assertEqual(ok.status_code, 201)
        bad = mudir.post('/api/crud/fanlar/', {'name': 'Java', 'department': self.dep_b1.id}, format='json')
        self.assertEqual(bad.status_code, 403)
        moved = mudir.patch(f'/api/crud/fanlar/{self.sub_a1.id}/', {'department': self.dep_b1.id}, format='json')
        self.assertEqual(moved.status_code, 403)
        # Kafedra mudiri kafedra nomini o'zgartira olmaydi, o'qituvchilar ro'yxatini — ha
        self.assertEqual(mudir.patch(f'/api/crud/kafedralar/{self.dep_a1.id}/', {'name': 'X'},
                                     format='json').status_code, 403)
        self.assertEqual(mudir.patch(f'/api/crud/kafedralar/{self.dep_a1.id}/',
                                     {'teachers': [self.mudir_t.id]}, format='json').status_code, 200)
        self.assertEqual(mudir.post('/api/crud/otm/', {'name': 'Yangi'}, format='json').status_code, 403)
        # Dekan faqat ko'radi
        self.assertEqual(self.as_(self.dekan).post('/api/crud/fanlar/', {
            'name': 'Java', 'department': self.dep_a1.id}, format='json').status_code, 403)
        # O'quv bo'limi normativlarni boshqaradi, fanlarni emas
        self.assertEqual(self.as_(self.oquv).post('/api/crud/fanlar/', {
            'name': 'Java', 'department': self.dep_a1.id}, format='json').status_code, 403)
        # Oddiy o'qituvchi hech narsa yozmaydi
        self.assertEqual(self.as_(self.oqit).post('/api/crud/fanlar/', {
            'name': 'Java', 'department': self.dep_a1.id}, format='json').status_code, 403)

    def test_admin_can_grant_oquv_bolimi(self):
        url = f'/api/auth/users/{self.oqit.id}/rollar'
        self.assertEqual(self.as_(self.mudir).patch(url, {'oquv_bolimi': True}, format='json').status_code, 403)
        self.assertEqual(self.as_(self.admin).patch(url, {'oquv_bolimi': True}, format='json').data['oquv_bolimi'],
                         True)
        fresh = User.objects.get(pk=self.oqit.id)  # so'rovda foydalanuvchi bazadan qayta o'qiladi
        self.assertEqual(self.as_(fresh).get('/api/auth/scope').data['role'], 'oquv_bolimi')

    # --- approval flow -------------------------------------------------
    def decide(self, user, qaror, izoh=''):
        return self.as_(user).post(f'/api/crud/rejalar/{self.reja_a1.id}/qaror/',
                                   {'qaror': qaror, 'izoh': izoh}, format='json')

    def test_approval_flow_order_and_notifications(self):
        url = f'/api/crud/rejalar/{self.reja_a1.id}/yuborish/'
        self.assertEqual(self.as_(self.boshqa).post(url).status_code, 404)  # begona reja
        self.assertEqual(self.as_(self.oqit).post(url).status_code, 200)
        self.assertEqual(Reja.objects.get(pk=self.reja_a1.id).status, 'tekshiruvda')
        self.assertTrue(Xabar.objects.filter(user=self.mudir).exists())

        # Navbat: kafedra. Dekan va o'quv bo'limi hali qaror qila olmaydi
        self.assertEqual(self.decide(self.dekan, 'tasdiqlash').status_code, 403)
        self.assertEqual(self.decide(self.oquv, 'tasdiqlash').status_code, 403)
        self.assertEqual(self.decide(self.mudir, 'rad_etish').status_code, 400)  # izohsiz
        self.assertEqual(self.decide(self.mudir, 'tasdiqlash').status_code, 200)
        self.assertEqual(self.decide(self.dekan, 'tasdiqlash').status_code, 200)
        rejected = self.decide(self.oquv, 'rad_etish', 'Ilmiy ishlar to\'ldirilmagan')
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(Reja.objects.get(pk=self.reja_a1.id).status, 'rad_etilgan')
        self.assertTrue(any('Ilmiy ishlar' in x.matn for x in Xabar.objects.filter(user=self.oqit)))

        # Qayta yuborish — hamma bosqich boshidan
        self.assertEqual(self.as_(self.oqit).post(url).status_code, 200)
        states = {a.stage: a.state for a in Approval.objects.filter(reja_id=self.reja_a1.id)}
        self.assertEqual(states, {'kafedra': 'kutilmoqda', 'dekan': 'kutilmoqda', 'oquv_bolimi': 'kutilmoqda'})
        for user in (self.mudir, self.dekan, self.oquv):
            self.assertEqual(self.decide(user, 'tasdiqlash').status_code, 200)
        self.assertEqual(Reja.objects.get(pk=self.reja_a1.id).status, 'tasdiqlangan')
        inbox = self.as_(self.oqit).get('/api/crud/xabarlar/').data
        self.assertGreaterEqual(inbox['oqilmagan'], 2)
        self.as_(self.oqit).post('/api/crud/xabarlar/oqildi/', {}, format='json')
        self.assertEqual(self.as_(self.oqit).get('/api/crud/xabarlar/').data['oqilmagan'], 0)

    def test_head_own_plan_skips_own_stage(self):
        own = Reja.objects.create(teacher=self.mudir_t, department=self.dep_a1, oquv_yili='2026-2027')
        self.assertEqual(self.as_(self.mudir).post(f'/api/crud/rejalar/{own.id}/yuborish/').status_code, 200)
        states = {a.stage: a.state for a in Approval.objects.filter(reja_id=own.id)}
        self.assertEqual(states['kafedra'], 'tasdiqlangan')
        self.assertEqual(self.as_(self.mudir).post(f'/api/crud/rejalar/{own.id}/qaror/',
                                                   {'qaror': 'tasdiqlash'}, format='json').status_code, 403)
        self.assertEqual(self.as_(self.dekan).post(f'/api/crud/rejalar/{own.id}/qaror/',
                                                   {'qaror': 'tasdiqlash'}, format='json').status_code, 200)

    def test_role_dashboard_lists_my_pending(self):
        self.as_(self.oqit).post(f'/api/crud/rejalar/{self.reja_a1.id}/yuborish/')
        data = self.as_(self.mudir).get('/api/dashboard/rol/').data
        self.assertEqual([a['rejaId'] for a in data['kutilayotganAmallar']], [str(self.reja_a1.id)])
        self.assertEqual(self.as_(self.dekan).get('/api/dashboard/rol/').data['kutilayotganAmallar'], [])
        self.assertEqual(self.as_(self.oqit).get('/api/dashboard/rol/').status_code, 403)

    def test_head_sees_only_own_department_not_sibling(self):
        """Bir fakultetdagi qo'shni kafedra (Tarmoqlar) ma'lumotlari Dasturlash mudiriga ko'rinmaydi."""
        from apps.academics.models import Group
        g_a1 = Group.objects.create(name='DI-21', department=self.dep_a1)
        g_a2 = Group.objects.create(name='TT-21', department=self.dep_a2)
        Group.objects.create(name='OP-21', department=self.dep_b1)
        sub_a2 = Subject.objects.create(name='Tarmoqlar asoslari', department=self.dep_a2)
        mudir = self.as_(self.mudir)
        self.assertEqual(self.ids(mudir.get('/api/crud/guruhlar/')), {g_a1.id})
        self.assertEqual(self.ids(mudir.get('/api/crud/fanlar/')), {self.sub_a1.id})
        self.assertEqual(self.ids(mudir.get('/api/crud/oqituvchilar/')), {self.mudir_t.id, self.oqit_t.id})
        self.assertEqual(self.ids(mudir.get('/api/crud/kafedralar/')), {self.dep_a1.id})
        self.assertEqual(mudir.get(f'/api/crud/guruhlar/{g_a2.id}/').status_code, 404)
        self.assertEqual(mudir.get(f'/api/crud/fanlar/{sub_a2.id}/').status_code, 404)
        # Dekan esa fakultetidagi ikkala kafedrani ko'radi
        self.assertEqual(self.ids(self.as_(self.dekan).get('/api/crud/guruhlar/')), {g_a1.id, g_a2.id})
