"""O'quv bo'limi boshqaruv paneli: butun OTM bo'yicha rejalar, yuklama, ijro va ilmiy salohiyat.

GET /api/dashboard/rol/oquv-bolimi/?oquvYili=&otmId=&fakultetId=&kafedraId=
Ruxsat: o'quv bo'limi (faqat o'z OTMi) va administrator.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.roles import user_scope

HAFTALAR = 10          # tasdiqlanish dinamikasi: oxirgi necha hafta
UZOQ_KUN = 7           # bosqichda shuncha kundan ortiq turgan reja "uzoq turgan" hisoblanadi
OYLAR = [9, 10, 11, 12, 1, 2, 3, 4, 5, 6]   # o'quv yili: sentyabr — iyun
DEGREES = ('dsc', 'phd', 'master', 'bachelor')


def _int(v):
    return int(v) if v not in (None, '') and str(v).isdigit() else None


def _aware(value):
    """date/datetime -> timezone-aware datetime (taqqoslash uchun)."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        value = datetime.combine(value, time.min)
    return value if timezone.is_aware(value) else timezone.make_aware(value)


def _start_year(oquv):
    head = (oquv or '').split('-')[0]
    return int(head) if head.isdigit() else None


def _oquv_yillari(dep_ids):
    """Filtr uchun o'quv yillari: tizimdagi o'quv yillari va shu hududdagi rejalar yillari (yangisi birinchi)."""
    from apps.workload.models import AcademicYear, Reja
    years = {y.name for y in AcademicYear.objects.all() if y.name}
    years |= {r.oquv_yili for r in Reja.objects.all() if r.oquv_yili and r.department_id in dep_ids}
    return sorted(years, reverse=True)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def oquv_bolimi_panel(request):
    from apps.departments.models import OTM, Department, Faculty
    from apps.teachers.models import Teacher
    from apps.teachers.views import teacher_departments
    from apps.workload.approval_flow import next_approval
    from apps.workload.bajarilish import plan_rows
    from apps.workload.models import Approval, IshDalili, Reja
    from apps.workload.services import reja_fan_hours
    from config.dashboard_urls import _position_norm

    scope = user_scope(request.user)
    if not (scope.is_admin or scope.role == 'oquv_bolimi'):
        return Response({'detail': "Bu sahifa o'quv bo'limi uchun."}, status=status.HTTP_403_FORBIDDEN)

    p = request.query_params
    oquv = p.get('oquvYili') or ''
    otm_id, fak_id, kaf_id = _int(p.get('otmId')), _int(p.get('fakultetId')), _int(p.get('kafedraId'))

    # --- Hudud: OTM / fakultet / kafedra filtri
    # O'quv bo'limi faqat o'z OTMini ko'radi (admin — hammasini)
    otms = [o for o in OTM.objects.all() if scope.is_admin or o.id in scope.otm_ids]
    allowed_otm = {o.id for o in otms}
    all_faculties = [f for f in Faculty.objects.all() if f.otm_id in allowed_otm]
    allowed_fac = {f.id for f in all_faculties}
    all_deps = [d for d in Department.objects.all() if d.faculty_id in allowed_fac]
    faculties = [f for f in all_faculties if (otm_id is None or f.otm_id == otm_id) and (fak_id is None or f.id == fak_id)]
    fac_ids = {f.id for f in faculties}
    deps = [d for d in all_deps if d.faculty_id in fac_ids and (kaf_id is None or d.id == kaf_id)]
    dep_ids = {d.id for d in deps}
    dep_faculty = {d.id: d.faculty_id for d in all_deps}
    fac_otm = {f.id: f.otm_id for f in all_faculties}

    mapping = teacher_departments()
    teachers = [t for t in Teacher.objects.all() if not getattr(t, 'faqat_xodim', False)
                and set(mapping.get(t.id, [])) & dep_ids]
    rejalar = [r for r in Reja.objects.select_related('teacher').all()
               if r.department_id in dep_ids and (not oquv or r.oquv_yili == oquv)]
    reja_ids = {r.id for r in rejalar}

    approvals = {}
    for a in Approval.objects.all():
        if a.reja_id in reja_ids:
            approvals.setdefault(a.reja_id, {})[a.stage] = a

    # --- Kesim: filtr tanlanmasa — OTMlar, OTM tanlansa — fakultetlar, fakultet tanlansa — kafedralar,
    #     kafedra tanlansa — shu kafedra o'qituvchilari
    if kaf_id is not None:
        kesim_turi = 'oqituvchi'
        kesim = {t.id: {'id': t.id, 'nomi': t.full_name, 'qisqa': (t.full_name or '').split(' ')[0]} for t in teachers}
        kesim_of = None
    elif fak_id is not None:
        kesim_turi = 'kafedra'
        kesim = {d.id: {'id': d.id, 'nomi': d.name, 'qisqa': ''} for d in deps}
        kesim_of = lambda dep: dep  # noqa: E731
    elif otm_id is not None or len(otms) <= 1:
        kesim_turi = 'fakultet'
        kesim = {f.id: {'id': f.id, 'nomi': f.name, 'qisqa': ''} for f in faculties}
        kesim_of = lambda dep: dep_faculty.get(dep)  # noqa: E731
    else:
        kesim_turi = 'otm'
        kesim = {o.id: {'id': o.id, 'nomi': o.name, 'qisqa': o.short_name or ''} for o in otms}
        kesim_of = lambda dep: fac_otm.get(dep_faculty.get(dep))  # noqa: E731
    def _bosh():
        return {'kam': 0, 'meyorda': 0, 'kop': 0, 'oqituvchi': 0, 'ilmiy': 0, 'rejalar': 0, 'tasdiqlangan': 0,
                'menda': 0, 'ijroQator': 0, 'ijroQabul': 0,
                'soatReja': 0.0, 'soatMeyor': 0.0, 'soatOrtiqcha': 0.0, 'soatKam': 0.0}

    for row in kesim.values():
        row.update(_bosh())
    # Reyting har doim kafedralar bo'yicha
    reyting = {d.id: {'id': d.id, 'nomi': d.name, **_bosh()} for d in deps}
    for t in teachers:
        own = {d for d in mapping.get(t.id, []) if d in dep_ids}
        keys = {t.id} if kesim_of is None else {kesim_of(d) for d in own}
        ilmiy = t.degree in ('dsc', 'phd')
        for key in keys:
            if key in kesim:
                kesim[key]['oqituvchi'] += 1
                kesim[key]['ilmiy'] += ilmiy
        for d in own:
            reyting[d]['oqituvchi'] += 1
            reyting[d]['ilmiy'] += ilmiy

    def kesim_key(reja):
        if kesim_of is None:
            return reja.teacher.id if reja.teacher else None
        return kesim_of(reja.department_id)

    # --- Dalillar: qabul qilingan ishlar (ijro) va tekshiruvni kutayotganlar
    accepted_at = {}   # (reja_id, bolim, qator_id) -> qabul qilingan sana
    dalil_kutilmoqda = 0
    for d in IshDalili.objects.all():
        if d.reja_id not in reja_ids:
            continue
        if d.holat == 'oquv_bolimida':
            dalil_kutilmoqda += 1
        if d.holat == 'qabul_qilindi':
            sana = next((_aware(x.get('sana')) for x in reversed(d.tekshiruvlar or [])
                         if x.get('qaror') == 'qabul'), None) or _aware(d.edited_at)
            key = (d.reja_id, d.bolim, str(d.qator_id))
            if key not in accepted_at or sana < accepted_at[key]:
                accepted_at[key] = sana

    now = timezone.now()
    holat = {'tasdiqlangan': 0, 'menda': 0, 'mudirda': 0, 'dekanda': 0, 'yuborilmagan': 0, 'rad_etilgan': 0}
    yuk = {'kam': 0, 'meyorda': 0, 'kop': 0}
    uzoq, kam_list, kop_list = [], [], []
    yuborilgan_sana, tasdiq_sana = [], []
    jami_qator = 0
    soat_jami = {'reja': 0.0, 'meyor': 0.0, 'ortiqcha': 0.0, 'kam': 0.0}
    for r in rejalar:
        k = kesim.get(kesim_key(r))
        rk = reyting.get(r.department_id)
        targets = [x for x in (k, rk) if x]
        stages = approvals.get(r.id, {})
        for x in targets:
            x['rejalar'] += 1
        # Holat
        if r.status == 'tasdiqlangan':
            holat['tasdiqlangan'] += 1
            for x in targets:
                x['tasdiqlangan'] += 1
        elif r.status == 'rad_etilgan':
            holat['rad_etilgan'] += 1
        elif r.status == 'tekshiruvda':
            nxt = next_approval(r)
            stage = nxt.stage if nxt else 'kafedra'
            key = {'kafedra': 'mudirda', 'dekan': 'dekanda'}.get(stage, 'menda')
            holat[key] += 1
            if key == 'menda' and k:
                k['menda'] += 1
            # Joriy bosqichga qachon kelgan: oldingi bosqich qarori yoki yuborilgan vaqt
            prev = [stages[s].acted_at for s in ('kafedra', 'dekan') if s in stages and stages[s].acted_at
                    and s != stage and stages[s].state == 'tasdiqlangan']
            since = _aware(max(prev)) if prev else _aware(r.yuborilgan_at or r.edited_at)
            kun = (now - since).days if since else 0
            if kun > UZOQ_KUN:
                uzoq.append({'id': r.id, 'nomi': r.teacher.full_name if r.teacher else '', 'kun': kun, 'bosqich': stage})
        else:
            holat['yuborilmagan'] += 1
        # Yuklama me'yori
        t = r.teacher
        soat = reja_fan_hours(r)
        if soat > 0:
            mn, mx = _position_norm(t.position if t else '', r.oquv_yili, t.rate if t else 'rate_1')
            level = 'kam' if soat < Decimal(mn) else ('kop' if soat > Decimal(mx) + 10 else 'meyorda')
            yuk[level] += 1
            for x in targets:
                x[level] += 1
            # Soatlar: rejalashtirilgan, me'yor (quyi chegara), me'yordan ortiq (soatbay) va yetishmaydigan
            s_reja, s_min, s_max = float(soat), float(mn), float(mx)
            ortiq, kam = max(0.0, s_reja - s_max), max(0.0, s_min - s_reja)
            for bucket, prefix in [(soat_jami, '')] + [(x, 'soat') for x in targets]:
                for name, val in (('reja', s_reja), ('meyor', s_min), ('ortiqcha', ortiq), ('kam', kam)):
                    key = f'{prefix}{name.capitalize()}' if prefix else name
                    bucket[key] += val
            item = {'id': r.id, 'nomi': t.full_name if t else '', 'soat': float(soat), 'min': mn, 'max': mx}
            (kam_list if level == 'kam' else kop_list if level == 'kop' else []).append(item)
        # Ijro
        rows = plan_rows(r)
        jami_qator += len(rows)
        qabul = sum(1 for row in rows if (r.id, row['bolim'], row['id']) in accepted_at)
        for x in targets:
            x['ijroQator'] += len(rows)
            x['ijroQabul'] += qabul
        # Dinamika uchun sanalar
        if r.status != 'loyiha':
            sent = r.yuborilgan_at or min((a.acted_at for a in stages.values() if a.acted_at), default=None) or r.edited_at
            yuborilgan_sana.append(_aware(sent))
        final = stages.get('oquv_bolimi')
        if r.status == 'tasdiqlangan' and final and final.acted_at:
            tasdiq_sana.append(_aware(final.acted_at))

    # --- Haftalik tasdiqlanish dinamikasi (yig'indi)
    today = timezone.localdate()
    week_end = today + timedelta(days=(6 - today.weekday()))
    haftalar = []
    for i in range(HAFTALAR - 1, -1, -1):
        end = week_end - timedelta(weeks=i)
        limit = _aware(datetime.combine(end, time.max))
        haftalar.append({
            'sana': (end - timedelta(days=6)).isoformat(),
            'yuborilgan': sum(1 for s in yuborilgan_sana if s and s <= limit),
            'tasdiqlangan': sum(1 for s in tasdiq_sana if s and s <= limit),
        })

    # --- Oylik ijro dinamikasi (o'quv yili bo'yicha, kelajak oylar — null)
    start_year = _start_year(oquv) or (today.year if today.month >= 9 else today.year - 1)
    oylar = []
    for m in OYLAR:
        y = start_year if m >= 9 else start_year + 1
        last = (date(y + (m == 12), 1 if m == 12 else m + 1, 1) - timedelta(days=1))
        if date(y, m, 1) > today:
            foiz = None
        else:
            limit = _aware(datetime.combine(min(last, today), time.max))
            done = sum(1 for s in accepted_at.values() if s and s <= limit)
            foiz = round(done / jami_qator * 100, 1) if jami_qator else 0.0
        oylar.append({'oy': m, 'yil': y, 'foiz': foiz})

    # --- Ilmiy salohiyat
    salohiyat = {k: 0 for k in DEGREES}
    for t in teachers:
        salohiyat[t.degree if t.degree in salohiyat else 'bachelor'] += 1

    shakllangan = sum(yuk.values())
    jami_qabul = len(accepted_at)
    for row in list(kesim.values()) + list(reyting.values()):
        row['ijroFoiz'] = round(row['ijroQabul'] / row['ijroQator'] * 100, 1) if row['ijroQator'] else 0.0
        for key in ('soatReja', 'soatMeyor', 'soatOrtiqcha', 'soatKam'):
            row[key] = round(row[key], 1)
    # Kafedralar reytingi: tasdiqlangan rejalar 40%, ijro 40%, ilmiy darajalilar 20%
    for row in reyting.values():
        tasdiq = row['tasdiqlangan'] / row['rejalar'] * 100 if row['rejalar'] else 0.0
        ilmiy = row['ilmiy'] / row['oqituvchi'] * 100 if row['oqituvchi'] else 0.0
        row['tasdiqFoiz'] = round(tasdiq, 1)
        row['ilmiyFoiz'] = round(ilmiy, 1)
        row['ball'] = round(0.4 * tasdiq + 0.4 * row['ijroFoiz'] + 0.2 * ilmiy)

    named = lambda items: sorted(items, key=lambda x: x['nomi'])[:8]  # noqa: E731
    muammolar = [
        {'key': 'kam_yuklama', 'soni': len(kam_list), 'items': named(kam_list), 'href': '/dashboard/oquv-bolimi/oqituvchilar'},
        {'key': 'kop_yuklama', 'soni': len(kop_list), 'items': named(kop_list), 'href': '/dashboard/oquv-bolimi/oqituvchilar'},
        {'key': 'uzoq_turgan', 'soni': len(uzoq), 'items': sorted(uzoq, key=lambda x: -x['kun'])[:8],
         'href': '/dashboard/oquv-bolimi/rejalar?holat=tekshiruvda'},
        {'key': 'yuborilmagan', 'soni': holat['yuborilmagan'], 'items': [], 'href': '/dashboard/oquv-bolimi/rejalar?holat=loyiha'},
        {'key': 'dalil_kutilmoqda', 'soni': dalil_kutilmoqda, 'items': [], 'href': '/dashboard/oquv-bolimi/ishlar'},
    ]

    return Response({
        'kpi': {
            'menda': holat['menda'],
            'tasdiqlangan': holat['tasdiqlangan'],
            'jamiReja': len(rejalar),
            'oqituvchi': len(teachers),
            'meyordaFoiz': round(yuk['meyorda'] / shakllangan * 100, 1) if shakllangan else 0.0,
            'shakllangan': shakllangan,
            'ijroFoiz': round(jami_qabul / jami_qator * 100, 1) if jami_qator else 0.0,
            'ijroQabul': jami_qabul,
            'ijroQator': jami_qator,
        },
        'holat': holat,
        'yuklama': yuk,
        'kesimTuri': kesim_turi,
        'kesim': sorted(kesim.values(), key=lambda k: k['nomi']),
        'soatlar': {key: round(val, 1) for key, val in soat_jami.items()},
        'reyting': sorted((r for r in reyting.values() if r['oqituvchi'] or r['rejalar']),
                          key=lambda r: (-r['ball'], r['nomi'])),
        'haftalar': haftalar,
        'oylar': oylar,
        'salohiyat': salohiyat,
        'muammolar': muammolar,
        'filtr': {
            'oquvYillari': _oquv_yillari(dep_ids),
            'otmlar': [{'id': o.id, 'nomi': o.short_name or o.name} for o in otms],
            'fakultetlar': [{'id': f.id, 'nomi': f.name, 'otmId': f.otm_id} for f in all_faculties],
            'kafedralar': [{'id': d.id, 'nomi': d.name, 'fakultetId': d.faculty_id} for d in all_deps],
        },
    })
