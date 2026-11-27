"""Admin foydalanuvchilarni pochta/parol/rol bilan kiritadi; xodim shu rol bilan kiradi."""
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core.testing import StoreTestCase
from apps.departments.models import OTM, Department, Faculty
from apps.teachers.models import Teacher

URL = '/api/auth/foydalanuvchilar'
PAROL = 'Kuchli-Parol-4821'


class UsersAdminTests(StoreTestCase):
    def setUp(self):
        self.client = APIClient()
        self.otm = otm = OTM.objects.create(name='Universitet')
        self.fac = Faculty.objects.create(name='KIF', otm=otm)
        self.dep1 = Department.objects.create(name='Dasturlash', faculty=self.fac)
        self.dep2 = Department.objects.create(name='Tarmoqlar', faculty=self.fac)
        self.admin = User.objects.create_superuser('admin', email='admin@t.test', password='x')
        self.client.force_authenticate(self.admin)

    def create(self, **data):
        body = {'fio': 'Aliyev Anvar Akmalovich', 'telefon': '+998901112233', 'pochta': 'anvar@uni.test',
                'parol': PAROL, 'rol': 'oqituvchi', 'kafedraId': self.dep1.id, **data}
        return self.client.post(URL, body, format='json')

    def login_role(self, email, password=PAROL):
        anon = APIClient()
        res = anon.post('/api/auth/login', {'email': email, 'password': password}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        anon.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")
        return anon.get('/api/auth/scope').data

    def test_admin_creates_head_who_logs_in_with_that_role(self):
        res = self.create(rol='kafedra_mudiri', kafedraId=self.dep2.id)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual((res.data['rol'], res.data['telefon']), ('kafedra_mudiri', '+998901112233'))
        scope = self.login_role('anvar@uni.test')
        self.assertEqual((scope['role'], scope['kafedraIds']), ('kafedra_mudiri', [self.dep2.id]))
        self.assertEqual(scope['unvon'], 'Tarmoqlar kafedrasi mudiri')

    def test_each_role(self):
        self.create(pochta='d@uni.test', rol='dekan', fakultetId=self.fac.id, kafedraId='')
        self.assertEqual(self.create(pochta='o@uni.test', rol='oquv_bolimi', kafedraId='').status_code, 400)  # OTM shart
        self.assertEqual(self.create(pochta='o@uni.test', rol='oquv_bolimi', kafedraId='', otmId=self.otm.id).status_code, 201)
        self.create(pochta='t@uni.test', rol='oqituvchi')
        self.assertEqual(self.login_role('d@uni.test')['role'], 'dekan')
        self.assertEqual(self.login_role('o@uni.test')['role'], 'oquv_bolimi')
        self.assertEqual(self.login_role('t@uni.test')['role'], 'oqituvchi')
        rows = {r['pochta']: r for r in self.client.get(URL).data}
        self.assertEqual(rows['d@uni.test']['unvon'], 'KIF dekani')

    def test_validation(self):
        self.assertEqual(self.create(rol='dekan', kafedraId='').status_code, 400)  # fakultet yo'q
        self.assertEqual(self.create(rol='direktor').status_code, 400)
        self.assertEqual(self.create(parol='123').status_code, 400)
        self.assertEqual(self.create(kafedraId='').status_code, 400)
        self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.create(pochta='ANVAR@uni.test').status_code, 400)  # takror pochta
        # Xato bo'lgan urinishlar hech narsa qoldirmaydi
        self.assertEqual(User.objects.filter(email__iexact='anvar@uni.test').count(), 1)

    def test_head_slot_is_unique_until_freed(self):
        first = self.create(pochta='a@uni.test', rol='kafedra_mudiri').data
        # Kafedrada mudir bor — ikkinchi odamga shu rol berilmaydi (yaratishda ham, tahrirlashda ham)
        blocked = self.create(pochta='b@uni.test', rol='kafedra_mudiri')
        self.assertEqual(blocked.status_code, 400)
        self.assertIn('kafedraId', blocked.data)
        second = self.create(pochta='b@uni.test').data
        res = self.client.patch(f"{URL}/{second['id']}", {'rol': 'kafedra_mudiri', 'kafedraId': self.dep1.id}, format='json')
        self.assertEqual(res.status_code, 400)
        self.dep1.refresh_from_db()
        self.assertEqual(self.dep1.head_of_department_id, first['id'])
        # Mudirni oddiy o'qituvchiga tushirish — o'rin bo'shaydi va boshqaga berish mumkin
        res = self.client.patch(f"{URL}/{first['id']}", {'rol': 'oqituvchi'}, format='json')
        self.assertEqual(res.data['rol'], 'oqituvchi')
        self.dep1.refresh_from_db()
        self.assertIsNone(self.dep1.head_of_department_id)
        res = self.client.patch(f"{URL}/{second['id']}", {'rol': 'kafedra_mudiri', 'kafedraId': self.dep1.id}, format='json')
        self.assertEqual((res.status_code, res.data['rol']), (200, 'kafedra_mudiri'))

    def test_password_set_by_admin_and_changed_by_user(self):
        row = self.create().data
        self.assertEqual(self.client.post(f"{URL}/{row['id']}/parol", {'parol': 'Yangi-Parol-7710'},
                                          format='json').status_code, 200)
        self.login_role('anvar@uni.test', 'Yangi-Parol-7710')
        user = User.objects.get(email='anvar@uni.test')
        own = APIClient()
        own.force_authenticate(user)
        res = own.post('/api/auth/change-password', {'old_password': 'Yangi-Parol-7710',
                                                      'new_password': 'Mening-Parolim-3390'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.login_role('anvar@uni.test', 'Mening-Parolim-3390')

    def test_block_and_account_for_existing_profile(self):
        teacher = Teacher.objects.create(full_name='Eski Profil', email='eski@uni.test')
        self.dep1.teachers.add(teacher)
        res = self.client.patch(f'{URL}/{teacher.id}', {'parol': PAROL}, format='json')
        self.assertTrue(res.data['hisob'], res.data)
        self.login_role('eski@uni.test')
        self.client.patch(f'{URL}/{teacher.id}', {'faol': False}, format='json')
        res = APIClient().post('/api/auth/login', {'email': 'eski@uni.test', 'password': PAROL}, format='json')
        self.assertEqual(res.status_code, 401)

    def test_non_admin_forbidden_and_signup_closed(self):
        self.create()
        user = User.objects.get(email='anvar@uni.test')
        other = APIClient()
        other.force_authenticate(user)
        self.assertEqual(other.get(URL).status_code, 403)
        self.assertEqual(other.post(URL, {}, format='json').status_code, 403)
        res = APIClient().post('/api/auth/signup', {'email': 'x@uni.test', 'password': PAROL}, format='json')
        self.assertEqual(res.status_code, 403)

    def test_unlinked_account_matched_by_email(self):
        # Admin hisobi o'qituvchi profiliga bog'lanmagan, lekin pochtasi bir xil
        teacher = Teacher.objects.create(full_name='Admin Profil', email='ADMIN@t.test')
        rows = self.client.get(URL).data
        row = next(r for r in rows if r['id'] == teacher.id)
        self.assertEqual((row['hisob'], row['rol']), (True, 'admin'))
        self.assertFalse(any(r['id'] is None and r['pochta'] == 'admin@t.test' for r in rows))
        self.assertEqual(self.client.patch(f'{URL}/{teacher.id}', {'rol': 'dekan'}, format='json').status_code, 400)
        self.assertEqual(self.create(pochta='admin@t.test').status_code, 400)
        self.assertEqual(User.objects.filter(email__iexact='admin@t.test').count(), 1)

    def test_staff_added_here_hidden_from_teacher_list(self):
        created = self.create(pochta='dekan.x@uni.test').data
        ids = [t['id'] for t in self.client.get('/api/crud/oqituvchilar/').data]
        self.assertNotIn(created['id'], ids)
        # Foydalanuvchilar ro'yxatida esa ko'rinadi
        self.assertIn(created['id'], [r['id'] for r in self.client.get(URL).data])


class HeadAccountsTests(StoreTestCase):
    """Kafedra mudiri faqat o'z kafedrasidagi oddiy o'qituvchilarga kirish hisobi beradi."""

    def setUp(self):
        otm = OTM.objects.create(name='Universitet')
        fac = Faculty.objects.create(name='KIF', otm=otm)
        self.dep1 = Department.objects.create(name='Dasturlash', faculty=fac)
        self.dep2 = Department.objects.create(name='Tarmoqlar', faculty=fac)
        head_user = User.objects.create_user('mudir', email='mudir@t.test', password='x')
        self.head = Teacher.objects.create(user=head_user, full_name='Mudir', email=head_user.email)
        self.own = Teacher.objects.create(full_name='Oz Oqituvchi', email='oz@t.test')
        self.other = Teacher.objects.create(full_name='Begona Oqituvchi', email='begona@t.test')
        self.dep1.teachers.add(self.head, self.own)
        self.dep2.teachers.add(self.other)
        self.dep1.head_of_department = self.head
        self.dep1.save()
        self.client = APIClient()
        self.client.force_authenticate(head_user)

    def test_head_lists_and_opens_account_for_own_teacher(self):
        rows = self.client.get(URL).data
        self.assertEqual({r['id'] for r in rows}, {self.head.id, self.own.id})
        res = self.client.patch(f'{URL}/{self.own.id}', {'pochta': 'oz@t.test', 'parol': PAROL}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertTrue(res.data['hisob'])
        login = APIClient().post('/api/auth/login', {'email': 'oz@t.test', 'password': PAROL}, format='json')
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.client.post(f'{URL}/{self.own.id}/parol', {'parol': 'Boshqa-Parol-5512'},
                                          format='json').status_code, 200)

    def test_head_limits(self):
        # Boshqa kafedra, o'zi, rol berish va yangi xodim yaratish — taqiqlangan
        self.assertEqual(self.client.patch(f'{URL}/{self.other.id}', {'parol': PAROL}, format='json').status_code, 403)
        self.assertEqual(self.client.patch(f'{URL}/{self.head.id}', {'parol': PAROL}, format='json').status_code, 403)
        self.assertEqual(self.client.patch(f'{URL}/{self.own.id}', {'rol': 'dekan'}, format='json').status_code, 403)
        self.assertEqual(self.client.patch(f'{URL}/{self.own.id}', {'fio': 'X'}, format='json').status_code, 403)
        self.assertEqual(self.client.post(URL, {'fio': 'Y', 'pochta': 'y@t.test', 'parol': PAROL}, format='json').status_code, 403)
        self.assertEqual(self.client.post(f'{URL}/{self.other.id}/parol', {'parol': PAROL}, format='json').status_code, 403)

    def test_plain_teacher_forbidden(self):
        teacher_user = User.objects.create_user('oddiy', email='oddiy@t.test', password='x')
        Teacher.objects.create(user=teacher_user, full_name='Oddiy', email=teacher_user.email)
        c = APIClient()
        c.force_authenticate(teacher_user)
        self.assertEqual(c.get(URL).status_code, 403)
