"""Foydalanuvchi roli va hududi (qaysi kafedra/fakultet ma'lumotlarini ko'ra oladi).

Rol tartibi (birinchi mos kelgani asosiy rol):
  admin          — superuser yoki 'admin' guruhi: hammasi
  oquv_bolimi    — 'oquv_bolimi' guruhi: faqat o'ziga biriktirilgan OTM (User.otm_id) fakultet va kafedralari
  dekan          — o'qituvchi profili Faculty.dean bo'lsa: fakultet(lar) va undagi kafedralar
  kafedra_mudiri — o'qituvchi profili Department.head_of_department bo'lsa: kafedra(lar)
  oqituvchi      — faqat o'zi

Eski 'dekan' / 'kafedra_mudiri' guruhlari ham rol beradi, lekin hududi (kafedrasi/fakulteti)
belgilanmagan bo'ladi — bunday foydalanuvchi hech qanday kafedra ma'lumotini ko'rmaydi.
"""
from dataclasses import dataclass, field

ROLE_ORDER = ('admin', 'oquv_bolimi', 'dekan', 'kafedra_mudiri', 'oqituvchi')
GLOBAL_ROLES = ('admin',)
UNIT_ROLES = ('oquv_bolimi', 'dekan', 'kafedra_mudiri')


@dataclass
class Scope:
    role: str = 'oqituvchi'
    roles: list = field(default_factory=list)
    teacher: object = None
    department_ids: frozenset = frozenset()   # yozish/tekshirish huquqi bor kafedralar
    headed_department_ids: frozenset = frozenset()  # mudiri bo'lgan kafedralar
    faculty_ids: frozenset = frozenset()      # dekan bo'lgan fakultetlar
    visible_faculty_ids: frozenset = frozenset()
    visible_otm_ids: frozenset = frozenset()
    otm_ids: frozenset = frozenset()          # o'quv bo'limi bo'lgan OTM(lar)
    label: str = ''
    dept_faculty: dict = field(default_factory=dict)  # kafedra id -> fakultet id (hammasi)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_global(self):
        return self.role in GLOBAL_ROLES

    @property
    def teacher_id(self):
        return self.teacher.id if self.teacher is not None else None

    def has_department(self, department_id):
        if self.is_global:
            return True
        try:
            return int(department_id) in self.department_ids
        except (TypeError, ValueError):
            return False

    def as_dict(self):
        return {
            'role': self.role,
            'rollar': list(self.roles),
            'kafedraIds': sorted(self.department_ids),
            'fakultetIds': sorted(self.faculty_ids),
            'oqituvchiId': self.teacher_id,
            'unvon': self.label,
        }


_CACHE_ATTR = '_proyuk_scope'


def user_scope(user):
    """Foydalanuvchi uchun Scope (bitta so'rov davomida user obyektida keshlanadi)."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return Scope(role='anonim')
    cached = getattr(user, _CACHE_ATTR, None)
    if cached is not None:
        return cached
    scope = _build_scope(user)
    try:
        setattr(user, _CACHE_ATTR, scope)
    except Exception:  # noqa: BLE001
        pass
    return scope


def _build_scope(user):
    from apps.departments.models import Department, Faculty
    from config.permissions import is_application_admin

    groups = set(getattr(user, 'groups', None) or [])
    teacher = getattr(user, 'teacher_profile', None)

    departments = list(Department.objects.all())
    faculties = list(Faculty.objects.all())
    dept_faculty = {d.id: d.faculty_id for d in departments}
    faculty_otm = {f.id: f.otm_id for f in faculties}

    deaned = [f for f in faculties if teacher is not None and f.dean_id == teacher.id]
    headed = [d for d in departments if teacher is not None and d.head_of_department_id == teacher.id]

    roles = []
    if is_application_admin(user):
        roles.append('admin')
    if 'oquv_bolimi' in groups:
        roles.append('oquv_bolimi')
    if deaned or 'dekan' in groups:
        roles.append('dekan')
    if headed or 'kafedra_mudiri' in groups:
        roles.append('kafedra_mudiri')
    roles.append('oqituvchi')
    role = next(r for r in ROLE_ORDER if r in roles)

    # O'quv bo'limi: biriktirilgan OTM (bo'lmasa — xodimning kafedrasi joylashgan OTM)
    otm_ids = frozenset()
    if 'oquv_bolimi' in roles:
        otm = getattr(user, 'otm_id', None)
        if otm is None and teacher is not None:
            own = [d.faculty_id for d in departments if teacher.id in set(d.teachers._ids())]
            otms = {faculty_otm.get(f) for f in own} - {None}
            otm = next(iter(otms)) if len(otms) == 1 else None
        otm_ids = frozenset({otm}) if otm is not None else frozenset()
    otm_department_ids = frozenset(d_id for d_id, f_id in dept_faculty.items() if faculty_otm.get(f_id) in otm_ids)

    faculty_ids = frozenset(f.id for f in deaned)
    department_ids = frozenset(
        {d.id for d in headed} | {d_id for d_id, f_id in dept_faculty.items() if f_id in faculty_ids}
        | otm_department_ids
    )
    visible_faculty_ids = frozenset(faculty_ids | {dept_faculty[d] for d in department_ids})
    visible_faculty_ids = frozenset(visible_faculty_ids | {f.id for f in faculties if f.otm_id in otm_ids})
    visible_otm_ids = frozenset({faculty_otm[f] for f in visible_faculty_ids if f in faculty_otm} | otm_ids)

    if role == 'admin':
        label = 'Administrator'
    elif role == 'oquv_bolimi':
        from apps.departments.models import OTM
        otm_obj = OTM.objects.filter(pk=next(iter(otm_ids))).first() if otm_ids else None
        label = f"{otm_obj.short_name or otm_obj.name} o'quv bo'limi" if otm_obj else "O'quv bo'limi"
    elif role == 'dekan':
        label = ', '.join(f'{f.name} dekani' for f in deaned) or 'Dekan'
    elif role == 'kafedra_mudiri':
        label = ', '.join(f'{d.name} kafedrasi mudiri' for d in headed) or 'Kafedra mudiri'
    else:
        label = ''

    return Scope(
        role=role, roles=roles, teacher=teacher,
        department_ids=department_ids, faculty_ids=faculty_ids,
        headed_department_ids=frozenset(d.id for d in headed),
        visible_faculty_ids=visible_faculty_ids, visible_otm_ids=visible_otm_ids, otm_ids=otm_ids,
        label=label, dept_faculty=dept_faculty,
    )
