from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from apps.accounts.roles import user_scope
from apps.core.drf import ODMModelViewSet
from config.permissions import require_departments, scope_filter
from .models import OTM, Faculty, Department
from .serializers import OTMSerializer, FacultySerializer, DepartmentSerializer


def _admin_only(user):
    if not user_scope(user).is_admin:
        raise PermissionDenied("Bu amal faqat administrator uchun ruxsat etilgan.")


class OTMViewSet(ODMModelViewSet):
    queryset = OTM.objects.all()
    serializer_class = OTMSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        scope = user_scope(self.request.user)
        if scope.role in ('dekan', 'kafedra_mudiri'):
            qs = qs.filter_fn(lambda o: o.id in scope.visible_otm_ids)
        return qs

    @action(detail=False, methods=['get', 'post'], url_path='hierarchy')
    def hierarchy(self, request):
        if request.method == 'GET':
            return self._hierarchy_get()
        return self._hierarchy_post(request)

    def _hierarchy_get(self):
        """OTM → Fakultet → Kafedra daraxt strukturasi"""
        data = []
        scope = user_scope(self.request.user)
        limited = scope.role in ('dekan', 'kafedra_mudiri')
        for otm in OTM.objects.prefetch_related('faculties__departments').all():
            if limited and otm.id not in scope.visible_otm_ids:
                continue
            faculties = []
            for faculty in otm.faculties.all():
                if limited and faculty.id not in scope.visible_faculty_ids:
                    continue
                departments = list(faculty.departments.values('id', 'name', 'yillik_yuklama'))
                if limited:
                    departments = [d for d in departments if d['id'] in scope.department_ids]
                faculties.append({
                    'id': faculty.id,
                    'name': faculty.name,
                    'kafedralar': departments,
                })
            data.append({
                'id': otm.id,
                'name': otm.name,
                'short_name': otm.short_name,
                'fakultetlar': faculties,
            })
        return Response(data)

    def _hierarchy_post(self, request):
        """OTM + Fakultet + Kafedra birdan yaratish"""
        otm_nomi = request.data.get('otmNomi', '').strip()
        otm_qisqa = request.data.get('otmQisqaNomi', '').strip()
        fakultet_nomi = request.data.get('fakultetNomi', '').strip()
        kafedra_nomi = request.data.get('kafedraNomi', '').strip()

        if not all([otm_nomi, fakultet_nomi, kafedra_nomi]):
            return Response(
                {'detail': 'otmNomi, fakultetNomi va kafedraNomi majburiy.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        otm, otm_created = OTM.objects.get_or_create(
            name=otm_nomi,
            defaults={'short_name': otm_qisqa},
        )
        fakultet, _ = Faculty.objects.get_or_create(
            name=fakultet_nomi,
            otm=otm,
        )
        kafedra, created = Department.objects.get_or_create(
            name=kafedra_nomi,
            faculty=fakultet,
        )

        return Response({
            'otm': {'id': otm.id, 'name': otm.name, 'short_name': otm.short_name},
            'fakultet': {'id': fakultet.id, 'name': fakultet.name},
            'kafedra': {'id': kafedra.id, 'name': kafedra.name},
            'created': created,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class FacultyViewSet(ODMModelViewSet):
    queryset = Faculty.objects.select_related('otm', 'dean').all()
    serializer_class = FacultySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        scope = user_scope(self.request.user)
        if scope.role in ('dekan', 'kafedra_mudiri'):
            qs = qs.filter_fn(lambda f: f.id in scope.visible_faculty_ids)
        otm_id = self.request.query_params.get('otmId')
        if otm_id:
            qs = qs.filter(otm_id=otm_id)
        return qs


class DepartmentViewSet(ODMModelViewSet):
    queryset = Department.objects.select_related('faculty', 'head_of_department').prefetch_related('teachers').all()
    serializer_class = DepartmentSerializer
    # Kafedra mudiri o'z kafedrasining o'qituvchilar ro'yxati va yuklamasini o'zgartira oladi
    role_write = ('kafedra_mudiri',)
    MUDIR_FIELDS = {'teachers', 'yillik_yuklama', 'yuklama_data'}

    def get_queryset(self):
        qs = scope_filter(super().get_queryset(), self.request.user, departments_of=lambda d: [d.id])
        fakultet_id = self.request.query_params.get('fakultetId')
        otm_id = self.request.query_params.get('otmId')
        if fakultet_id:
            qs = qs.filter(faculty_id=fakultet_id)
        if otm_id:
            qs = qs.filter(faculty__otm_id=otm_id)
        return qs

    def perform_create(self, serializer):
        _admin_only(self.request.user)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        user = self.request.user
        if not user_scope(user).is_admin:
            require_departments(user, [serializer.instance.id])
            instance = serializer.instance

            def changed(name, value):
                old = getattr(instance, name, None)
                old = getattr(old, 'pk', old)
                return getattr(value, 'pk', value) != old

            # Frontend butun formani yuboradi — faqat haqiqatan o'zgargan maydonlar tekshiriladi
            extra = {k for k, v in serializer.validated_data.items()
                     if k not in self.MUDIR_FIELDS and changed(k, v)}
            if extra:
                raise PermissionDenied(
                    "Kafedra mudiri faqat o'qituvchilar ro'yxati va yuklamani o'zgartira oladi.")
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        _admin_only(self.request.user)
        super().perform_destroy(instance)
