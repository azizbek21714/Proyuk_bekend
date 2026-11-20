"""Bajarilish hisobotlari va yillik arxiv.

  GET  /api/hisobot/bajarilish/?oquvYili=&kafedraId=&fakultetId=[&eksport=xlsx]   rahbarlar
  POST /api/hisobot/yopish/   {oquvYili, kafedraId?}                              o'quv bo'limi / admin
  GET  /api/teacher/natijalar/                                                   o'qituvchi: yillar kesimida
"""
from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.roles import user_scope
from apps.core.odm import atomic
from config.permissions import scope_filter
from .bajarilish import SECTIONS, compute
from .models import IshDalili, Reja, YillikNatija

SECTION_TITLE = {key: label for key, _, label in SECTIONS}


def _rejalar(request, oquv_yili):
    qs = scope_filter(Reja.objects.select_related('teacher', 'department').all(), request.user,
                      departments_of=lambda r: [r.department_id])
    qs = qs.filter(oquv_yili=oquv_yili)
    p = request.query_params if request.method == 'GET' else request.data
    if p.get('kafedraId'):
        qs = qs.filter(department_id=p['kafedraId'])
    if p.get('fakultetId'):
        qs = qs.filter(department__faculty_id=p['fakultetId'])
    return list(qs)


def _row(reja, frozen, dalillar_by_reja):
    natija = frozen.natija if frozen is not None else compute(reja, dalillar_by_reja.get(reja.id, []))
    return {
        'rejaId': reja.id,
        'oqituvchiId': reja.teacher_id,
        'fio': reja.teacher.full_name if reja.teacher else '',
        'lavozim': reja.teacher.position if reja.teacher else '',
        'kafedraId': reja.department_id,
        'kafedraNomi': reja.department.name if reja.department else '',
        'yopilgan': frozen is not None,
        **natija,
    }


def build_report(request, oquv_yili):
    rejalar = _rejalar(request, oquv_yili)
    ids = {r.id for r in rejalar}
    dalillar_by_reja = {}
    for d in IshDalili.objects.filter(oquv_yili=oquv_yili):
        if d.reja_id in ids:
            dalillar_by_reja.setdefault(d.reja_id, []).append(d)
    frozen = {n.teacher_id: n for n in YillikNatija.objects.filter(oquv_yili=oquv_yili)}
    rows = [_row(r, frozen.get(r.teacher_id), dalillar_by_reja) for r in rejalar]
    rows.sort(key=lambda r: (r['kafedraNomi'], r['fio']))
    return rows


def _xlsx(rows, oquv_yili):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = 'Bajarilish'
    ws.append([f"Professor-o'qituvchilar ish rejasining bajarilishi — {oquv_yili}"])
    ws['A1'].font = Font(bold=True, size=13)
    header = ['№', 'Kafedra', 'F.I.Sh.'] + [SECTION_TITLE[k] + ' (%)' for k, _, _ in SECTIONS] + \
             ['Rejadagi ishlar', 'Qabul qilingan', 'Umumiy (%)', 'Holat']
    ws.append([])
    ws.append(header)
    for cell in ws[3]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill('solid', fgColor='E2EFDA')
        cell.alignment = Alignment(wrap_text=True, vertical='center')
    for i, r in enumerate(rows, 1):
        by_key = {b['bolim']: b['foiz'] for b in r['bolimlar']}
        ws.append([i, r['kafedraNomi'], r['fio']] + [by_key.get(k, 0) for k, _, _ in SECTIONS] +
                  [r['qatorlar'], r['qabulQilingan'], r['umumiyFoiz'], 'Yopilgan' if r['yopilgan'] else 'Joriy'])
    for col, width in zip('ABCDEFGHIJ', (5, 28, 34, 16, 16, 16, 12, 12, 12, 11)):
        ws.column_dimensions[col].width = width
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def bajarilish_hisobot(request):
    if user_scope(request.user).role == 'oqituvchi':
        return Response({'detail': 'Hisobot rahbarlar uchun.'}, status=status.HTTP_403_FORBIDDEN)
    oquv_yili = request.query_params.get('oquvYili')
    if not oquv_yili:
        return Response({'oquvYili': ['Bu maydon majburiy.']}, status=status.HTTP_400_BAD_REQUEST)
    rows = build_report(request, oquv_yili)
    if request.query_params.get('eksport') == 'xlsx':
        response = HttpResponse(
            _xlsx(rows, oquv_yili),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="bajarilish-{oquv_yili}.xlsx"'
        return response
    return Response(rows)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def yilni_yopish(request):
    """O'quv yili natijalarini muzlatadi (keyin yangi yuklash va tekshiruv bloklanadi)."""
    scope = user_scope(request.user)
    if not (scope.is_admin or 'oquv_bolimi' in scope.roles):
        return Response({'detail': "Yilni faqat o'quv bo'limi yopa oladi."}, status=status.HTTP_403_FORBIDDEN)
    oquv_yili = request.data.get('oquvYili')
    if not oquv_yili:
        return Response({'oquvYili': ['Bu maydon majburiy.']}, status=status.HTTP_400_BAD_REQUEST)
    rows = build_report(request, oquv_yili)
    now = timezone.now()
    created = 0
    with atomic():
        for row in rows:
            if row['yopilgan']:
                continue
            natija = {k: v for k, v in row.items()
                      if k in ('oquvYili', 'bolimlar', 'qatorlar', 'qabulQilingan', 'rejaSoat',
                               'bajarilganSoat', 'umumiyFoiz')}
            YillikNatija.objects.create(teacher_id=row['oqituvchiId'], department_id=row['kafedraId'],
                                        oquv_yili=oquv_yili, natija=natija, yopilgan_sana=now,
                                        yopgan=request.user)
            created += 1
    return Response({'yopildi': created, 'jami': len(rows)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def teacher_natijalar(request):
    """O'qituvchi profili: o'quv yillari kesimida bajarilish natijalari."""
    scope = user_scope(request.user)
    if scope.teacher is None:
        return Response([])
    frozen = {n.oquv_yili: n for n in YillikNatija.objects.filter(teacher_id=scope.teacher_id)}
    result = []
    for reja in Reja.objects.filter(teacher_id=scope.teacher_id).order_by('-oquv_yili'):
        n = frozen.pop(reja.oquv_yili, None)
        natija = n.natija if n else compute(reja, list(IshDalili.objects.filter(reja=reja)))
        result.append({**natija, 'oquvYili': reja.oquv_yili, 'yopilgan': n is not None,
                       'yopilganSana': n.yopilgan_sana.isoformat() if n and n.yopilgan_sana else None})
    for year, n in frozen.items():  # reja o'chirilgan, lekin natija saqlangan yillar
        result.append({**n.natija, 'oquvYili': year, 'yopilgan': True,
                       'yopilganSana': n.yopilgan_sana.isoformat() if n.yopilgan_sana else None})
    result.sort(key=lambda r: r['oquvYili'], reverse=True)
    return Response(result)
