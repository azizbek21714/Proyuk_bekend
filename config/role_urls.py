"""Rollar bilan bog'liq API: hudud (scope), rol berish, xabarlar, rol dashboardi."""
from decimal import Decimal

from django.urls import path
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import User, Xabar
from apps.accounts.roles import user_scope
from config import fakultet_views, oquv_bolimi_views, tizim_views
from config.permissions import IsApplicationAdmin, scope_filter


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def scope(request):
    """Joriy foydalanuvchining roli va hududi (kabinetni tanlash va menyu uchun)."""
    return Response(user_scope(request.user).as_dict())


@api_view(['GET', 'PATCH'])
@permission_classes([IsApplicationAdmin])
def user_roles(request, user_id):
    """Admin: foydalanuvchiga o'quv bo'limi rolini beradi yoki oladi. body: {oquv_bolimi: bool}"""
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        return Response({'detail': 'Foydalanuvchi topilmadi.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'GET':
        return Response({'id': user.id, 'oquv_bolimi': 'oquv_bolimi' in (user.groups or [])})
    if 'oquv_bolimi' not in request.data:
        return Response({'oquv_bolimi': ['Bu maydon majburiy.']}, status=status.HTTP_400_BAD_REQUEST)
    groups = [g for g in (user.groups or []) if g != 'oquv_bolimi']
    if str(request.data.get('oquv_bolimi')).lower() in ('1', 'true', 'yes', 'ha'):
        groups.append('oquv_bolimi')
    user.groups = groups
    user.save(update_fields=['groups'])
    return Response({'id': user.id, 'oquv_bolimi': 'oquv_bolimi' in groups})


def _xabar(item):
    return {
        'id': item.id, 'matn': item.matn, 'havola': item.havola,
        'oqilgan': item.oqilgan, 'createdAt': item.created_at.isoformat() if item.created_at else None,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def xabarlar(request):
    items = list(Xabar.objects.filter(user=request.user))
    return Response({
        'oqilmagan': sum(1 for x in items if not x.oqilgan),
        'results': [_xabar(x) for x in items[:50]],
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def xabarlar_oqildi(request):
    """body: {ids: [..]} — berilmasa hammasi o'qilgan deb belgilanadi."""
    ids = request.data.get('ids')
    qs = Xabar.objects.filter(user=request.user, oqilgan=False)
    if ids:
        wanted = {int(i) for i in ids if str(i).isdigit()}
        qs = qs.filter_fn(lambda x: x.id in wanted)
    count = 0
    for item in qs:
        item.oqilgan = True
        item.save(update_fields=['oqilgan'])
        count += 1
    return Response({'belgilandi': count})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def rol_dashboard(request):
    """Rahbar rollar uchun hudud bo'yicha statistika va "menga kelgan tasdiqlar"."""
    from apps.teachers.views import teacher_departments
    from apps.teachers.models import Teacher
    from apps.workload.approval_flow import pending_for
    from apps.workload.models import Reja
    from apps.workload.services import reja_fan_hours
    from config.dashboard_urls import _position_norm

    scope_obj = user_scope(request.user)
    if scope_obj.role == 'oqituvchi':
        return Response({'detail': "Bu sahifa rahbarlar uchun."}, status=status.HTTP_403_FORBIDDEN)
    oquv = request.query_params.get('oquvYili')

    mapping = teacher_departments()
    teachers = scope_filter(Teacher.objects.all(), request.user,
                            departments_of=lambda t: mapping.get(t.id, []))
    rejalar = scope_filter(Reja.objects.select_related('teacher', 'department').all(), request.user,
                           departments_of=lambda r: [r.department_id])
    if oquv:
        rejalar = rejalar.filter(oquv_yili=oquv)
    rejalar = list(rejalar)
    teachers_count = teachers.count()
    # ?kafedraId= — bosh sahifadagi kafedra filtri (rahbar ko'radigan hudud ichida)
    kaf = request.query_params.get('kafedraId')
    if kaf and str(kaf).isdigit():
        kaf = int(kaf)
        rejalar = [r for r in rejalar if r.department_id == kaf]
        teachers_count = sum(1 for t in teachers if kaf in mapping.get(t.id, []))

    holatlar = {}
    bar, past = [], 0
    for r in rejalar:
        holatlar[r.status] = holatlar.get(r.status, 0) + 1
        t = r.teacher
        min_norm, max_norm = _position_norm(t.position if t else '', r.oquv_yili, t.rate if t else 'rate_1')
        soat = reja_fan_hours(r)
        if soat < Decimal(min_norm):
            past += 1
        bar.append({'id': str(r.id), 'fio': t.full_name if t else '', 'kafedraId': r.department_id,
                    'jamiSoat': float(soat), 'minNorm': min_norm, 'maxNorm': max_norm, 'status': r.status})

    kutilayotgan = [{
        'rejaId': str(r.id), 'bosqich': a.stage,
        'oqituvchiFio': r.teacher.full_name if r.teacher else '',
        'kafedraNomi': r.department.name if r.department else None,
        'oquvYiliNomi': r.oquv_yili,
        'kunSoni': (timezone.now().date() - (r.edited_at or r.created_at).date()).days,
    } for r, a in pending_for(request.user, rejalar)]

    return Response({
        'scope': scope_obj.as_dict(),
        'stats': {
            'jamiOqituvchilar': teachers_count,
            'jamiRejalar': len(rejalar),
            'rejaHolatlari': holatlar,
            'kutilayotganTasdiqlar': len(kutilayotgan),
            'pastYuklamalarSoni': past,
        },
        'barChartData': bar,
        'kutilayotganAmallar': kutilayotgan,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def rol_rejalar(request):
    """Rahbar uchun yengil rejalar ro'yxati: bosqichlar holati, navbat va "men qaror qila olamanmi".

    ?oquvYili=  ?holat=loyiha|tekshiruvda|tasdiqlangan|rad_etilgan|menga  ?kafedraId=  ?id=
    """
    from apps.workload.approval_flow import STAGES, can_act, next_approval
    from apps.workload.models import Approval, Reja
    from apps.workload.services import reja_fan_hours

    if user_scope(request.user).role == 'oqituvchi':
        return Response({'detail': "Bu sahifa rahbarlar uchun."}, status=status.HTTP_403_FORBIDDEN)
    p = request.query_params
    rejalar = scope_filter(Reja.objects.select_related('teacher', 'department').all(), request.user,
                           departments_of=lambda r: [r.department_id])
    if p.get('id'):
        rejalar = rejalar.filter(pk=p['id'])
    if p.get('oquvYili'):
        rejalar = rejalar.filter(oquv_yili=p['oquvYili'])
    if p.get('kafedraId'):
        rejalar = rejalar.filter(department_id=p['kafedraId'])
    holat = p.get('holat')
    if holat and holat != 'menga':
        rejalar = rejalar.filter(status=holat)

    approvals = {}
    for a in Approval.objects.all():
        approvals.setdefault(a.reja_id, {})[a.stage] = a
    from apps.departments.models import OTM, Faculty
    faculties = {f.id: f for f in Faculty.objects.all()}
    otms = {o.id: o for o in OTM.objects.all()}
    rows = []
    for r in rejalar:
        fac = faculties.get(r.department.faculty_id) if r.department else None
        otm = otms.get(fac.otm_id) if fac else None
        nxt = next_approval(r)
        mine = bool(nxt and can_act(request.user, r, nxt.stage))
        if holat == 'menga' and not mine:
            continue
        stages = approvals.get(r.id, {})
        rows.append({
            'id': r.id,
            'fio': r.teacher.full_name if r.teacher else '',
            'lavozim': r.teacher.position if r.teacher else '',
            'oqituvchiId': r.teacher_id,
            'kafedraId': r.department_id,
            'kafedraNomi': r.department.name if r.department else '',
            'fakultetId': fac.id if fac else None,
            'fakultetNomi': fac.name if fac else '',
            'otmId': otm.id if otm else None,
            'otmNomi': otm.name if otm else '',
            'stavka': r.teacher.rate if r.teacher else '',
            'oquvYili': r.oquv_yili,
            'status': r.status,
            # Shakllangan yuklama soati (diagramma bilan bir xil hisob)
            'jamiSoat': float(reja_fan_hours(r)),
            'navbat': nxt.stage if nxt else None,
            'mengaNavbat': mine,
            'bosqichlar': [{
                'bosqich': stage,
                'holat': stages[stage].state if stage in stages else 'kutilmoqda',
                'izoh': stages[stage].comment if stage in stages else '',
                'sana': stages[stage].acted_at.isoformat() if stage in stages and stages[stage].acted_at else None,
            } for stage in STAGES],
            'yangilangan': r.edited_at.isoformat() if r.edited_at else None,
        })
    rows.sort(key=lambda row: (not row['mengaNavbat'], row['fio']))
    return Response(rows)


auth_patterns = [
    path('scope', scope),
    path('users/<int:user_id>/rollar', user_roles),
]

from apps.workload import evidence_views  # noqa: E402

crud_patterns = [
    path('xabarlar/', xabarlar),
    path('xabarlar/oqildi/', xabarlar_oqildi),
    path('ish-dalillari/', evidence_views.dalillar),
    path('ish-dalillari/<int:pk>/', evidence_views.dalil_detail),
    path('ish-dalillari/<int:pk>/tekshirish/', evidence_views.dalil_tekshirish),
    path('ish-dalillari/<int:pk>/fayl/', evidence_views.dalil_fayl),
]

from apps.workload import report_views  # noqa: E402

LESSON_LABELS = {'maruza': "Ma'ruza", 'amaliyot': "Amaliy mashg'ulot", 'laboratoriya': 'Laboratoriya'}
WORK_LABELS = {'amaliyot': 'Amaliyot (praktika)', 'nazorat': 'Nazorat', 'kurs_loyihasi': 'Kurs ishi',
               'md_ilmiy_rahbarlik': 'MD rahbarligi', 'bmi_rahbarlik': 'BMI rahbarligi', 'dak_taqriz': 'DAK / taqriz'}


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def teacher_guruhlar(request):
    """O'qituvchi profili: rejasidagi fanlarga mudir biriktirgan guruhlar (talabalari va fanlari bilan).

    ?oquvYili= — bo'lmasa eng oxirgi reja. Faqat o'z rejasidagi guruhlar qaytariladi.
    """
    from apps.academics.models import Group, Talaba
    from apps.workload.evidence_views import _teacher_reja

    scope = user_scope(request.user)
    if scope.teacher is None:
        return Response({'reja': None, 'guruhlar': [], 'biriktirilmagan': []})
    reja = _teacher_reja(scope, oquv_yili=request.query_params.get('oquvYili'))
    if reja is None:
        return Response({'reja': None, 'guruhlar': [], 'biriktirilmagan': []})
    data = reja.data if isinstance(reja.data, dict) else {}
    variants = data.get('variants') if isinstance(data.get('variants'), dict) else {'rate_1': data}
    fans_by_group, unassigned, seen = {}, [], set()
    for variant in variants.values():
        for fan in (variant or {}).get('fanlar') or []:
            if not isinstance(fan, dict) or str(fan.get('id')) in seen:
                continue
            seen.add(str(fan.get('id')))
            item = {
                'nomi': str(fan.get('baseNomi') or fan.get('nomi') or ''),
                'turi': LESSON_LABELS.get(fan.get('lessonType')) or WORK_LABELS.get(fan.get('workloadKind')) or '',
                'semestr': fan.get('semestr') or '',
                'soat': fan.get('soat') or 0,
            }
            guruhlar = [g for g in (fan.get('guruhlar') or []) if isinstance(g, dict) and g.get('id')]
            if not guruhlar:
                unassigned.append(item)
            for g in guruhlar:
                fans_by_group.setdefault(int(g['id']), []).append(item)
    groups = {g.id: g for g in Group.objects.filter(pk__in=list(fans_by_group))}
    result = []
    for gid, fans in fans_by_group.items():
        g = groups.get(gid)
        if g is None:
            continue
        talabalar = [{'id': t.id, 'fio': t.fio, 'telefon': t.telefon}
                     for t in Talaba.objects.filter(group_id=gid)]
        result.append({
            'id': g.id, 'nomi': g.name, 'kurs': g.course, 'talimShakli': g.program_type,
            'oqishShakli': g.study_format, 'talabaSoni': g.students or len(talabalar),
            'fanlar': fans, 'talabalar': talabalar,
        })
    result.sort(key=lambda r: r['nomi'])
    return Response({'reja': {'id': reja.id, 'oquvYili': reja.oquv_yili},
                     'guruhlar': result, 'biriktirilmagan': unassigned})


teacher_patterns = [
    path('guruhlar/', teacher_guruhlar),
    path('bajarilgan-ishlar/', evidence_views.teacher_ishlar),
    path('natijalar/', report_views.teacher_natijalar),
]

hisobot_patterns = [
    path('bajarilish/', report_views.bajarilish_hisobot),
    path('yopish/', report_views.yilni_yopish),
]

dashboard_patterns = [
    path('rol/', rol_dashboard),
    path('rol/rejalar/', rol_rejalar),
    path('rol/kafedralar/', fakultet_views.rol_kafedralar),
    path('rol/guruhlar/', fakultet_views.rol_guruhlar),
    path('rol/guruhlar/<int:pk>/', fakultet_views.rol_guruh_detail),
    path('rol/tizim/', tizim_views.tizim_holati),
    path('rol/oquv-bolimi/', oquv_bolimi_views.oquv_bolimi_panel),
]
