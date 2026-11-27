from rest_framework.exceptions import PermissionDenied

from apps.accounts.roles import UNIT_ROLES, user_scope
from apps.core.drf import ODMModelViewSet
from apps.departments.models import Department
from .models import Teacher
from .serializers import TeacherSerializer
from config.permissions import require_departments, scope_filter


def teacher_departments():
    """O'qituvchi id -> kafedra id'lari (Department.teachers M2M bo'yicha)."""
    mapping = {}
    for dep in Department.objects.all():
        for teacher in dep.teachers.all():
            mapping.setdefault(teacher.id, []).append(dep.id)
    return mapping


class TeacherViewSet(ODMModelViewSet):
    queryset = Teacher.objects.all()
    serializer_class = TeacherSerializer
    # Kafedra mudiri o'z kafedrasi o'qituvchilarini qo'sha va tahrirlay oladi
    role_write = ('kafedra_mudiri',)

    def get_queryset(self):
        # Telefon va pochta shaxsiy ma'lumot: administrator bo'lmagan foydalanuvchi
        # faqat o'z profilini (rahbarlar — o'z hududidagilarni) ko'radi.
        scope = user_scope(self.request.user)
        qs = super().get_queryset()
        if scope.role in UNIT_ROLES:
            mapping = teacher_departments()
            qs = scope_filter(qs, self.request.user,
                              departments_of=lambda t: mapping.get(t.id, []),
                              teacher_of=lambda t: t.id)
        else:
            qs = scope_filter(qs, self.request.user, teacher_lookup='')
        params = self.request.query_params
        # Kafedra (Department.teachers M2M, related_name='departments')
        if params.get('kafedraId'):
            qs = qs.filter(departments__id=params['kafedraId'])
        if params.get('fakultetId'):
            qs = qs.filter(departments__faculty_id=params['fakultetId'])
        if params.get('otmId'):
            qs = qs.filter(departments__faculty__otm_id=params['otmId'])
        # Stavka (rate)
        if params.get('rate'):
            qs = qs.filter(rate=params['rate'])
        # Foydalanuvchilar bo'limidan qo'shilgan xodimlar o'qituvchilar ro'yxatida chiqmaydi
        if getattr(self, 'action', None) == 'list':
            qs = qs.filter_fn(lambda t: not getattr(t, 'faqat_xodim', False))
        return qs.distinct()

    def _check_fields(self, serializer):
        if not user_scope(self.request.user).is_admin and 'user' in serializer.validated_data:
            raise PermissionDenied("Foydalanuvchi hisobini faqat administrator bog'lay oladi.")

    def perform_create(self, serializer):
        self._check_fields(serializer)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self._check_fields(serializer)
        if not user_scope(self.request.user).is_admin:
            require_departments(self.request.user, teacher_departments().get(serializer.instance.id, []))
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        if not user_scope(self.request.user).is_admin:
            require_departments(self.request.user, teacher_departments().get(instance.id, []))
        super().perform_destroy(instance)
