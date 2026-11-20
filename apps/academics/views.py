from apps.accounts.roles import user_scope
from apps.core.drf import ODMModelViewSet
from config.permissions import require_departments, scope_filter
from .models import Subject, Group, DlMd
from .serializers import (
    SubjectSerializer,
    GroupSerializer,
    DlMdSerializer,
)


class _DepartmentScopedMixin:
    """Fan/guruh: kafedra mudiri o'z kafedrasida yozadi, rahbarlar hududini ko'radi."""
    role_write = ('kafedra_mudiri',)

    def _scoped(self, qs):
        return scope_filter(qs, self.request.user, departments_of=lambda o: [o.department_id])

    def _require(self, *department_ids):
        if not user_scope(self.request.user).is_admin:
            require_departments(self.request.user, department_ids)

    def perform_create(self, serializer):
        dep = serializer.validated_data.get('department')
        self._require(dep.id if dep else None)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        dep = serializer.validated_data.get('department', serializer.instance.department)
        self._require(serializer.instance.department_id, dep.id if dep else None)
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        self._require(instance.department_id)
        super().perform_destroy(instance)


class SubjectViewSet(_DepartmentScopedMixin, ODMModelViewSet):
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer

    def get_queryset(self):
        qs = self._scoped(super().get_queryset())
        kafedra_id = self.request.query_params.get('kafedraId')
        if kafedra_id:
            qs = qs.filter(department_id=kafedra_id)
        return qs


class GroupViewSet(_DepartmentScopedMixin, ODMModelViewSet):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer

    def get_queryset(self):
        qs = self._scoped(super().get_queryset())
        params = self.request.query_params
        if params.get('kafedraId'):
            qs = qs.filter(department_id=params['kafedraId'])
        if params.get('fakultetId'):
            qs = qs.filter(department__faculty_id=params['fakultetId'])
        if params.get('otmId'):
            qs = qs.filter(department__faculty__otm_id=params['otmId'])
        if params.get('kurs'):
            kurs = params['kurs']
            qs = qs.filter(course=kurs if str(kurs).startswith('course_') else f'course_{kurs}')
        return qs


class DlMdViewSet(ODMModelViewSet):
    queryset = DlMd.objects.all()
    serializer_class = DlMdSerializer

