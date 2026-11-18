"""Golden scenarios: every API path the frontend (and tests) rely on.

IDs refer to rows in tools/golden/golden.sqlite3 (built by make_dataset.py). Each scenario
runs on a fresh copy of that database; mutation scenarios end with re-reads so cascades and
derived values are compared too.
"""
OTM1, OTM2 = 8, 9
FAC1, FAC2 = 9, 10
DEP1, DEP2, DEP3 = 9, 10, 11
T13, TA, TB, TC = 13, 20, 21, 22          # TA=teacher@ (Yusupov), TB=teacher2@ (Aliyev)
REJA19, PLAN_A, PLAN_B, REJA_NULL = 19, 20, 21, 22
SUBJ_ALG, SUBJ_GEO, SUBJ_FIRST = 682, 683, 619
G1, G2 = 4, 5
WT_MARUZA, WT_FAN = 1, 7
NORM1, NORM2 = 1, 2
ASG1, ASG2 = 233, 234
DLMD_A, DLMD_A2, DLMD_B = 10, 11, 12
U_SUPER, U_TEACHER, U_TEACHER2, U_NOPROFILE = 9, 28, 29, 26
APPR_A1 = None  # looked up by API in scenarios that need it


def get(path, actor='super', **kw):
    return dict(method='GET', path=path, actor=actor, **kw)


def post(path, data, actor='super', **kw):
    return dict(method='POST', path=path, data=data, actor=actor, **kw)


def put(path, data, actor='super', **kw):
    return dict(method='PUT', path=path, data=data, actor=actor, **kw)


def patch(path, data, actor='super', **kw):
    return dict(method='PATCH', path=path, data=data, actor=actor, **kw)


def delete(path, actor='super', **kw):
    return dict(method='DELETE', path=path, actor=actor, **kw)


SCENARIOS = {}


def scenario(name, *steps):
    assert name not in SCENARIOS, name
    SCENARIOS[name] = {'name': name, 'steps': list(steps)}


C = '/api/crud'

# ---------------------------------------------------------------- reads
scenario('root', get(f'{C}/'))
for res in ('otm', 'fakultetlar', 'kafedralar', 'guruhlar', 'fanlar', 'oqituvchilar', 'rejalar',
            'dl-md', 'dlmd-turlari', 'topshiriqlar', 'tasdiqlash', 'normativlar'):
    scenario(f'list_{res}', get(f'{C}/{res}/'))
    scenario(f'list_{res}_page1', get(f'{C}/{res}/?page=1'))
    scenario(f'list_{res}_anonymous', get(f'{C}/{res}/', actor=None))
scenario('list_kafedra_yuklama', get(f'{C}/kafedra-yuklama/'))
scenario('list_kafedra_yuklama_dep2', get(f'{C}/kafedra-yuklama/?kafedraId={DEP2}'))
scenario('fanlar_pages', get(f'{C}/fanlar/?page=2'), get(f'{C}/fanlar/?page=4'), get(f'{C}/fanlar/?page=999'),
         get(f'{C}/fanlar/?page=abc'))
scenario('otm_detail', get(f'{C}/otm/{OTM1}/'), get(f'{C}/otm/999/'), get(f'{C}/otm/abc/'))
scenario('otm_hierarchy', get(f'{C}/otm/hierarchy/'))
scenario('fakultetlar_filters', get(f'{C}/fakultetlar/?otmId={OTM2}'), get(f'{C}/fakultetlar/{FAC2}/'))
scenario('kafedralar_filters', get(f'{C}/kafedralar/?fakultetId={FAC2}'), get(f'{C}/kafedralar/?otmId={OTM1}'),
         get(f'{C}/kafedralar/{DEP2}/'), get(f'{C}/kafedralar/?otmId={OTM2}&fakultetId={FAC2}'))
scenario('guruhlar_filters', get(f'{C}/guruhlar/?kafedraId={DEP2}'), get(f'{C}/guruhlar/?fakultetId={FAC1}'),
         get(f'{C}/guruhlar/?otmId={OTM2}'), get(f'{C}/guruhlar/?kurs=1'), get(f'{C}/guruhlar/?kurs=course_3'),
         get(f'{C}/guruhlar/{G2}/'))
scenario('fanlar_filters', get(f'{C}/fanlar/?kafedraId={DEP2}'), get(f'{C}/fanlar/?kafedraId={DEP1}&page=1'),
         get(f'{C}/fanlar/{SUBJ_ALG}/'))
scenario('oqituvchilar_filters', get(f'{C}/oqituvchilar/?kafedraId={DEP2}'),
         get(f'{C}/oqituvchilar/?fakultetId={FAC1}'), get(f'{C}/oqituvchilar/?otmId={OTM2}'),
         get(f'{C}/oqituvchilar/?rate=rate_1'), get(f'{C}/oqituvchilar/?kafedraId={DEP1}&rate=rate_0_5_ichki'),
         get(f'{C}/oqituvchilar/{TA}/'), get(f'{C}/oqituvchilar/999/'))
scenario('rejalar_filters', get(f'{C}/rejalar/?oqituvchiId={TA}'), get(f'{C}/rejalar/?oquvYili=2025-2026'),
         get(f'{C}/rejalar/?oquvYiliNomi=2026-2027'), get(f'{C}/rejalar/?kafedraId={DEP2}'),
         get(f'{C}/rejalar/?departmentId={DEP1}'), get(f'{C}/rejalar/{PLAN_A}/'), get(f'{C}/rejalar/{REJA19}/'),
         get(f'{C}/rejalar/{REJA_NULL}/'))
scenario('dlmd_filters', get(f'{C}/dl-md/?oqituvchiId={TA}'), get(f'{C}/dl-md/?kafedraId={DEP2}'),
         get(f'{C}/dl-md/?fakultetId={FAC2}'), get(f'{C}/dl-md/?otmId={OTM1}'), get(f'{C}/dl-md/?tur=md'),
         get(f'{C}/dl-md/{DLMD_A}/'))
scenario('topshiriq_tasdiq_filters', get(f'{C}/topshiriqlar/?rejaId={PLAN_A}'), get(f'{C}/topshiriqlar/{ASG1}/'),
         get(f'{C}/tasdiqlash/?rejaId={PLAN_A}'), get(f'{C}/tasdiqlash/?rejaId={REJA19}'))
scenario('normativlar_types', get(f'{C}/normativlar/?type=yuklama_turi'),
         get(f'{C}/normativlar/?type=academic_year'), get(f'{C}/normativlar/?type=position_norm'),
         get(f'{C}/normativlar/?type=position_norm&oquvYili=2026-2027'),
         get(f'{C}/normativlar/?type=normativ&yuklamaTuriId={WT_MARUZA}'),
         get(f'{C}/normativlar/?yuklamaTuriId={WT_FAN}'), get(f'{C}/normativlar/{NORM1}/'))

# Non-admin roles see only their own personal records
for actor in ('teacher', 'teacher2', 'noprofile', 'dekan'):
    scenario(f'role_reads_{actor}',
             get(f'{C}/oqituvchilar/', actor=actor), get(f'{C}/rejalar/', actor=actor),
             get(f'{C}/dl-md/', actor=actor), get(f'{C}/topshiriqlar/', actor=actor),
             get(f'{C}/tasdiqlash/', actor=actor), get(f'{C}/fanlar/?kafedraId={DEP2}', actor=actor),
             get(f'{C}/oqituvchilar/{T13}/', actor=actor), get(f'{C}/rejalar/{PLAN_A}/', actor=actor),
             post(f'{C}/otm/', {'name': 'Taqiqlangan'}, actor=actor))

# Dashboards
scenario('stats', get('/api/dashboard/stats/'), get('/api/dashboard/stats/', actor='admin_group'),
         get('/api/dashboard/stats/', actor='teacher'), get('/api/dashboard/stats/', actor=None))
for actor in ('teacher', 'teacher2', 'noprofile', 'super'):
    scenario(f'teacher_dashboard_{actor}', get('/api/teacher/dashboard/', actor=actor))
scenario('teacher_document',
         get(f'/api/teacher/dashboard/?document=1&rejaId={PLAN_A}', actor='teacher'),
         get(f'/api/teacher/dashboard/?document=1&rejaId={PLAN_B}', actor='teacher'),
         get(f'/api/teacher/dashboard/?document=1&rejaId=999', actor='teacher'),
         get(f'/api/teacher/dashboard/?document=1&rejaId=abc', actor='teacher'),
         get(f'/api/teacher/dashboard/?document=1&rejaId={REJA_NULL}', actor='noprofile'),
         get('/api/teacher/dashboard/', actor=None))
for actor in ('super', 'admin_group', 'dekan', 'kafedra', 'oquv', 'teacher', 'noprofile'):
    scenario(f'me_{actor}', get('/api/auth/me', actor=actor))
scenario('me_anonymous', get('/api/auth/me', actor=None))

# ---------------------------------------------------------------- auth
A = '/api/auth'
LOGIN_SUPER = dict(method='POST', path=f'{A}/login', data={'email': 'super@golden.test', 'password': 'Golden-Pass-1!'},
                   save={'access': 'access', 'refresh': 'refresh'})
scenario('auth_token_cycle', LOGIN_SUPER,
         dict(method='GET', path=f'{A}/me', bearer='$access'),
         dict(method='GET', path=f'{C}/otm/', bearer='$access'),
         dict(method='POST', path=f'{A}/refresh', data={'refresh': '$refresh'}, save={'access2': 'access', 'refresh2': 'refresh'}),
         dict(method='POST', path=f'{A}/refresh', data={'refresh': '$refresh'}),
         dict(method='POST', path=f'{A}/refresh', data={'refresh': '$refresh2'}),
         dict(method='POST', path=f'{A}/refresh', data={'refresh': 'garbage'}),
         dict(method='POST', path=f'{A}/refresh', data={}),
         dict(method='POST', path=f'{A}/logout', data={'refresh': '$refresh'}, bearer='$access2'),
         dict(method='POST', path=f'{A}/logout', data={}, bearer='$access2'))
scenario('auth_bad_headers',
         dict(method='GET', path=f'{A}/me', auth_header='Bearer'),
         dict(method='GET', path=f'{A}/me', auth_header='Token abc'),
         dict(method='GET', path=f'{A}/me', auth_header='Bearer garbage'),
         dict(method='GET', path=f'{A}/me', auth_header='Bearer a b'),
         dict(method='GET', path=f'{C}/otm/', auth_header='Bearer eyJhbGciOiJIUzI1NiJ9.eyJ4IjoxfQ.sig'))
scenario('auth_login_variants',
         dict(method='POST', path=f'{A}/login', data={'email': '  SUPER@golden.test ', 'password': 'Golden-Pass-1!'}),
         dict(method='POST', path=f'{A}/login', data={'email': 'super@golden.test', 'password': 'wrong'}),
         dict(method='POST', path=f'{A}/login', data={'email': 'nobody@golden.test', 'password': 'x'}),
         dict(method='POST', path=f'{A}/login', data={'email': 'inactive@golden.test', 'password': 'Golden-Pass-1!'}),
         dict(method='POST', path=f'{A}/login', data={'username': 'golden_user_9', 'password': 'Golden-Pass-1!'}),
         dict(method='POST', path=f'{A}/login', data={'email': 'not-an-email', 'password': 'x'}),
         dict(method='POST', path=f'{A}/login', data={'email': 'teacher@golden.test', 'password': 'Golden-Pass-1!'}),
         dict(method='POST', path=f'{A}/login', data={'email': 'dekan@golden.test', 'password': 'Golden-Pass-1!'}),
         dict(method='POST', path=f'{A}/signin', data={'email': 'teacher2@golden.test', 'password': 'Golden-Pass-1!'}),
         dict(method='POST', path=f'{A}/signin', data={'email': 'teacher2@golden.test', 'password': 'bad'}))
scenario('auth_signup',
         dict(method='POST', path=f'{A}/signup', data={'email': 'New.User@Golden.test', 'password': 'Strong-Pass-8812',
                                                         'first_name': 'Yangi', 'last_name': 'Foydalanuvchi', 'role': 'admin'}),
         dict(method='POST', path=f'{A}/login', data={'email': 'new.user@golden.test', 'password': 'Strong-Pass-8812'}),
         dict(method='POST', path=f'{A}/signup', data={'email': 'NEW.USER@golden.test', 'password': 'Strong-Pass-8812'}),
         dict(method='POST', path=f'{A}/signup', data={'email': 'bad', 'password': 'Strong-Pass-8812'}),
         dict(method='POST', path=f'{A}/signup', data={'password': 'Strong-Pass-8812'}),
         dict(method='POST', path=f'{A}/signup', data={'email': 'weak@golden.test', 'password': '123'}),
         dict(method='POST', path=f'{A}/signup', data={'email': 'teacher13@golden.test', 'password': 'Strong-Pass-8812'}),
         get(f'{C}/oqituvchilar/'))
scenario('auth_change_password',
         dict(method='POST', path=f'{A}/login', data={'email': 'teacher@golden.test', 'password': 'Golden-Pass-1!'},
              save={'access': 'access'}),
         dict(method='POST', path=f'{A}/change-password', data={'old_password': 'x', 'new_password': 'Another-Pass-77'}, bearer='$access'),
         dict(method='POST', path=f'{A}/change-password', data={'old_password': 'Golden-Pass-1!'}, bearer='$access'),
         dict(method='POST', path=f'{A}/change-password', data={'old_password': 'Golden-Pass-1!', 'new_password': '123'}, bearer='$access'),
         dict(method='POST', path=f'{A}/change-password', data={'old_password': 'Golden-Pass-1!', 'new_password': 'Another-Pass-77'}, bearer='$access'),
         dict(method='POST', path=f'{A}/login', data={'email': 'teacher@golden.test', 'password': 'Another-Pass-77'}),
         dict(method='POST', path=f'{A}/change-password', data={}, actor=None))
scenario('auth_reset_password',
         dict(method='POST', path=f'{A}/reset-password', data={'user_id': U_TEACHER, 'new_password': 'Reset-Pass-4455'}, actor=None),
         dict(method='POST', path=f'{A}/reset-password', data={'user_id': U_TEACHER, 'new_password': 'Reset-Pass-4455'}, actor='teacher'),
         dict(method='POST', path=f'{A}/reset-password', data={'user_id': U_TEACHER, 'new_password': 'Reset-Pass-4455'}, actor='super'),
         dict(method='POST', path=f'{A}/reset-password', data={'username': 'email_teacher2', 'new_password': 'Reset-Pass-4456'}, actor='admin_group'),
         dict(method='POST', path=f'{A}/reset-password', data={'email': 'DEKAN@golden.test', 'new_password': 'Reset-Pass-4457'}, actor='super'),
         dict(method='POST', path=f'{A}/reset-password', data={'user_id': 99999, 'new_password': 'Reset-Pass-4455'}, actor='super'),
         dict(method='POST', path=f'{A}/reset-password', data={'user_id': U_TEACHER, 'new_password': '1'}, actor='super'),
         dict(method='POST', path=f'{A}/reset-password', data={'new_password': 'Reset-Pass-4455'}, actor='super'),
         dict(method='POST', path=f'{A}/login', data={'email': 'teacher@golden.test', 'password': 'Reset-Pass-4455'}),
         dict(method='POST', path=f'{A}/login', data={'email': 'dekan@golden.test', 'password': 'Reset-Pass-4457'}))

# ---------------------------------------------------------------- mutations
scenario('otm_crud',
         post(f'{C}/otm/', {'name': 'Yangi OTM', 'short_name': 'YO'}),
         post(f'{C}/otm/', {'short_name': 'X'}),
         patch(f'{C}/otm/{OTM2}/', {'short_name': 'ADU-2'}),
         put(f'{C}/otm/{OTM2}/', {'nomi': 'Faqat nomi'}),
         put(f'{C}/otm/{OTM2}/', {'name': 'Andijon DU', 'short_name': 'ADU'}),
         get(f'{C}/otm/'))
scenario('otm_delete_cascade',
         delete(f'{C}/otm/{OTM2}/'), get(f'{C}/otm/'), get(f'{C}/fakultetlar/'), get(f'{C}/kafedralar/'),
         get(f'{C}/fanlar/?kafedraId={DEP2}'), get(f'{C}/guruhlar/'), get(f'{C}/dl-md/'), get(f'{C}/oqituvchilar/'),
         get(f'{C}/rejalar/'), get(f'{C}/kafedra-yuklama/?kafedraId={DEP2}'), get(f'{C}/topshiriqlar/'),
         delete(f'{C}/otm/{OTM2}/'))
scenario('hierarchy_post',
         post(f'{C}/otm/hierarchy/', {'otmNomi': 'Samarqand DU', 'otmQisqaNomi': 'SamDU', 'fakultetNomi': 'Tarix',
                                      'kafedraNomi': 'Jahon tarixi', 'kafedraYillikYuklama': 900}),
         post(f'{C}/otm/hierarchy/', {'otmNomi': 'Samarqand DU', 'fakultetNomi': 'Tarix', 'kafedraNomi': 'Jahon tarixi'}),
         post(f'{C}/otm/hierarchy/', {'otmNomi': 'Samarqand DU', 'fakultetNomi': 'Tarix', 'kafedraNomi': 'Ozbekiston tarixi'}),
         post(f'{C}/otm/hierarchy/', {'otmNomi': 'X'}),
         get(f'{C}/otm/hierarchy/'))
scenario('fakultet_crud',
         post(f'{C}/fakultetlar/', {'nomi': 'Nomsiz', 'otmId': OTM1}),
         post(f'{C}/fakultetlar/', {'name': 'Iqtisodiyot', 'otmId': OTM1}),
         post(f'{C}/fakultetlar/', {'name': 'Otm siz'}),
         post(f'{C}/fakultetlar/', {'name': 'Xato otm', 'otmId': 999}),
         post(f'{C}/fakultetlar/', {'name': 'Xato otm', 'otm': 'abc'}),
         put(f'{C}/fakultetlar/{FAC2}/', {'nomi': 'Fizika'}),
         patch(f'{C}/fakultetlar/{FAC2}/', {'name': 'Fizika', 'dean': TA}),
         delete(f'{C}/fakultetlar/{FAC2}/'), get(f'{C}/fakultetlar/'), get(f'{C}/kafedralar/'))
scenario('kafedra_crud',
         post(f'{C}/kafedralar/', {'name': 'Yangi kafedra', 'fakultetId': FAC1}),
         post(f'{C}/kafedralar/', {'nomi': 'Nomsiz', 'yillikYuklama': 100, 'fakultetId': FAC1}),
         post(f'{C}/kafedralar/', {'name': 'Fakultetsiz'}),
         patch(f'{C}/kafedralar/{DEP3}/', {'name': 'Geometriya va topologiya', 'fakultetId': FAC2}),
         patch(f'{C}/kafedralar/{DEP3}/', {'teachers': [TC, TA]}),
         patch(f'{C}/kafedralar/{DEP3}/', {'teachers': [999]}),
         put(f'{C}/kafedralar/{DEP3}/', {'nomi': 'X', 'yillikYuklama': 5}),
         patch(f'{C}/kafedralar/{DEP3}/', {'yillik_yuklama': 777, 'yuklama_data': {'b': 1, 'a': [1, [2, 3]]}}),
         get(f'{C}/kafedralar/{DEP3}/'),
         delete(f'{C}/kafedralar/{DEP3}/'), get(f'{C}/kafedralar/'))
scenario('guruh_crud',
         post(f'{C}/guruhlar/', {'name': 'NEW-1', 'department': DEP1, 'course': 'course_2', 'program_type': 'bachelor',
                                 'study_format': 'full_time', 'study_language': 'uz', 'oquv_yili': '2026-2027', 'students': 30}),
         post(f'{C}/guruhlar/', {'name': 'BAD', 'course': 'course_9'}),
         put(f'{C}/guruhlar/{G1}/', {'name': 'MT-21a', 'department': DEP1, 'course': 'course_3', 'program_type': 'bachelor',
                                     'study_format': 'full_time', 'study_language': 'uz', 'oquv_yili': '2026-2027', 'students': 26}),
         delete(f'{C}/guruhlar/{G2}/'), get(f'{C}/guruhlar/'), get(f'{C}/kafedra-yuklama/?kafedraId={DEP2}'))
scenario('fan_crud',
         post(f'{C}/fanlar/', {'name': 'Yangi fan', 'department': DEP2, 'course': 'course_2', 'program_type': 'bachelor',
                               'study_format': 'full_time', 'semester': 'semester_3', 'study_language': 'ru',
                               'study_languages': 'ru,en', 'maruza_hours': 10, 'amaliyot_hours': 20,
                               'laboratoriya_hours': 0, 'seminar_hours': 0, 'hours': 30}),
         post(f'{C}/fanlar/', {'name': 'Manfiy', 'maruza_hours': -1}),
         put(f'{C}/fanlar/{SUBJ_GEO}/', {'name': 'Geometriya asoslari II', 'department': DEP2, 'hours': 44}),
         patch(f'{C}/fanlar/{SUBJ_GEO}/', {'semester': 'semester_5'}),
         delete(f'{C}/fanlar/{SUBJ_ALG}/'), get(f'{C}/fanlar/?kafedraId={DEP2}'), get(f'{C}/topshiriqlar/?rejaId={PLAN_A}'),
         get(f'{C}/kafedra-yuklama/?kafedraId={DEP2}'))
scenario('fan_duplicate_name', post(f'{C}/fanlar/', {'name': 'CHIZIQLI ALGEBRA', 'department': DEP2}))
scenario('oqituvchi_crud',
         post(f'{C}/oqituvchilar/', {'full_name': 'Yangi Oqituvchi', 'position': 'teacher', 'degree': 'master',
                                     'academic_title': 'none', 'speciality': 'other', 'rate': 'rate_1',
                                     'email': 'yangi@golden.test', 'phone_number': '+998901234567'}),
         post(f'{C}/oqituvchilar/', {'full_name': 'Xato', 'email': 'not-email', 'rate': 'rate_9'}),
         put(f'{C}/oqituvchilar/{TC}/', {'full_name': 'Karimova Dilnoza Aliyevna', 'position': 'assistant',
                                         'degree': 'bachelor', 'academic_title': 'none', 'speciality': 'other',
                                         'rate': 'rate_0_25', 'email': '', 'phone_number': ''}),
         patch(f'{C}/oqituvchilar/{TC}/', {'rate': 'rate_1'}),
         delete(f'{C}/oqituvchilar/{TB}/'), get(f'{C}/kafedralar/{DEP2}/'), get(f'{C}/fakultetlar/{FAC2}/'),
         get(f'{C}/rejalar/'), get(f'{C}/dl-md/'), get(f'{C}/oqituvchilar/'))
scenario('oqituvchi_duplicate_email', post(f'{C}/oqituvchilar/', {'full_name': 'Dublikat', 'email': 'TEACHER@golden.test'}))
scenario('reja_crud',
         post(f'{C}/rejalar/', {'oqituvchiId': TC, 'oquvYiliNomi': '2026-2027', 'departmentId': DEP2}),
         post(f'{C}/rejalar/', {'oqituvchiId': TC, 'oquvYiliNomi': '2026-2027', 'departmentId': DEP2}),
         post(f'{C}/rejalar/', {'oqituvchiId': T13, 'oquvYiliNomi': '2025-2026', 'jamiSoat': 15}),
         get(f'{C}/rejalar/'), get(f'{C}/tasdiqlash/'), get(f'{C}/topshiriqlar/'))
scenario('reja_patch_sync',
         patch(f'{C}/rejalar/{PLAN_A}/', {'data': {'stavka': 'rate_0_5', 'variants': {'rate_0_5': {
             'fanlar': [
                 {'id': f'lesson:{SUBJ_ALG}:kuzgi:1:amaliyot:1', 'subjectId': str(SUBJ_ALG), 'nomi': 'Amaliyot: Chiziqli algebra',
                  'soat': 15.5, 'semestr': 'kuzgi', 'lessonType': 'amaliyot', 'groupIndex': 1, 'groupCount': 2},
                 {'id': 'lesson:x:bahorgi:2:maruza', 'nomi': 'Sintetik', 'soat': 40, 'semestr': 'bahorgi'},
                 {'id': str(SUBJ_GEO), 'nomi': 'Eski format', 'soat': 0},
             ],
             'doc': {'oquvIshlari': [{'id': 'r1', 'jami': '55.5'}, {'id': 'dlmd-9', 'jami': '84'}]},
         }}}}),
         get(f'{C}/rejalar/{PLAN_A}/'), get(f'{C}/topshiriqlar/?rejaId={PLAN_A}'), get('/api/dashboard/stats/'),
         get('/api/teacher/dashboard/', actor='teacher'),
         patch(f'{C}/rejalar/{PLAN_A}/', {'jamiSoat': 140, 'status': 'tasdiqlangan'}),
         patch(f'{C}/rejalar/{PLAN_B}/', {'oqituvchiId': TA, 'oquvYiliNomi': '2026-2027'}),
         put(f'{C}/rejalar/{PLAN_B}/', {'oquvYiliNomi': '2024-2025'}),
         get(f'{C}/rejalar/{PLAN_B}/'))
scenario('reja_delete',
         delete(f'{C}/rejalar/{PLAN_A}/'), get(f'{C}/topshiriqlar/'), get(f'{C}/tasdiqlash/'), get('/api/dashboard/stats/'),
         get('/api/teacher/dashboard/', actor='teacher'))
scenario('dlmd_crud',
         post(f'{C}/dl-md/', {'kafedraId': DEP2, 'oqituvchiId': TB, 'tur': 'md', 'talimShakli': 'magistr',
                              'semestr': 'kuzgi', 'talabaSoni': 2, 'oquvYili': '2026-2027'}),
         post(f'{C}/dl-md/', {'kafedraId': DEP2, 'tur': 'dl'}),
         put(f'{C}/dl-md/{DLMD_A}/', {'talabaSoni': 5}),
         patch(f'{C}/dl-md/{DLMD_A}/', {'tur': 'md'}),
         delete(f'{C}/dl-md/{DLMD_B}/'), get(f'{C}/dl-md/'), get('/api/dashboard/stats/'),
         get('/api/teacher/dashboard/', actor='teacher'))
scenario('tasdiqlash_crud',
         post(f'{C}/tasdiqlash/', {'rejaId': REJA19, 'bosqich': 'rektor', 'holat': 'tasdiqlangan', 'izoh': None}),
         post(f'{C}/tasdiqlash/', {'rejaId': REJA19, 'bosqich': 'kafedra'}),
         get(f'{C}/tasdiqlash/?rejaId={REJA19}'), get(f'{C}/rejalar/{REJA19}/'), get('/api/dashboard/stats/'))
scenario('normativ_crud',
         post(f'{C}/normativlar/', {'yuklamaTuriId': WT_FAN, 'otmProfil': 'barcha', 'koeffitsient': 1.5, 'limitMin': 5,
                                    'limitMax': 50, 'amalBoshi': '2026-09-01', 'amalOxiri': None, 'izoh': None}),
         post(f'{C}/normativlar/', {'yuklamaTuriId': WT_MARUZA, 'otmProfil': 'barcha', 'koeffitsient': 2,
                                    'amalBoshi': '2026-06-01'}),
         post(f'{C}/normativlar/', {'yuklamaTuriId': WT_MARUZA, 'otmProfil': 'barcha', 'koeffitsient': 2,
                                    'amalBoshi': '2026-06-01', 'force': True}),
         post(f'{C}/normativlar/', {'yuklamaTuriId': WT_MARUZA, 'otmProfil': 'umumiy', 'koeffitsient': 1,
                                    'limitMin': 10, 'limitMax': 5, 'amalBoshi': '2026-06-01'}),
         put(f'{C}/normativlar/{NORM2}/', {'yuklamaTuriId': WT_MARUZA, 'otmProfil': 'tibbiyot', 'koeffitsient': 0.75,
                                           'amalBoshi': '2025-01-01', 'amalOxiri': '2025-06-30', 'izoh': 'Yangilandi'}),
         get(f'{C}/normativlar/?type=normativ&yuklamaTuriId={WT_MARUZA}'),
         get(f'{C}/normativlar/?type=yuklama_turi'),
         delete(f'{C}/normativlar/{NORM1}/'), get(f'{C}/normativlar/'))
scenario('topshiriq_crud',
         post(f'{C}/topshiriqlar/', {'rejaId': PLAN_B, 'yuklamaTuriId': WT_MARUZA, 'fanId': SUBJ_GEO, 'semesterRaqami': 2,
                                     'soat': 12.25, 'formulaInput': {'k': 1}}),
         patch(f'{C}/topshiriqlar/{ASG2}/', {'soat': 7}),
         delete(f'{C}/topshiriqlar/{ASG1}/'), get(f'{C}/topshiriqlar/'))
scenario('fanlar_shakllantir',
         post(f'{C}/fanlar-shakllantir/', {'department_id': DEP1}),
         post(f'{C}/fanlar-shakllantir/', {'departmentId': 999}),
         get(f'{C}/fanlar/?kafedraId={DEP1}&page=1'),
         delete(f'{C}/fanlar-shakllantir/?department_id={DEP2}'),
         delete(f'{C}/fanlar-shakllantir/'),
         get(f'{C}/kafedralar/{DEP2}/'), get(f'{C}/rejalar/'), get(f'{C}/dl-md/'), get(f'{C}/fanlar/?kafedraId={DEP2}'),
         get(f'{C}/kafedra-yuklama/?kafedraId={DEP2}'))
scenario('excel_import',
         dict(method='POST', path=f'{C}/yuklama-excel/', actor='super', format='multipart', data={'$file': True}),
         dict(method='POST', path=f'{C}/yuklama-excel/', actor='super', format='multipart', data={}),
         dict(method='POST', path=f'{C}/yuklama-excel/', actor='super', format='multipart',
              data={'$file': True, 'save': 'true', 'department_id': '999'}),
         dict(method='POST', path=f'{C}/yuklama-excel/', actor='super', format='multipart',
              data={'$file': True, 'save': 'true', 'department_id': str(DEP2)}),
         get(f'{C}/kafedralar/{DEP2}/'), get(f'{C}/fanlar/?kafedraId={DEP2}'),
         get(f'{C}/kafedra-yuklama/?kafedraId={DEP2}'),
         dict(method='POST', path=f'{C}/yuklama-excel/', actor='super', format='multipart',
              data={'$file': True, 'save': 'true', 'department_id': str(DEP2)}),
         get(f'{C}/fanlar/?kafedraId={DEP2}'), get(f'{C}/kafedra-yuklama/?kafedraId={DEP2}'))
scenario('kafedra_yuklama_crud',
         post(f'{C}/kafedra-yuklama/', {'name': 'Qo\'lda', 'department_id': DEP2, 'subject_id': SUBJ_GEO, 'control': 3}),
         get(f'{C}/kafedra-yuklama/?kafedraId={DEP2}'),
         patch(f'{C}/kafedra-yuklama/1/', {'name': 'x'}))
scenario('teacher_lesson_type',
         patch('/api/teacher/dashboard/', {'id': ASG1, 'mashgulotTuri': 'laboratoriya'}, actor='teacher'),
         patch('/api/teacher/dashboard/', {'id': ASG2, 'mashgulotTuri': 'maruza'}, actor='teacher'),
         patch('/api/teacher/dashboard/', {'id': ASG1, 'mashgulotTuri': 'xato'}, actor='teacher'),
         patch('/api/teacher/dashboard/', {'id': ASG1, 'mashgulotTuri': 'maruza'}, actor='teacher2'),
         get('/api/teacher/dashboard/', actor='teacher'))
scenario('teacher_personal_plan',
         patch('/api/teacher/dashboard/', {'action': 'save_personal_plan', 'rejaId': PLAN_A, 'activeStavka': 'rate_0_5',
                                           'variants': {'rate_0_5': {'uslubiy': [{'id': 'u2', 'nomi': 'Yangi'}], 'ilmiy': [],
                                                                     'ustozShogird': [], 'reyting': {'x': '2'},
                                                                     'dekan': 'Yangi Dekan', 'oquvIshlari': []}}},
               actor='teacher'),
         patch('/api/teacher/dashboard/', {'action': 'save_personal_plan', 'rejaId': PLAN_A, 'activeStavka': 'rate_1',
                                           'variants': {'rate_1': {'uslubiy': [], 'ilmiy': [], 'ustozShogird': [],
                                                                   'reyting': {}}}}, actor='teacher'),
         patch('/api/teacher/dashboard/', {'action': 'save_personal_plan', 'rejaId': PLAN_A, 'activeStavka': 'rate_0_5',
                                           'variants': {'rate_0_5': {'uslubiy': 'x'}}}, actor='teacher'),
         patch('/api/teacher/dashboard/', {'action': 'save_personal_plan', 'rejaId': PLAN_B, 'activeStavka': 'rate_1',
                                           'variants': {'rate_1': {'uslubiy': [], 'ilmiy': [], 'ustozShogird': [],
                                                                   'reyting': {}}}}, actor='teacher2'),
         get(f'/api/teacher/dashboard/?document=1&rejaId={PLAN_A}', actor='teacher'),
         get(f'/api/teacher/dashboard/?document=1&rejaId={PLAN_B}', actor='teacher2'),
         get('/api/teacher/dashboard/', actor='teacher2'))
