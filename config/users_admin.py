"""Admin: foydalanuvchilar va rollar.

Admin har bir xodimni FIO, telefon, pochta, parol va rol bilan o'zi kiritadi; xodim shu pochta va
parol bilan kiradi va admin bergan rol kabinetiga tushadi. Rol saqlanadigan joylar (roles.py dagi
hisob bilan bir xil, shuning uchun OTM formasidagi "Dekan"/"Kafedra mudiri" maydonlari bilan mos):
  kafedra_mudiri -> Department.head_of_department
  dekan          -> Faculty.dean
  oquv_bolimi    -> User.groups ichida 'oquv_bolimi'
  oqituvchi      -> yuqoridagilarning hech biri
Ro'yxat o'qituvchi profillari (Teacher) bo'yicha yuritiladi; kirish hisobi (User) profilga bog'lanadi.
"""
from hashlib import sha256

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.urls import path
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.models import User
from apps.core.odm import atomic
from apps.departments.models import Department, Faculty
from apps.teachers.models import Teacher, TeacherPosition
from rest_framework.permissions import BasePermission

from apps.accounts.roles import user_scope
from config.permissions import is_application_admin


class IsAdminOrHead(BasePermission):
    """Admin — hammasi; kafedra mudiri — faqat o'z kafedrasi o'qituvchilarining kirish hisobi."""
    message = "Bu amal faqat administrator yoki kafedra mudiri uchun ruxsat etilgan."

    def has_permission(self, request, view):
        return is_application_admin(request.user) or user_scope(request.user).role == 'kafedra_mudiri'


# Kafedra mudiri o'qituvchi profilida faqat shu maydonlarni o'zgartira oladi (kirish hisobi)
HEAD_FIELDS = {'pochta', 'parol', 'faol'}


def _head_guard(request, teacher, idx):
    """Mudir uchun: o'qituvchi uning kafedrasida bo'lishi va oddiy o'qituvchi bo'lishi kerak."""
    if is_application_admin(request.user):
        return
    scope = user_scope(request.user)
    if not set(idx.members.get(teacher.id, [])) & set(scope.department_ids):
        raise _Abort(Response({'detail': "Bu o'qituvchi sizning kafedrangizda emas."}, status=status.HTTP_403_FORBIDDEN))
    if scope.teacher_id == teacher.id:
        raise _Abort(Response({'detail': "O'z hisobingizni bu yerdan o'zgartirib bo'lmaydi."}, status=status.HTTP_403_FORBIDDEN))
    if _row(teacher, _find_user(teacher), idx)['rol'] != 'oqituvchi':
        raise _Abort(Response({'detail': "Rahbar xodimlarning hisobini faqat administrator boshqaradi."},
                              status=status.HTTP_403_FORBIDDEN))

ROLLAR = ('oqituvchi', 'kafedra_mudiri', 'dekan', 'oquv_bolimi')
ROLE_GROUPS = ('oquv_bolimi', 'dekan', 'kafedra_mudiri')


class _Abort(Exception):
    """atomic() ichidan xato javob bilan chiqish (tranzaksiya bekor qilinadi)."""

    def __init__(self, response):
        super().__init__('abort')
        self.response = response


def _bad(field, message):
    return Response({field: [message]}, status=status.HTTP_400_BAD_REQUEST)


def _username(email):
    # Ro'yxatdan o'tishdagi bilan bir xil texnik username (pochtadan olinadi)
    return 'email_' + sha256(email.encode('utf-8')).hexdigest()


class _Index:
    """Kafedra/fakultet bog'lanishlari — har profil uchun alohida so'rov qilmaslik uchun."""

    def __init__(self):
        self.departments = list(Department.objects.all())
        self.faculties = list(Faculty.objects.all())
        self.dept_by_id = {d.id: d for d in self.departments}
        self.fac_by_id = {f.id: f for f in self.faculties}
        self.members, self.headed, self.deaned = {}, {}, {}
        for d in self.departments:
            for tid in d.teachers._ids():
                self.members.setdefault(tid, []).append(d.id)
            if d.head_of_department_id:
                self.headed.setdefault(d.head_of_department_id, []).append(d.id)
        for f in self.faculties:
            if f.dean_id:
                self.deaned.setdefault(f.dean_id, []).append(f.id)


def _row(teacher, user, idx):
    groups = set((user.groups or []) if user else [])
    headed = idx.headed.get(teacher.id, []) if teacher else []
    deaned = idx.deaned.get(teacher.id, []) if teacher else []
    if user is not None and is_application_admin(user):
        rol, unvon = 'admin', 'Administrator'
    elif 'oquv_bolimi' in groups:
        rol, unvon = 'oquv_bolimi', "O'quv bo'limi"
    elif deaned:
        rol = 'dekan'
        unvon = ', '.join(f'{idx.fac_by_id[i].name} dekani' for i in deaned)
    elif headed:
        rol = 'kafedra_mudiri'
        unvon = ', '.join(f'{idx.dept_by_id[i].name} kafedrasi mudiri' for i in headed)
    else:
        rol, unvon = 'oqituvchi', "O'qituvchi"
    kafedralar = idx.members.get(teacher.id, []) if teacher else []
    if teacher is None:  # o'qituvchi profili yo'q hisob (masalan administrator) — faqat ko'rsatiladi
        fio = f'{user.last_name} {user.first_name}'.strip() or user.email
    return {
        'id': teacher.id if teacher else None,
        'fio': teacher.full_name if teacher else fio,
        'telefon': (teacher.phone_number if teacher else '') or '',
        'pochta': (user.email if user else teacher.email) or '',
        'lavozim': teacher.position if teacher else '',
        'userId': user.id if user else None,
        'hisob': user is not None,
        'faol': bool(user.is_active) if user else False,
        'rol': rol,
        'unvon': unvon,
        'kafedraIds': kafedralar,
        'kafedralar': [idx.dept_by_id[i].name for i in kafedralar],
        'mudirKafedraIds': headed,
        'dekanFakultetIds': deaned,
    }


def _int_or_error(value):
    if value in (None, ''):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _validate_role(data, idx, current_kafedra_ids, teacher_id=None):
    """Rol va unga kerakli kafedra/fakultetni tekshiradi: (rol, kafedra_id, fakultet_id).

    Har bir fakultetda bitta dekan, har bir kafedrada bitta mudir: o'rin band bo'lsa — rad etiladi
    (avval amaldagi dekan/mudirni boshqa rolga o'tkazish kerak)."""
    rol = data.get('rol') or 'oqituvchi'
    if rol not in ROLLAR:
        raise _Abort(_bad('rol', "Rol noto'g'ri. Mumkin: " + ', '.join(ROLLAR)))
    kafedra_id = _int_or_error(data.get('kafedraId'))
    fakultet_id = _int_or_error(data.get('fakultetId'))
    if kafedra_id is not None and kafedra_id not in idx.dept_by_id:
        raise _Abort(_bad('kafedraId', 'Kafedra topilmadi.'))
    if fakultet_id is not None and fakultet_id not in idx.fac_by_id:
        raise _Abort(_bad('fakultetId', 'Fakultet topilmadi.'))
    if rol in ('oqituvchi', 'kafedra_mudiri') and kafedra_id is None and not current_kafedra_ids:
        raise _Abort(_bad('kafedraId', 'Kafedrani tanlang.'))
    if rol == 'kafedra_mudiri' and kafedra_id is None:
        kafedra_id = current_kafedra_ids[0]
    if rol == 'dekan' and fakultet_id is None:
        raise _Abort(_bad('fakultetId', 'Fakultetni tanlang.'))
    if rol == 'kafedra_mudiri':
        band = idx.dept_by_id[kafedra_id].head_of_department_id
        if band and band != teacher_id:
            fio = getattr(Teacher.objects.filter(pk=band).first(), 'full_name', '')
            raise _Abort(_bad('kafedraId', f"Bu kafedraga mudir allaqachon tayinlangan: {fio}. "
                                           "Avval uni boshqa rolga o'tkazing."))
    if rol == 'dekan':
        band = idx.fac_by_id[fakultet_id].dean_id
        if band and band != teacher_id:
            fio = getattr(Teacher.objects.filter(pk=band).first(), 'full_name', '')
            raise _Abort(_bad('fakultetId', f"Bu fakultetga dekan allaqachon tayinlangan: {fio}. "
                                            "Avval uni boshqa rolga o'tkazing."))
    return rol, kafedra_id, fakultet_id


def _set_membership(teacher, kafedra_id, idx):
    """Asosiy kafedra: bitta kafedrada bo'lsa — ko'chiriladi, bir nechtasida bo'lsa — qo'shiladi."""
    if kafedra_id is None:
        return
    current = idx.members.get(teacher.id, [])
    if kafedra_id in current:
        return
    if len(current) == 1:
        idx.dept_by_id[current[0]].teachers.remove(teacher)
    idx.dept_by_id[kafedra_id].teachers.add(teacher)


def _apply_role(teacher, user, rol, kafedra_id, fakultet_id, idx):
    """Eski rol belgilarini olib, yangisini qo'yadi. O'rni olingan odamlar ro'yxatini qaytaradi."""
    replaced = []
    for d in idx.departments:
        if d.head_of_department_id == teacher.id and not (rol == 'kafedra_mudiri' and d.id == kafedra_id):
            d.head_of_department_id = None
            d.save()
    for f in idx.faculties:
        if f.dean_id == teacher.id and not (rol == 'dekan' and f.id == fakultet_id):
            f.dean_id = None
            f.save()
    if rol == 'kafedra_mudiri':
        d = idx.dept_by_id[kafedra_id]
        if d.head_of_department_id != teacher.id:
            old = Teacher.objects.filter(pk=d.head_of_department_id).first() if d.head_of_department_id else None
            if old:
                replaced.append(f'{old.full_name} — {d.name} kafedrasi mudiri edi')
            d.head_of_department_id = teacher.id
            d.save()
    if rol == 'dekan':
        f = idx.fac_by_id[fakultet_id]
        if f.dean_id != teacher.id:
            old = Teacher.objects.filter(pk=f.dean_id).first() if f.dean_id else None
            if old:
                replaced.append(f'{old.full_name} — {f.name} dekani edi')
            f.dean_id = teacher.id
            f.save()
    if user is not None:
        groups = [g for g in (user.groups or []) if g not in ROLE_GROUPS]
        if rol == 'oquv_bolimi':
            groups.append('oquv_bolimi')
        if groups != list(user.groups or []):
            user.groups = groups
            user.save(update_fields=['groups'])
    elif rol == 'oquv_bolimi':
        raise _Abort(_bad('rol', "O'quv bo'limi roli uchun pochta va parol (kirish hisobi) kerak."))
    return replaced


def _check_password(password, user):
    try:
        validate_password(password, user)
    except ValidationError as exc:
        raise _Abort(_bad('parol', ' '.join(exc.messages)))


def _check_email(email):
    if not email:
        raise _Abort(_bad('pochta', 'Elektron pochtani kiriting.'))
    try:
        validate_email(email)
    except ValidationError:
        raise _Abort(_bad('pochta', "To'g'ri elektron pochta manzilini kiriting.")) from None


def _email_free(email, teacher=None):
    taken = User.objects.filter(email__iexact=email).first()
    own = _find_user(teacher) if teacher is not None else None
    if taken is not None and (own is None or taken.id != own.id):
        raise _Abort(_bad('pochta', 'Bu pochta bilan hisob allaqachon mavjud.'))
    other = Teacher.objects.filter(email__iexact=email).first()
    if teacher is not None and other is not None and other.id != teacher.id:
        raise _Abort(_bad('pochta', "Bu pochta boshqa o'qituvchiga yozilgan."))


def _names(fio):
    parts = fio.split()
    return (parts[1] if len(parts) > 1 else ''), (parts[0] if parts else '')


def _create_account(teacher, email, password):
    first, last = _names(teacher.full_name)
    probe = User(username=_username(email), email=email, first_name=first, last_name=last)
    _check_password(password, probe)
    user = User.objects.create_user(username=probe.username, email=email, password=password,
                                    first_name=first, last_name=last)
    teacher.user = user
    teacher.email = email
    teacher.save()
    return user


def _lavozim(data, default):
    lavozim = data.get('lavozim') or default
    if lavozim not in TeacherPosition.values:
        raise _Abort(_bad('lavozim', "Lavozim noto'g'ri."))
    return lavozim


def _find_user(teacher):
    """Profilga bog'langan hisob; bog'lanmagan bo'lsa — shu pochtali hisob (masalan admin hisobi)."""
    if teacher.user_id:
        return User.objects.filter(pk=teacher.user_id).first()
    if teacher.email:
        return User.objects.filter(email__iexact=teacher.email).first()
    return None


def _respond(teacher, status_code=status.HTTP_200_OK, **extra):
    return Response({**_row(teacher, _find_user(teacher), _Index()), **extra}, status=status_code)


@api_view(['GET', 'POST'])
@permission_classes([IsAdminOrHead])
def foydalanuvchilar(request):
    """GET — barcha xodimlar va rollari. POST — yangi xodim: {fio, telefon, pochta, parol, lavozim, rol,
    kafedraId, fakultetId}. Shu pochtali o'qituvchi profili bo'lsa (hisobsiz), unga bog'lanadi."""
    idx = _Index()
    is_admin = is_application_admin(request.user)
    if request.method == 'POST' and not is_admin:
        return Response({'detail': "Yangi xodimni administrator qo'shadi."}, status=status.HTTP_403_FORBIDDEN)
    if request.method == 'GET' and not is_admin:
        # Kafedra mudiri: faqat o'z kafedrasi o'qituvchilari (kirish hisobini berish uchun)
        own = set(user_scope(request.user).department_ids)
        users = {u.id: u for u in User.objects.all()}
        rows = []
        for t in Teacher.objects.all():
            if set(idx.members.get(t.id, [])) & own:
                rows.append(_row(t, users.get(t.user_id) if t.user_id else _find_user(t), idx))
        return Response(rows)
    if request.method == 'GET':
        users = list(User.objects.all())
        by_id = {u.id: u for u in users}
        by_email = {(u.email or '').lower(): u for u in users if u.email}
        rows, shown = [], set()
        for t in Teacher.objects.all():
            user = by_id.get(t.user_id) if t.user_id else by_email.get((t.email or '').lower())
            if user is not None:
                shown.add(user.id)
            rows.append(_row(t, user, idx))
        rows += [_row(None, u, idx) for u in users if u.id not in shown]
        return Response(rows)

    data = request.data
    try:
        fio = ' '.join(str(data.get('fio') or '').split())
        if not fio:
            raise _Abort(_bad('fio', 'FIO ni kiriting.'))
        email = str(data.get('pochta') or '').strip().lower()
        _check_email(email)
        if not data.get('parol'):
            raise _Abort(_bad('parol', 'Parolni kiriting.'))
        teacher = Teacher.objects.filter(email__iexact=email).first()
        if (teacher is not None and teacher.user_id) or User.objects.filter(email__iexact=email).exists():
            raise _Abort(_bad('pochta', 'Bu pochta bilan hisob allaqachon mavjud.'))
        lavozim = _lavozim(data, teacher.position if teacher else TeacherPosition.TEACHER)
        rol, kafedra_id, fakultet_id = _validate_role(data, idx, idx.members.get(teacher.id, []) if teacher else [],
                                                      teacher.id if teacher else None)
        telefon = str(data.get('telefon') or '').strip()
        with atomic():
            if teacher is None:
                teacher = Teacher.objects.create(full_name=fio, email=email, position=lavozim, phone_number=telefon,
                                                 faqat_xodim=True)
            else:
                teacher.full_name = fio
                teacher.position = lavozim
                teacher.phone_number = telefon or teacher.phone_number
                teacher.save()
            user = _create_account(teacher, email, data['parol'])
            _set_membership(teacher, kafedra_id, idx)
            replaced = _apply_role(teacher, user, rol, kafedra_id, fakultet_id, idx)
    except _Abort as exc:
        return exc.response
    return _respond(teacher, status.HTTP_201_CREATED, almashtirildi=replaced)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAdminOrHead])
def foydalanuvchi(request, teacher_id):
    """PATCH — istalgan maydon: fio, telefon, pochta, lavozim, rol (+kafedraId/fakultetId), faol.
    Hisobi yo'q profilga pochta + parol berilsa, kirish hisobi ochiladi."""
    teacher = Teacher.objects.filter(pk=teacher_id).first()
    if teacher is None:
        return Response({'detail': 'Foydalanuvchi topilmadi.'}, status=status.HTTP_404_NOT_FOUND)
    idx = _Index()
    try:
        _head_guard(request, teacher, idx)
    except _Abort as exc:
        return exc.response
    if request.method == 'GET':
        return _respond(teacher)

    data = request.data
    user = _find_user(teacher)
    replaced = []
    if not is_application_admin(request.user) and set(data.keys()) - HEAD_FIELDS:
        return Response({'detail': "Kafedra mudiri faqat kirish hisobini (pochta, parol, holat) boshqaradi."},
                        status=status.HTTP_403_FORBIDDEN)
    try:
        if user is not None and is_application_admin(user) and ('rol' in data or 'faol' in data):
            raise _Abort(_bad('rol', "Administrator rolini va holatini bu yerdan o'zgartirib bo'lmaydi."))
        email = None
        if 'pochta' in data:
            email = str(data.get('pochta') or '').strip().lower()
            _check_email(email)
            _email_free(email, teacher)
        if user is None and data.get('parol') and not (email or teacher.email):
            raise _Abort(_bad('pochta', 'Kirish hisobi uchun pochtani kiriting.'))
        role_args = None
        if 'rol' in data:
            role_args = _validate_role(data, idx, idx.members.get(teacher.id, []), teacher.id)
        lavozim = _lavozim(data, teacher.position) if 'lavozim' in data else None
        with atomic():
            if 'fio' in data:
                fio = ' '.join(str(data.get('fio') or '').split())
                if not fio:
                    raise _Abort(_bad('fio', 'FIO ni kiriting.'))
                teacher.full_name = fio
            if 'telefon' in data:
                teacher.phone_number = str(data.get('telefon') or '').strip()
            if lavozim:
                teacher.position = lavozim
            if email:
                teacher.email = email
            teacher.save()
            if user is None and data.get('parol'):
                user = _create_account(teacher, email or teacher.email.lower(), data['parol'])
            elif user is not None:
                changed = []
                if email and email != user.email:
                    user.email = email
                    user.username = _username(email)
                    changed += ['email', 'username']
                if 'fio' in data:
                    user.first_name, user.last_name = _names(teacher.full_name)
                    changed += ['first_name', 'last_name']
                if 'faol' in data:
                    if user.id == request.user.id:
                        raise _Abort(_bad('faol', "O'zingizni bloklay olmaysiz."))
                    user.is_active = bool(data.get('faol'))
                    changed.append('is_active')
                if changed:
                    user.save(update_fields=changed)
            if role_args is not None:
                rol, kafedra_id, fakultet_id = role_args
                _set_membership(teacher, kafedra_id, idx)
                replaced = _apply_role(teacher, user, rol, kafedra_id, fakultet_id, idx)
    except _Abort as exc:
        return exc.response
    return _respond(teacher, almashtirildi=replaced)


@api_view(['POST'])
@permission_classes([IsAdminOrHead])
def foydalanuvchi_parol(request, teacher_id):
    """Admin xodimga yangi parol beradi: {parol}. Hisobi bo'lmasa — 400 (avval pochta bilan hisob oching)."""
    teacher = Teacher.objects.filter(pk=teacher_id).first()
    if teacher is None:
        return Response({'detail': 'Foydalanuvchi topilmadi.'}, status=status.HTTP_404_NOT_FOUND)
    try:
        _head_guard(request, teacher, _Index())
    except _Abort as exc:
        return exc.response
    user = _find_user(teacher)
    if user is None:
        return _bad('parol', "Bu xodimning kirish hisobi yo'q.")
    password = request.data.get('parol') or ''
    if not password:
        return _bad('parol', 'Parolni kiriting.')
    try:
        _check_password(password, user)
    except _Abort as exc:
        return exc.response
    user.set_password(password)
    user.save()
    return Response({'detail': "Parol o'rnatildi."})


urlpatterns = [
    path('foydalanuvchilar', foydalanuvchilar),
    path('foydalanuvchilar/<int:teacher_id>', foydalanuvchi),
    path('foydalanuvchilar/<int:teacher_id>/parol', foydalanuvchi_parol),
]
