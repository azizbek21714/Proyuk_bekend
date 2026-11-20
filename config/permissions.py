from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission


def is_application_admin(user):
    """Application admins are superusers or members of the explicit admin group."""
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or 'admin' in (getattr(user, 'groups', None) or []))
    )


def limit_to_own(queryset, user, teacher_lookup='teacher'):
    """Administrator hammasini ko'radi; boshqa foydalanuvchi faqat o'ziga tegishli
    yozuvlarni (o'qituvchi profili orqali bog'langan) ko'radi.

    teacher_lookup — querysetdan Teacher modeligacha yo'l ('' — querysetning o'zi Teacher).
    """
    if is_application_admin(user):
        return queryset
    field = f'{teacher_lookup}__user' if teacher_lookup else 'user'
    return queryset.filter(**{field: user})


def _scope(user):
    from apps.accounts.roles import user_scope
    return user_scope(user)


def scope_filter(queryset, user, departments_of=None, teacher_of=None, teacher_lookup=None):
    """Rolga qarab querysetni cheklaydi.

    admin / o'quv bo'limi — hammasi;
    dekan / kafedra mudiri — departments_of(obj) hududdagi kafedralar bilan kesishsa
        (yoki teacher_of(obj) foydalanuvchining o'zi bo'lsa);
    o'qituvchi — avvalgidek: teacher_lookup berilgan bo'lsa faqat o'ziniki, aks holda o'zgarishsiz.
    """
    scope = _scope(user)
    if scope.is_global:
        return queryset
    if scope.role in ('dekan', 'kafedra_mudiri'):
        allowed = scope.department_ids
        own = scope.teacher_id

        def visible(obj):
            if teacher_of is not None and own is not None and teacher_of(obj) == own:
                return True
            if departments_of is None:
                return False
            return bool(set(departments_of(obj)) & allowed)

        return queryset.filter_fn(visible)
    if teacher_lookup is None:
        return queryset
    return limit_to_own(queryset, user, teacher_lookup)


def require_departments(user, department_ids):
    """Yozish amali: barcha kafedralar foydalanuvchi hududida bo'lishi shart (admin — doim)."""
    scope = _scope(user)
    if scope.is_admin:
        return
    ids = [d for d in department_ids if d is not None]
    if not ids or not all(scope.has_department(d) for d in ids):
        raise PermissionDenied("Bu amal faqat o'z kafedrangiz (fakultetingiz) doirasida ruxsat etilgan.")


class IsApplicationAdmin(BasePermission):
    message = "Bu amal faqat administrator uchun ruxsat etilgan."

    def has_permission(self, request, view):
        return is_application_admin(request.user)


class IsApplicationAdminOrAuthenticatedReadOnly(BasePermission):
    """All reads require login; mutations require an application administrator."""
    message = "Bu amal faqat administrator uchun ruxsat etilgan."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.method in SAFE_METHODS or is_application_admin(request.user)


class RolePermission(IsApplicationAdminOrAuthenticatedReadOnly):
    """Admin uchun avvalgidek. Qo'shimcha: view.role_write ro'yxatidagi rollar ham yozishi mumkin
    (hudud tekshiruvi view ichida require_departments orqali qilinadi)."""

    def has_permission(self, request, view):
        if super().has_permission(request, view):
            return True
        if not request.user or not request.user.is_authenticated:
            return False
        allowed = getattr(view, 'role_write', ())
        return _scope(request.user).role in allowed
