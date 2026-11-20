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
        otm = OTM.objects.create(name='Universitet')
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
        self.create(pochta='o@uni.test', rol='oquv_bolimi', kafedraId='')
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

    def test_role_change_moves_head_and_reports_replaced(self):
        first = self.create(pochta='a@uni.test', rol='kafedra_mudiri').data
        second = self.create(pochta='b@uni.test', rol='kafedra_mudiri').data
        self.assertEqual(len(second['almashtirildi']), 1)
        self.dep1.refresh_from_db()
        self.assertEqual(self.dep1.head_of_department_id, second['id'])
        self.assertEqual(self.client.get(f"{URL}/{first['id']}").data['rol'], 'oqituvchi')
        # Mudirni oddiy o'qituvchiga tushirish — kafedra mudirsiz qoladi
        res = self.client.patch(f"{URL}/{second['id']}", {'rol': 'oqituvchi'}, format='json')
        self.assertEqual(res.data['rol'], 'oqituvchi')
        self.dep1.refresh_from_db()
        self.assertIsNone(self.dep1.head_of_department_id)

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
