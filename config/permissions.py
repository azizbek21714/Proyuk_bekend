from rest_framework.permissions import SAFE_METHODS, BasePermission


def is_application_admin(user):
    """Application admins are superusers or members of the explicit admin group."""
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.groups.filter(name='admin').exists())
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
