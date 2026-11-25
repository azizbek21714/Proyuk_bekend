"""Rahbarlar uchun fakultet tarkibi: kafedralar (mudirlari bilan) va guruhlar (yo'nalish, sardor, murabbiy).

GET   /api/dashboard/rol/kafedralar/                 dekan, o'quv bo'limi, mudir, admin — hududdagi kafedralar
GET   /api/dashboard/rol/guruhlar/?kafedraId=        hududdagi guruhlar
PATCH /api/dashboard/rol/guruhlar/<id>/              {yonalish, sardorId, murabbiyId} — admin, dekan, kafedra mudiri
"""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.roles import user_scope
from config.permissions import require_departments, scope_filter

EDIT_ROLES = ('admin', 'dekan', 'kafedra_mudiri')


def _forbidden_for_teacher(request):
    if user_scope(request.user).role == 'oqituvchi':
        return Response({'detail': "Bu sahifa rahbarlar uchun."}, status=status.HTTP_403_FORBIDDEN)
    return None


def _person(obj, name_attr, phone_attr):
    if obj is None:
        return None
    return {'id': obj.id, 'fio': getattr(obj, name_attr, '') or '', 'telefon': getattr(obj, phone_attr, '') or ''}


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def rol_kafedralar(request):
    """Hududdagi kafedralar: mudir FIO va aloqa, o'qituvchilar va guruhlar soni."""
    denied = _forbidden_for_teacher(request)
    if denied:
        return denied
    from apps.academics.models import Group
    from apps.departments.models import Department, Faculty
    from apps.teachers.models import Teacher

    deps = scope_filter(Department.objects.all(), request.user, departments_of=lambda d: [d.id])
    faculties = {f.id: f for f in Faculty.objects.all()}
    teachers = {t.id: t for t in Teacher.objects.all()}
    guruh_soni = {}
    for g in Group.objects.all():
        guruh_soni[g.department_id] = guruh_soni.get(g.department_id, 0) + 1
    rows = []
    for d in deps:
        head = teachers.get(d.head_of_department_id)
        fac = faculties.get(d.faculty_id)
        rows.append({
            'id': d.id,
            'nomi': d.name,
            'fakultetId': d.faculty_id,
            'fakultetNomi': fac.name if fac else '',
            'mudir': _person(head, 'full_name', 'phone_number') and {
                **_person(head, 'full_name', 'phone_number'), 'pochta': head.email or '',
            },
            'oqituvchilarSoni': len(list(d.teachers.all())),
            'guruhlarSoni': guruh_soni.get(d.id, 0),
        })
    rows.sort(key=lambda r: r['nomi'])
    return Response(rows)


def _group_row(g, deps, talabalar_by_id, teachers, talaba_soni):
    dep = deps.get(g.department_id)
    return {
        'id': g.id,
        'nomi': g.name,
        'kafedraId': g.department_id,
        'kafedraNomi': dep.name if dep else '',
        'kurs': g.course,
        'talimTuri': g.program_type,
        'talimShakli': g.study_format,
        'tili': g.study_language,
        'oquvYili': g.oquv_yili,
        'yonalish': g.yonalish or '',
        'talabaSoni': talaba_soni.get(g.id, 0) or g.students or 0,
        'sardor': _person(talabalar_by_id.get(g.sardor_id), 'fio', 'telefon'),
        'murabbiy': _person(teachers.get(g.murabbiy_id), 'full_name', 'phone_number'),
    }


def _context():
    from apps.academics.models import Talaba
    from apps.departments.models import Department
    from apps.teachers.models import Teacher

    talabalar = list(Talaba.objects.all())
    talaba_soni = {}
    for t in talabalar:
        talaba_soni[t.group_id] = talaba_soni.get(t.group_id, 0) + 1
    return ({d.id: d for d in Department.objects.all()}, {t.id: t for t in talabalar},
            {t.id: t for t in Teacher.objects.all()}, talaba_soni)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def rol_guruhlar(request):
    """Hududdagi guruhlar: yo'nalish, kurs, ta'lim turi, talabalar soni, sardor va murabbiy."""
    denied = _forbidden_for_teacher(request)
    if denied:
        return denied
    from apps.academics.models import Group

    qs = scope_filter(Group.objects.all(), request.user, departments_of=lambda g: [g.department_id])
    kaf = request.query_params.get('kafedraId')
    groups = [g for g in qs if not kaf or str(g.department_id) == str(kaf)]
    deps, talabalar, teachers, soni = _context()
    rows = [_group_row(g, deps, talabalar, teachers, soni) for g in groups]
    rows.sort(key=lambda r: (r['yonalish'] or '~', r['kurs'] or '', r['nomi']))
    return Response(rows)


def _int_or_none(value, field):
    if value in (None, '', 'null'):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise PermissionDenied(f"{field} noto'g'ri.") from None


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def rol_guruh_detail(request, pk):
    """Guruh yo'nalishi, sardori (shu guruh talabasi) va murabbiyini (hududdagi o'qituvchi) belgilash."""
    from apps.academics.models import Group, Talaba
    from apps.teachers.models import Teacher
    from apps.teachers.views import teacher_departments

    scope = user_scope(request.user)
    if scope.role not in EDIT_ROLES:
        return Response({'detail': "Bu amal faqat admin, dekan va kafedra mudiri uchun."},
                        status=status.HTTP_403_FORBIDDEN)
    group = Group.objects.filter(pk=pk).first()
    if group is None:
        return Response({'detail': 'Guruh topilmadi.'}, status=status.HTTP_404_NOT_FOUND)
    require_departments(request.user, [group.department_id])

    data = request.data
    errors = {}
    if 'yonalish' in data:
        yonalish = str(data.get('yonalish') or '').strip()
        if len(yonalish) > 255:
            errors['yonalish'] = ["Yo'nalish 255 belgidan oshmasin."]
        else:
            group.yonalish = yonalish
    if 'sardorId' in data:
        try:
            sid = _int_or_none(data.get('sardorId'), 'sardorId')
        except PermissionDenied:
            sid, errors['sardorId'] = None, ["Noto'g'ri qiymat."]
        if sid is not None and not Talaba.objects.filter(pk=sid, group_id=group.id).exists():
            errors['sardorId'] = ["Sardor shu guruh talabalaridan tanlanishi kerak."]
        elif 'sardorId' not in errors:
            group.sardor_id = sid
    if 'murabbiyId' in data:
        try:
            mid = _int_or_none(data.get('murabbiyId'), 'murabbiyId')
        except PermissionDenied:
            mid, errors['murabbiyId'] = None, ["Noto'g'ri qiymat."]
        if mid is not None:
            teacher = Teacher.objects.filter(pk=mid).first()
            if teacher is None:
                errors['murabbiyId'] = ["O'qituvchi topilmadi."]
            elif not scope.is_admin and not (set(teacher_departments().get(mid, [])) & set(scope.department_ids)):
                errors['murabbiyId'] = ["Murabbiy o'z hududingizdagi o'qituvchilardan tanlanishi kerak."]
        if 'murabbiyId' not in errors:
            group.murabbiy_id = mid
    if errors:
        return Response(errors, status=status.HTTP_400_BAD_REQUEST)
    group.save()
    deps, talabalar, teachers, soni = _context()
    return Response(_group_row(group, deps, talabalar, teachers, soni))
