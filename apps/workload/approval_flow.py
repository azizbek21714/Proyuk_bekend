"""Shaxsiy reja tasdiqlash oqimi: kafedra mudiri → dekan → o'quv bo'limi.

Reja holatlari: loyiha → (yuborish) → tekshiruvda → tasdiqlangan | rad_etilgan.
Rad etilgan reja tuzatilib qayta yuboriladi (barcha bosqichlar boshidan).
Kafedra mudiri / dekanning o'z rejasida o'z bosqichi avtomatik o'tkaziladi.
"""
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import User, notify
from apps.accounts.roles import user_scope
from apps.core.odm import atomic
from apps.departments.models import Department, Faculty
from .models import Approval

STAGES = ('kafedra', 'dekan', 'oquv_bolimi')
STAGE_ROLE = {'kafedra': 'kafedra_mudiri', 'dekan': 'dekan', 'oquv_bolimi': 'oquv_bolimi'}
STAGE_LABEL = {'kafedra': 'Kafedra mudiri', 'dekan': 'Dekan', 'oquv_bolimi': "O'quv bo'limi"}
EDITABLE = ('loyiha', 'rad_etilgan')


def _approvals(reja):
    """Bosqichlar tartibida Approval yozuvlari (yo'qlari yaratiladi)."""
    existing = {a.stage: a for a in Approval.objects.filter(reja=reja)}
    result = []
    for stage in STAGES:
        approval = existing.get(stage)
        if approval is None:
            approval = Approval.objects.create(reja=reja, stage=stage)
        result.append(approval)
    return result


def next_approval(reja):
    if reja.status != 'tekshiruvda':
        return None
    return next((a for a in _approvals(reja) if a.state != 'tasdiqlangan'), None)


def _department(reja):
    return Department.objects.filter(pk=reja.department_id).first() if reja.department_id else None


def stage_approvers(reja, stage):
    """Bosqichni tasdiqlay oladigan foydalanuvchilar (xabar yuborish uchun)."""
    dep = _department(reja)
    if stage == 'kafedra':
        head = dep.head_of_department if dep else None
        return [head.user_id] if head and head.user_id else []
    if stage == 'dekan':
        faculty = Faculty.objects.filter(pk=dep.faculty_id).first() if dep else None
        dean = faculty.dean if faculty else None
        return [dean.user_id] if dean and dean.user_id else []
    return oquv_bolimi_users(reja.department_id)


def oquv_bolimi_users(department_id):
    """Shu kafedra joylashgan OTMning faol o'quv bo'limi xodimlari."""
    return [u.id for u in User.objects.all()
            if 'oquv_bolimi' in (u.groups or []) and u.is_active and user_scope(u).has_department(department_id)]


def can_act(user, reja, stage):
    scope = user_scope(user)
    if scope.is_admin:
        return True
    if STAGE_ROLE[stage] not in scope.roles:
        return False
    if stage == 'oquv_bolimi':
        return reja.department_id in scope.department_ids
    if scope.teacher_id is not None and reja.teacher_id == scope.teacher_id:
        return False  # o'z rejasini o'zi tasdiqlamaydi
    if stage == 'kafedra':
        return reja.department_id in scope.headed_department_ids
    return scope.dept_faculty.get(reja.department_id) in scope.faculty_ids


def _teacher_user_id(reja):
    teacher = reja.teacher
    return teacher.user_id if teacher else None


def _link(reja):
    return f'/dashboard/teacher/reja/{reja.id}'


def submit(user, reja):
    scope = user_scope(user)
    owner = scope.teacher_id is not None and reja.teacher_id == scope.teacher_id
    if not (owner or scope.is_admin):
        raise PermissionDenied("Rejani faqat uning egasi tasdiqlashga yubora oladi.")
    if reja.status not in EDITABLE:
        raise ValidationError({'detail': "Bu reja allaqachon tekshiruvda yoki tasdiqlangan."})
    now = timezone.now()
    dep = _department(reja)
    faculty = Faculty.objects.filter(pk=dep.faculty_id).first() if dep else None
    own_stage = {
        'kafedra': bool(dep and reja.teacher_id and dep.head_of_department_id == reja.teacher_id),
        'dekan': bool(faculty and reja.teacher_id and faculty.dean_id == reja.teacher_id),
    }
    with atomic():
        for approval in _approvals(reja):
            auto = own_stage.get(approval.stage, False)
            approval.state = 'tasdiqlangan' if auto else 'kutilmoqda'
            approval.comment = 'Rahbarning o\'z rejasi — bosqich avtomatik o\'tkazildi' if auto else ''
            approval.acted_by = None
            approval.acted_at = now if auto else None
            approval.save(update_fields=['state', 'comment', 'acted_by', 'acted_at'])
        reja.status = 'tekshiruvda'
        reja.yuborilgan_at = now
        reja.save(update_fields=['status', 'yuborilgan_at', 'edited_at'])
    pending = next_approval(reja)
    if pending is not None:
        fio = reja.teacher.full_name if reja.teacher else ''
        notify(stage_approvers(reja, pending.stage),
               f"{fio} shaxsiy ish rejasini tasdiqlashga yubordi.", _link(reja))
    return reja


def decide(user, reja, qaror, izoh):
    izoh = (izoh or '').strip()
    if qaror not in ('tasdiqlash', 'rad_etish'):
        raise ValidationError({'qaror': "Qaror 'tasdiqlash' yoki 'rad_etish' bo'lishi kerak."})
    if qaror == 'rad_etish' and not izoh:
        raise ValidationError({'izoh': "Rad etish sababini yozing."})
    approval = next_approval(reja)
    if approval is None:
        raise ValidationError({'detail': "Bu reja hozir tasdiqlash bosqichida emas."})
    if not can_act(user, reja, approval.stage):
        raise PermissionDenied(f"Hozirgi bosqich: {STAGE_LABEL[approval.stage]}. Sizda bu bosqich uchun huquq yo'q.")
    now = timezone.now()
    with atomic():
        approval.state = 'tasdiqlangan' if qaror == 'tasdiqlash' else 'rad_etilgan'
        approval.comment = izoh
        approval.acted_by = user
        approval.acted_at = now
        approval.save(update_fields=['state', 'comment', 'acted_by', 'acted_at'])
        if qaror == 'rad_etish':
            reja.status = 'rad_etilgan'
        elif approval.stage == STAGES[-1]:
            reja.status = 'tasdiqlangan'
        reja.save(update_fields=['status', 'edited_at'])
    label = STAGE_LABEL[approval.stage]
    if qaror == 'rad_etish':
        notify(_teacher_user_id(reja), f"Shaxsiy ish rejangiz rad etildi ({label}). Sabab: {izoh}", _link(reja))
    elif reja.status == 'tasdiqlangan':
        notify(_teacher_user_id(reja), "Shaxsiy ish rejangiz to'liq tasdiqlandi.", _link(reja))
    else:
        nxt = next_approval(reja)
        if nxt is not None:
            fio = reja.teacher.full_name if reja.teacher else ''
            notify(stage_approvers(reja, nxt.stage),
                   f"{fio} shaxsiy ish rejasi {label.lower()} tomonidan tasdiqlandi va sizga yuborildi.",
                   _link(reja))
    return reja


def pending_for(user, rejalar):
    """Foydalanuvchi hozir tasdiqlashi kerak bo'lgan (reja, approval) juftlari."""
    result = []
    for reja in rejalar:
        approval = next_approval(reja)
        if approval is not None and can_act(user, reja, approval.stage):
            result.append((reja, approval))
    return result
