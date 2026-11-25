"""Admin boshqaruv paneli: butun tizim holati (tuzilma, foydalanuvchilar, yuklama, tasdiqlash, muammolar).

GET /api/dashboard/rol/tizim/?oquvYili=&otmId=&fakultetId=&kafedraId=   — faqat administrator
"""
from decimal import Decimal

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from config.permissions import is_application_admin

ROLLAR = ('oqituvchi', 'kafedra_mudiri', 'dekan', 'oquv_bolimi', 'admin')
LIMIT = 8  # har bir muammo uchun namuna sifatida qaytariladigan nomlar soni


def _int(v):
    return int(v) if v not in (None, '') and str(v).isdigit() else None


def _problem(key, items, href):
    return {'key': key, 'soni': len(items), 'items': items[:LIMIT], 'href': href}


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def tizim_holati(request):
    from apps.academics.models import Group, Talaba
    from apps.accounts.models import User
    from apps.departments.models import OTM, Department, Faculty
    from apps.teachers.models import Teacher
    from apps.workload.approval_flow import next_approval
    from apps.workload.models import Reja
    from apps.workload.services import reja_fan_hours
    from config.dashboard_urls import _position_norm
    from config.users_admin import _Index, _row

    if not is_application_admin(request.user):
        return Response({'detail': 'Bu sahifa administrator uchun.'}, status=status.HTTP_403_FORBIDDEN)

    p = request.query_params
    oquv = p.get('oquvYili') or ''
    otm_id, fak_id, kaf_id = _int(p.get('otmId')), _int(p.get('fakultetId')), _int(p.get('kafedraId'))

    otms = list(OTM.objects.all())
    faculties = [f for f in Faculty.objects.all() if otm_id is None or f.otm_id == otm_id]
    if fak_id is not None:
        faculties = [f for f in faculties if f.id == fak_id]
    fac_ids = {f.id for f in faculties}
    fac_by_id = {f.id: f for f in faculties}
    deps = [d for d in Department.objects.all() if d.faculty_id in fac_ids]
    if kaf_id is not None:
        deps = [d for d in deps if d.id == kaf_id]
    dep_ids = {d.id for d in deps}
    filtered = otm_id is not None or fak_id is not None or kaf_id is not None

    idx = _Index()
    teachers = list(Teacher.objects.all())
    if filtered:
        teachers = [t for t in teachers if set(idx.members.get(t.id, [])) & dep_ids]
    teacher_ids = {t.id for t in teachers}

    groups = [g for g in Group.objects.all() if g.department_id in dep_ids]
    group_ids = {g.id for g in groups}
    talaba_soni = {}
    for t in Talaba.objects.all():
        if t.group_id in group_ids:
            talaba_soni[t.group_id] = talaba_soni.get(t.group_id, 0) + 1

    # --- Foydalanuvchilar: rollar va kirish hisoblari
    users = list(User.objects.all())
    by_id = {u.id: u for u in users}
    by_email = {(u.email or '').lower(): u for u in users if u.email}
    rows, shown = [], set()
    for t in teachers:
        user = by_id.get(t.user_id) if t.user_id else by_email.get((t.email or '').lower())
        if user is not None:
            shown.add(user.id)
        rows.append(_row(t, user, idx))
    if not filtered:
        rows += [_row(None, u, idx) for u in users if u.id not in shown]
    rollar = {r: 0 for r in ROLLAR}
    for r in rows:
        rollar[r['rol']] = rollar.get(r['rol'], 0) + 1
    hisobsiz = [r for r in rows if not r['hisob']]
    bloklangan = [r for r in rows if r['hisob'] and not r['faol']]

    # --- Yuklama va rejalar
    rejalar = [r for r in Reja.objects.all() if (not oquv or r.oquv_yili == oquv) and
               (not filtered or r.department_id in dep_ids)]
    dep_faculty = {d.id: d.faculty_id for d in Department.objects.all()}
    teacher_by_id = {t.id: t for t in Teacher.objects.all()}
    holat = {'kam': 0, 'meyorda': 0, 'kop': 0}
    fak_yuklama = {f.id: {'id': f.id, 'nomi': f.name, 'kam': 0, 'meyorda': 0, 'kop': 0} for f in faculties}
    voronka = {'loyiha': 0, 'kafedra': 0, 'dekan': 0, 'oquv_bolimi': 0, 'tasdiqlangan': 0, 'rad_etilgan': 0}
    shakllangan = set()
    for r in rejalar:
        t = teacher_by_id.get(r.teacher_id)
        soat = reja_fan_hours(r)
        if soat > 0 and r.teacher_id:
            shakllangan.add(r.teacher_id)
            mn, mx = _position_norm(t.position if t else '', r.oquv_yili, t.rate if t else 'rate_1')
            level = 'kam' if soat < Decimal(mn) else ('kop' if soat > Decimal(mx) + 10 else 'meyorda')
            holat[level] += 1
            fak = fak_yuklama.get(dep_faculty.get(r.department_id))
            if fak:
                fak[level] += 1
        if r.status == 'tekshiruvda':
            nxt = next_approval(r)
            voronka[nxt.stage if nxt else 'kafedra'] = voronka.get(nxt.stage if nxt else 'kafedra', 0) + 1
        elif r.status in voronka:
            voronka[r.status] += 1
    jami_rejalar = len(rejalar)

    # --- Tizim nazorati: tuzatilishi kerak bo'lgan joylar
    dep_teachers = {d.id: [tid for tid in d.teachers._ids()] for d in deps}
    named = lambda objs: [{'id': o.id, 'nomi': o.name} for o in objs]  # noqa: E731
    muammolar = [
        _problem('dekansiz_fakultet', named([f for f in faculties if not f.dean_id]), '/dashboard/admin/foydalanuvchilar'),
        _problem('mudirsiz_kafedra', named([d for d in deps if not d.head_of_department_id]), '/dashboard/admin/foydalanuvchilar'),
        _problem('hisobsiz_xodim', [{'id': r['id'], 'nomi': r['fio']} for r in hisobsiz], '/dashboard/admin/foydalanuvchilar'),
        _problem('bloklangan', [{'id': r['id'], 'nomi': r['fio']} for r in bloklangan], '/dashboard/admin/foydalanuvchilar'),
        _problem('yuklamasiz_kafedra', named([d for d in deps if not d.yillik_yuklama]), '/dashboard/admin/yuklama-shakllantirish'),
        _problem('oqituvchisiz_kafedra', named([d for d in deps if not dep_teachers.get(d.id)]), '/dashboard/admin/oqituvchilar'),
        _problem('talabasiz_guruh', named([g for g in groups if not talaba_soni.get(g.id)]), '/dashboard/admin/guruhlar'),
        _problem('sardorsiz_guruh', named([g for g in groups if not g.sardor_id or not g.murabbiy_id]), '/dashboard/admin/guruhlar'),
    ]

    return Response({
        'tuzilma': {
            'otm': len(otms) if otm_id is None else 1,
            'fakultet': len(faculties),
            'kafedra': len(deps),
            'oqituvchi': len(teacher_ids),
            'guruh': len(groups),
            'talaba': sum(talaba_soni.values()),
        },
        'hisoblar': {'bor': len(rows) - len(hisobsiz), 'yoq': len(hisobsiz), 'bloklangan': len(bloklangan)},
        'rollar': rollar,
        'yuklama': {
            'jamiOqituvchi': len(teacher_ids),
            'shakllangan': len(shakllangan & teacher_ids) if filtered else len(shakllangan),
            **holat,
            'fakultetlar': sorted(fak_yuklama.values(), key=lambda f: f['nomi']),
        },
        'rejalar': {'jami': jami_rejalar, 'voronka': voronka},
        'muammolar': muammolar,
        'filtr': {
            'otmlar': [{'id': o.id, 'nomi': o.short_name or o.name} for o in otms],
            'fakultetlar': [{'id': f.id, 'nomi': f.name, 'otmId': f.otm_id} for f in Faculty.objects.all()],
            'kafedralar': [{'id': d.id, 'nomi': d.name, 'fakultetId': d.faculty_id} for d in Department.objects.all()],
        },
    })
