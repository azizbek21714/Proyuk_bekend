"""Bajarilgan ishlar (ish dalillari) API.

  GET    /api/crud/ish-dalillari/                 ro'yxat (rol hududi bo'yicha)
  POST   /api/crud/ish-dalillari/                 yuklash (multipart: rejaId, bolim, qatorId, izoh, havola, fayllar)
  DELETE /api/crud/ish-dalillari/<id>/            o'chirish (egasi, qabul qilinmagan bo'lsa)
  POST   /api/crud/ish-dalillari/<id>/tekshirish/ {qaror: qabul|rad, sabab}
  GET    /api/crud/ish-dalillari/<id>/fayl/?i=0   faylni yuklab olish (huquq tekshiriladi)
  GET    /api/teacher/bajarilgan-ishlar/?rejaId=  o'qituvchi: reja qatorlari + dalillar + foizlar
"""
import mimetypes
import os
import uuid
from urllib.parse import quote

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import User, notify
from apps.accounts.roles import user_scope
from apps.core.files import FileStorageError, get_file_storage
from apps.core.odm import atomic
from apps.departments.models import Department, Faculty
from config.permissions import scope_filter
from .bajarilish import SECTION_KEYS, compute, find_row, plan_rows
from .models import IshDalili, Reja, YillikNatija

ALLOWED_EXT = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.jpg', '.jpeg', '.png'}
MAX_FILE = 10 * 1024 * 1024
MAX_FILES_PER_UPLOAD = 5
MAX_FILES_TOTAL = 10
HOLAT_LABEL = {
    'kafedrada': 'Kafedra mudirida', 'oquv_bolimida': "O'quv bo'limida",
    'qabul_qilindi': 'Qabul qilindi', 'rad_etildi': 'Rad etildi',
}
LINK = '/dashboard/teacher'
REVIEW_LINK = {'kafedrada': '/dashboard/kafedra/ishlar', 'oquv_bolimida': '/dashboard/oquv-bolimi/ishlar'}


def _err(detail, code=status.HTTP_400_BAD_REQUEST):
    return Response({'detail': detail}, status=code)


def year_closed(teacher_id, oquv_yili):
    return YillikNatija.objects.filter(teacher_id=teacher_id, oquv_yili=oquv_yili).exists()


def _start_stage(reja):
    """Kafedra mudiri yo'q bo'lsa yoki egasining o'zi mudir/dekan bo'lsa — to'g'ridan-to'g'ri o'quv bo'limiga."""
    dep = Department.objects.filter(pk=reja.department_id).first() if reja.department_id else None
    if dep is None or dep.head_of_department_id is None or dep.head_of_department_id == reja.teacher_id:
        return 'oquv_bolimida'
    faculty = Faculty.objects.filter(pk=dep.faculty_id).first()
    if faculty is not None and faculty.dean_id == reja.teacher_id:
        return 'oquv_bolimida'
    return 'kafedrada'


def _reviewers(dalil):
    if dalil.holat == 'kafedrada':
        dep = Department.objects.filter(pk=dalil.department_id).first() if dalil.department_id else None
        head = dep.head_of_department if dep else None
        return [head.user_id] if head and head.user_id else []
    if dalil.holat == 'oquv_bolimida':
        from apps.workload.approval_flow import oquv_bolimi_users
        return oquv_bolimi_users(dalil.department_id)
    return []


def can_review(user, dalil):
    scope = user_scope(user)
    if dalil.holat not in ('kafedrada', 'oquv_bolimida'):
        return False
    if scope.is_admin:
        return True
    if scope.teacher_id is not None and dalil.teacher_id == scope.teacher_id:
        return False
    if dalil.holat == 'kafedrada':
        return 'kafedra_mudiri' in scope.roles and dalil.department_id in scope.headed_department_ids
    return 'oquv_bolimi' in scope.roles and dalil.department_id in scope.department_ids


def _visible(user):
    """Foydalanuvchi ko'ra oladigan dalillar."""
    scope = user_scope(user)
    qs = IshDalili.objects.select_related('teacher', 'department').all()
    if scope.role == 'oqituvchi':
        return qs.filter(teacher_id=scope.teacher_id) if scope.teacher_id else qs.none()
    return scope_filter(qs, user, departments_of=lambda d: [d.department_id], teacher_of=lambda d: d.teacher_id)


def serialize(dalil, user=None, full=True):
    data = {
        'id': dalil.id,
        'rejaId': dalil.reja_id,
        'oqituvchiId': dalil.teacher_id,
        'fio': dalil.teacher.full_name if dalil.teacher else '',
        'unvon': dalil.yuboruvchi_unvon,
        'kafedraId': dalil.department_id,
        'kafedraNomi': dalil.department.name if dalil.department else '',
        'oquvYili': dalil.oquv_yili,
        'bolim': dalil.bolim,
        'qatorId': dalil.qator_id,
        'qatorNomi': dalil.qator_nomi,
        'ishNomi': dalil.ish_nomi or '',
        'nomi': dalil.ish_nomi or dalil.qator_nomi,
        'nashrTuri': dalil.nashr_turi or '',
        'hammualliflar': dalil.hammualliflar,
        'rejaSoat': float(dalil.reja_soat or 0),
        'izoh': dalil.izoh,
        'havola': dalil.havola,
        'fayllar': [{'i': i, 'nomi': f.get('nomi'), 'hajm': f.get('hajm'), 'mime': f.get('mime')}
                    for i, f in enumerate(dalil.fayllar or [])],
        'holat': dalil.holat,
        'holatNomi': HOLAT_LABEL.get(dalil.holat, dalil.holat),
        'sabab': dalil.sabab,
        'yangilangan': dalil.edited_at.isoformat() if dalil.edited_at else None,
    }
    if full:
        data['tekshiruvlar'] = dalil.tekshiruvlar or []
    if user is not None:
        data['mengaNavbat'] = can_review(user, dalil)
    return data


def _save_files(files, teacher_id, reja_id):
    """Fayllarni tekshirib saqlaydi; [{path, nomi, hajm, mime}] qaytaradi."""
    storage = get_file_storage()
    saved = []
    try:
        for f in files:
            ext = os.path.splitext(f.name or '')[1].lower()
            if ext not in ALLOWED_EXT:
                raise ValueError(f"'{f.name}': ruxsat etilmagan fayl turi. PDF, Word, Excel, PowerPoint yoki rasm yuklang.")
            if f.size > MAX_FILE:
                raise ValueError(f"'{f.name}': fayl hajmi 10 MB dan oshmasligi kerak.")
            mime = mimetypes.types_map.get(ext) or f.content_type or 'application/octet-stream'
            path = f'{teacher_id}/{reja_id}/{uuid.uuid4().hex}{ext}'
            storage.upload(path, f.read(), mime)
            saved.append({'path': path, 'nomi': f.name, 'hajm': f.size, 'mime': mime})
    except Exception:
        storage.delete([s['path'] for s in saved])
        raise
    return saved


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def dalillar(request):
    if request.method == 'GET':
        qs = _visible(request.user)
        p = request.query_params
        if p.get('mening'):
            scope = user_scope(request.user)
            qs = qs.filter(teacher_id=scope.teacher_id) if scope.teacher_id else qs.none()
        for param, field in (('oquvYili', 'oquv_yili'), ('kafedraId', 'department_id'),
                             ('oqituvchiId', 'teacher_id'), ('bolim', 'bolim'), ('rejaId', 'reja_id')):
            if p.get(param):
                qs = qs.filter(**{field: p[param]})
        holat = p.get('holat')
        rows = [serialize(d, request.user, full=False) for d in qs]
        if holat == 'menga':
            rows = [r for r in rows if r['mengaNavbat']]
        elif holat:
            rows = [r for r in rows if r['holat'] == holat]
        rows.sort(key=lambda r: (not r['mengaNavbat'], r['fio'], r['bolim']))
        return Response(rows)
    return _upload(request)


def _upload(request):
    scope = user_scope(request.user)
    if scope.teacher is None:
        return _err("Ish yuklash uchun o'qituvchi profilingiz bo'lishi kerak.", status.HTTP_403_FORBIDDEN)
    reja = Reja.objects.filter(pk=request.data.get('rejaId'), teacher_id=scope.teacher_id).first()
    if reja is None:
        return _err('Shaxsiy reja topilmadi.', status.HTTP_404_NOT_FOUND)
    if year_closed(reja.teacher_id, reja.oquv_yili):
        return _err(f"{reja.oquv_yili} o'quv yili yopilgan — yangi ish yuklab bo'lmaydi.")
    bolim = request.data.get('bolim')
    if bolim not in SECTION_KEYS:
        return _err("Bo'lim noto'g'ri.")
    row = find_row(reja, bolim, request.data.get('qatorId'))
    if row is None:
        return _err("Rejada bunday ish topilmadi. Avval shaxsiy rejani saqlang.")
    files = request.FILES.getlist('fayllar') or request.FILES.getlist('file')
    if len(files) > MAX_FILES_PER_UPLOAD:
        return _err(f"Bir martada {MAX_FILES_PER_UPLOAD} tagacha fayl yuklash mumkin.")
    izoh = str(request.data.get('izoh') or '').strip()[:2000]
    havola = str(request.data.get('havola') or '').strip()[:500]
    if havola and not havola.lower().startswith(('http://', 'https://')):
        return _err("Havola http:// yoki https:// bilan boshlanishi kerak.")

    ish_nomi = ' '.join(str(request.data.get('ishNomi') or '').split())[:1000]
    nashr_turi = str(request.data.get('nashrTuri') or '').strip()
    if nashr_turi not in ('', 'jurnal', 'konferensiya'):
        return _err("Nashr turi 'jurnal' yoki 'konferensiya' bo'lishi kerak.")
    hammualliflar = None
    if str(request.data.get('hammualliflar') or '').strip():
        try:
            hammualliflar = int(request.data.get('hammualliflar'))
        except (TypeError, ValueError):
            return _err("Hammualliflar soni butun son bo'lishi kerak.")
        if not 0 <= hammualliflar <= 100:
            return _err("Hammualliflar soni 0 dan 100 gacha bo'lishi kerak.")

    dalil_id = request.data.get('dalilId')
    if dalil_id:
        # Mavjud yuborishga fayl qo'shish yoki rad etilganini qayta yuborish
        dalil = IshDalili.objects.filter(pk=dalil_id, reja=reja).first()
        if dalil is None:
            return _err('Yuborilgan ish topilmadi.', status.HTTP_404_NOT_FOUND)
    elif ish_nomi:
        dalil = None  # yangi forma: har bir yuborish alohida yozuv (masalan 2 ta tezis)
    else:
        dalil = IshDalili.objects.filter(reja=reja, bolim=bolim, qator_id=row['id']).first()
    if dalil is not None and dalil.holat == 'qabul_qilindi':
        return _err('Bu ish allaqachon qabul qilingan.')
    existing = len(dalil.fayllar or []) if dalil else 0
    if existing + len(files) > MAX_FILES_TOTAL:
        return _err(f"Bitta ish uchun {MAX_FILES_TOTAL} tagacha fayl yuklash mumkin.")
    if not files and not havola and not existing and not (dalil and dalil.havola):
        return _err('Kamida bitta fayl yoki havola kerak.')
    try:
        saved = _save_files(files, reja.teacher_id, reja.id)
    except ValueError as exc:
        return _err(str(exc))
    except FileStorageError as exc:
        return _err(f'Fayl saqlash xizmati ishlamayapti: {exc}', status.HTTP_503_SERVICE_UNAVAILABLE)

    unvon = scope.label if scope.role in ('dekan', 'kafedra_mudiri') else ''
    start = _start_stage(reja)
    with atomic():
        if dalil is None:
            dalil = IshDalili(teacher_id=reja.teacher_id, reja=reja, department_id=reja.department_id,
                              oquv_yili=reja.oquv_yili, bolim=bolim, qator_id=row['id'])
            resubmit = False
        else:
            resubmit = dalil.holat == 'rad_etildi'
        dalil.variant = row['variant']
        dalil.qator_nomi = row['nomi']
        dalil.reja_soat = row['rejaSoat']
        if ish_nomi:
            dalil.ish_nomi = ish_nomi
        if nashr_turi:
            dalil.nashr_turi = nashr_turi
        if hammualliflar is not None:
            dalil.hammualliflar = hammualliflar
        dalil.fayllar = list(dalil.fayllar or []) + saved
        if izoh:
            dalil.izoh = izoh
        if havola:
            dalil.havola = havola
        dalil.yuboruvchi_unvon = unvon
        if dalil.pk is None or resubmit:
            dalil.holat = start
            dalil.sabab = ''
        dalil.save()
    if dalil.holat in ('kafedrada', 'oquv_bolimida'):
        notify(_reviewers(dalil),
               f"{dalil.teacher.full_name if dalil.teacher else ''} bajarilgan ish yukladi: {dalil.ish_nomi or dalil.qator_nomi}",
               REVIEW_LINK.get(dalil.holat, ''))
    return Response(serialize(dalil, request.user), status=status.HTTP_201_CREATED)


def _get_visible(request, pk):
    return _visible(request.user).filter(pk=pk).first()


@api_view(['GET', 'DELETE'])
@permission_classes([IsAuthenticated])
def dalil_detail(request, pk):
    dalil = _get_visible(request, pk)
    if dalil is None:
        return _err('Topilmadi.', status.HTTP_404_NOT_FOUND)
    if request.method == 'GET':
        return Response(serialize(dalil, request.user))
    scope = user_scope(request.user)
    if not (scope.is_admin or dalil.teacher_id == scope.teacher_id):
        return _err("Faqat ish egasi o'chira oladi.", status.HTTP_403_FORBIDDEN)
    if dalil.holat == 'qabul_qilindi' and not scope.is_admin:
        return _err("Qabul qilingan ishni o'chirib bo'lmaydi.")
    try:
        get_file_storage().delete([f['path'] for f in dalil.fayllar or [] if f.get('path')])
    except FileStorageError:
        pass
    dalil.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def dalil_tekshirish(request, pk):
    dalil = _get_visible(request, pk)
    if dalil is None:
        return _err('Topilmadi.', status.HTTP_404_NOT_FOUND)
    qaror = request.data.get('qaror')
    sabab = str(request.data.get('sabab') or '').strip()[:2000]
    if qaror not in ('qabul', 'rad'):
        return Response({'qaror': ["Qaror 'qabul' yoki 'rad' bo'lishi kerak."]}, status=status.HTTP_400_BAD_REQUEST)
    if qaror == 'rad' and not sabab:
        return Response({'sabab': ['Rad etish sababini yozing.']}, status=status.HTTP_400_BAD_REQUEST)
    if year_closed(dalil.teacher_id, dalil.oquv_yili):
        return _err(f"{dalil.oquv_yili} o'quv yili yopilgan.")
    if not can_review(request.user, dalil):
        return _err("Bu ish hozir sizning tekshiruvingizda emas.", status.HTTP_403_FORBIDDEN)
    stage = dalil.holat
    scope = user_scope(request.user)
    reviewer = scope.teacher.full_name if scope.teacher else (request.user.get_full_name() or request.user.email)
    with atomic():
        if qaror == 'rad':
            dalil.holat = 'rad_etildi'
            dalil.sabab = sabab
        else:
            dalil.holat = 'oquv_bolimida' if stage == 'kafedrada' else 'qabul_qilindi'
            dalil.sabab = ''
        dalil.tekshiruvlar = list(dalil.tekshiruvlar or []) + [{
            'bosqich': stage, 'qaror': qaror, 'sabab': sabab,
            'kim': reviewer, 'kimId': request.user.id, 'sana': timezone.now().isoformat(),
        }]
        dalil.save(update_fields=['holat', 'sabab', 'tekshiruvlar', 'edited_at'])
    owner = dalil.teacher.user_id if dalil.teacher else None
    if dalil.holat == 'rad_etildi':
        notify(owner, f"«{dalil.ish_nomi or dalil.qator_nomi}» ishingiz rad etildi. Sabab: {sabab}", LINK)
    elif dalil.holat == 'qabul_qilindi':
        notify(owner, f"«{dalil.ish_nomi or dalil.qator_nomi}» ishingiz qabul qilindi.", LINK)
    else:
        notify(_reviewers(dalil),
               f"{dalil.teacher.full_name if dalil.teacher else ''}: «{dalil.ish_nomi or dalil.qator_nomi}» kafedra mudiri tomonidan "
               "tasdiqlandi va sizga yuborildi.", REVIEW_LINK['oquv_bolimida'])
    return Response(serialize(dalil, request.user))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dalil_fayl(request, pk):
    dalil = _get_visible(request, pk)
    if dalil is None:
        return _err('Topilmadi.', status.HTTP_404_NOT_FOUND)
    try:
        meta = (dalil.fayllar or [])[int(request.query_params.get('i', 0))]
    except (ValueError, IndexError):
        return _err('Fayl topilmadi.', status.HTTP_404_NOT_FOUND)
    try:
        content = get_file_storage().download(meta['path'])
    except FileStorageError as exc:
        return _err(str(exc), status.HTTP_404_NOT_FOUND)
    response = HttpResponse(content, content_type=meta.get('mime') or 'application/octet-stream')
    response['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(meta.get('nomi') or 'fayl')}"
    return response


def _teacher_reja(scope, reja_id=None, oquv_yili=None):
    qs = Reja.objects.filter(teacher_id=scope.teacher_id)
    if reja_id:
        return qs.filter(pk=reja_id).first()
    if oquv_yili:
        found = qs.filter(oquv_yili=oquv_yili).first()
        if found:
            return found
    return qs.order_by('-oquv_yili', '-id').first()


def amalda_qiymat(row, dalillar):
    """Ilmiy ish bo'yicha amalda bajarilgan qiymat (rad etilganlar hisobga olinmaydi).

    Scopus/WoS: har bir maqola 1 / hammualliflar soni, yig'indi 2 xonagacha yaxlitlanadi.
    Respublika: yuklangan ishlar soni. Boshqa bo'limlar uchun None.
    """
    if row['bolim'] != 'ilmiy':
        return None
    faol = [d for d in dalillar if d.holat != 'rad_etildi']
    if not faol:
        return None
    if row.get('scopus'):
        return round(sum(1 / max(d.hammualliflar or 1, 1) for d in faol), 2)
    return len(faol)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def teacher_ishlar(request):
    """O'qituvchi: rejadagi ishlar, ularning dalillari va bajarilish foizlari."""
    scope = user_scope(request.user)
    if scope.teacher is None:
        return _err("O'qituvchi profili topilmadi.", status.HTTP_404_NOT_FOUND)
    reja = _teacher_reja(scope, request.query_params.get('rejaId'), request.query_params.get('oquvYili'))
    if reja is None:
        return Response({'reja': None, 'qatorlar': [], 'natija': None, 'yopilgan': False})
    dalillar_list = list(IshDalili.objects.filter(reja=reja))
    # Har bir rejadagi ish uchun eng yaxshi holatdagi dalil (qabul > o'quv bo'limi > mudir > rad)
    rank = {'qabul_qilindi': 4, 'oquv_bolimida': 3, 'kafedrada': 2, 'rad_etildi': 1}
    by_row = {}
    for d in dalillar_list:
        key = (d.bolim, d.qator_id)
        if key not in by_row or rank.get(d.holat, 0) > rank.get(by_row[key].holat, 0):
            by_row[key] = d
    today = timezone.now().date().isoformat()
    qatorlar = []
    for row in plan_rows(reja):
        dalil = by_row.get((row['bolim'], row['id']))
        row_dalillar = [d for d in dalillar_list if (d.bolim, d.qator_id) == (row['bolim'], row['id'])]
        qatorlar.append({**row, 'dalil': serialize(dalil) if dalil else None, 'yuborilgan': len(row_dalillar),
                         'amalda': amalda_qiymat(row, row_dalillar), 'bugun': today})
    return Response({
        'reja': {'id': reja.id, 'oquvYili': reja.oquv_yili, 'status': reja.status},
        'qatorlar': qatorlar,
        'natija': compute(reja, dalillar_list),
        'yopilgan': year_closed(reja.teacher_id, reja.oquv_yili),
    })
