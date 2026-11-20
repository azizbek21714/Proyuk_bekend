from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from .models import (
    Yuklama, Reja, DlMdBiriktirma, WorkloadType,
    WorkloadNorm, Assignment, Approval, AcademicYear,
    PositionNorm,
)
from .serializers import (
    YuklamaSerializer, RejaSerializer, DlMdBiriktirmaSerializer,
    WorkloadTypeSerializer, WorkloadNormSerializer, AssignmentSerializer,
    ApprovalSerializer, AcademicYearSerializer,
    PositionNormSerializer,
)
from .excel_parser import parse_workload_excel
from .importer import import_rows_to_yuklama, build_subjects_from_data
from apps.core.drf import ODMModelViewSet
from apps.core.odm import atomic
from apps.departments.models import Department
from .services import sync_reja_assignments
from apps.accounts.roles import user_scope
from config.permissions import require_departments, scope_filter


def _require(request, *department_ids):
    """Admin — doim ruxsat; boshqa rollar faqat o'z hududidagi kafedralar uchun."""
    if not user_scope(request.user).is_admin:
        require_departments(request.user, department_ids)


ALLOWED_EXCEL_EXTENSIONS = ('.xlsx', '.xlsm', '.xls')
MAX_EXCEL_SIZE = 10 * 1024 * 1024  # 10 MB


class YuklamaExcelImportView(APIView):
    """O'QUV YUKLAMASI HAJMI Excel faylini qabul qilib, ma'lumotlarni
    kuzgi va bahorgi semestrlarga ajratib qaytaradi.

    POST /api/crud/yuklama-excel/  (multipart/form-data)
      file          - Excel fayl (.xlsx/.xlsm/.xls), majburiy
      save          - "true" bo'lsa ma'lumot Yuklama jadvaliga yoziladi
      department_id - (ixtiyoriy) qaysi kafedraga bog'lanadi

    save=true bo'lmasa — faqat o'qib, oldindan ko'rish (preview) qaytaradi.
    """

    parser_classes = [MultiPartParser, FormParser]
    role_write = ('kafedra_mudiri',)

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if file_obj is None:
            return Response(
                {'detail': "Fayl yuborilmadi. 'file' maydonida Excel fayl yuboring."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        name = (file_obj.name or '').lower()
        if not name.endswith(ALLOWED_EXCEL_EXTENSIONS):
            return Response(
                {'detail': "Faqat .xlsx, .xlsm yoki .xls formatdagi Excel fayl qabul qilinadi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if file_obj.size and file_obj.size > MAX_EXCEL_SIZE:
            return Response(
                {'detail': "Fayl hajmi 10 MB dan oshmasligi kerak."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            data = parse_workload_excel(file_obj)
        except Exception as exc:  # noqa: BLE001 - foydalanuvchiga toza xabar qaytaramiz
            return Response(
                {'detail': f"Faylni o'qishda xatolik: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data['counts'] = {
            'kuzgi': len(data['kuzgi']),
            'bahorgi': len(data['bahorgi']),
        }

        save_flag = str(request.data.get('save', '')).lower() in ('1', 'true', 'yes', 'ha')
        if save_flag:
            department = None
            dep_id = request.data.get('department_id') or request.query_params.get('department_id')
            if dep_id:
                department = Department.objects.filter(pk=dep_id).first()
                if department is None:
                    return Response(
                        {'detail': f"department_id={dep_id} bo'yicha kafedra topilmadi."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            _require(request, department.id if department else None)

            with atomic():
                created = import_rows_to_yuklama(data, department=department)

                # Kafedra bo'lsa — shakllantirilgan yuklamani va yillik soatni saqlaymiz
                if department is not None:
                    department.yuklama_data = {
                        'meta': data['meta'],
                        'kuzgi': data['kuzgi'],
                        'bahorgi': data['bahorgi'],
                        'totals': data['totals'],
                    }
                    yillik = (data['totals'].get('yillik') or {}).get('jami')
                    if isinstance(yillik, (int, float)):
                        department.yillik_yuklama = int(yillik)
                    department.save(update_fields=['yuklama_data', 'yillik_yuklama', 'edited_at'])

            data['saved'] = True
            data['created'] = created
            data['created_counts'] = {
                'kuzgi': len(created['kuzgi']),
                'bahorgi': len(created['bahorgi']),
            }

        return Response(data, status=status.HTTP_200_OK)


class FanlarShakllantirView(APIView):
    """Kafedra yuklama_data sidan fanlarni (Subject) shakllantiradi (dedup bilan).

    POST /api/crud/fanlar-shakllantir/  body: { department_id }
    """
    role_write = ('kafedra_mudiri',)

    def post(self, request, *args, **kwargs):
        dep_id = request.data.get('department_id') or request.data.get('departmentId')
        department = Department.objects.filter(pk=dep_id).first() if dep_id else None
        if department is None:
            return Response(
                {'detail': "department_id bo'yicha kafedra topilmadi."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        _require(request, department.id)
        result = build_subjects_from_data(department)
        return Response(result, status=status.HTTP_200_OK)

    def delete(self, request, *args, **kwargs):
        """Kafedra yuklamasi va undan shakllangan barcha ma'lumotlarni o'chiradi:
        fanlar, Yuklama yozuvlari, o'qituvchilarning shaxsiy ish rejalari
        (biriktirmalar va tasdiqlashlar bilan) hamda DL/MD biriktirmalari."""
        from apps.academics.models import Subject
        dep_id = (request.query_params.get('department_id')
                  or request.query_params.get('departmentId')
                  or request.data.get('department_id'))
        department = Department.objects.filter(pk=dep_id).first() if dep_id else None
        if department is None:
            return Response(
                {'detail': "department_id bo'yicha kafedra topilmadi."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        _require(request, department.id)
        sub_count = Subject.objects.filter(department=department).count()
        reja_qs = Reja.objects.filter(department=department)
        dlmd_qs = DlMdBiriktirma.objects.filter(department=department)
        reja_count = reja_qs.count()
        dlmd_count = dlmd_qs.count()
        with atomic():
            # Rejalar kafedra yuklamasi nusxasidan tuzilgan — yuklamasiz ular eskirib qoladi.
            # Assignment va Approval yozuvlari CASCADE orqali birga o'chadi.
            reja_qs.delete()
            dlmd_qs.delete()
            Subject.objects.filter(department=department).delete()
            Yuklama.objects.filter(department=department).delete()
            department.yillik_yuklama = 0
            department.yuklama_data = {}
            department.save(update_fields=['yillik_yuklama', 'yuklama_data', 'edited_at'])
        return Response({
            'deleted_subjects': sub_count,
            'deleted_rejalar': reja_count,
            'deleted_dlmd': dlmd_count,
        }, status=status.HTTP_200_OK)


class KafedraYuklamaViewSet(ODMModelViewSet):
    queryset = Yuklama.objects.select_related(
        'department', 'department__faculty', 'group', 'subject',
        'subject__department', 'subject__department__faculty', 'dak', 'dl_md',
    ).all()
    serializer_class = YuklamaSerializer
    http_method_names = ['get', 'post', 'delete', 'head', 'options']
    role_write = ('kafedra_mudiri',)

    def get_queryset(self):
        qs = scope_filter(super().get_queryset(), self.request.user, departments_of=lambda o: [o.department_id])
        kafedra_id = self.request.query_params.get('kafedraId')
        if kafedra_id:
            qs = qs.filter(department_id=kafedra_id)
        return qs

    def perform_create(self, serializer):
        dep = serializer.validated_data.get('department')
        _require(self.request, dep.id if dep else None)
        super().perform_create(serializer)

    def perform_destroy(self, instance):
        _require(self.request, instance.department_id)
        super().perform_destroy(instance)


class RejaViewSet(ODMModelViewSet):
    queryset = Reja.objects.select_related(
        'teacher', 'department', 'department__faculty', 'department__faculty__otm'
    ).prefetch_related(
        'assignments__workload_type', 'assignments__subject', 'assignments__group', 'approvals',
    ).all()
    serializer_class = RejaSerializer
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']
    role_write = ('kafedra_mudiri',)

    def get_queryset(self):
        qs = scope_filter(super().get_queryset(), self.request.user,
                          departments_of=lambda o: [o.department_id],
                          teacher_of=lambda o: o.teacher_id, teacher_lookup='teacher')
        p = self.request.query_params
        if p.get('oqituvchiId'):
            qs = qs.filter(teacher_id=p['oqituvchiId'])
        oquv = p.get('oquvYili') or p.get('oquvYiliNomi')
        if oquv:
            qs = qs.filter(oquv_yili=oquv)
        kaf = p.get('departmentId') or p.get('kafedraId')
        if kaf:
            qs = qs.filter(department_id=kaf)
        return qs

    def create(self, request, *args, **kwargs):
        teacher_id = request.data.get('oqituvchiId')
        oquv_yili = request.data.get('oquvYiliNomi', '') or ''
        if teacher_id and Reja.objects.filter(teacher_id=teacher_id, oquv_yili=oquv_yili).exists():
            return Response({'detail': 'Bu o\'qituvchida shu o\'quv yili uchun reja mavjud'},
                            status=status.HTTP_409_CONFLICT)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dep = serializer.validated_data.get('department')
        _require(request, dep.id if dep else None)
        obj = serializer.save()
        # Kafedra yuklama_data ni rejaga nusxalaymiz (ko'rish uchun)
        dep = obj.department
        if (not obj.data and dep is not None and isinstance(dep.yuklama_data, dict)
                and dep.yuklama_data):
            obj.data = dep.yuklama_data
            if not obj.jami_soat:
                obj.jami_soat = dep.yillik_yuklama or 0
            obj.save(update_fields=['data', 'jami_soat', 'edited_at'])
        sync_reja_assignments(obj)
        Approval.objects.bulk_create([
            Approval(reja=obj, stage=stage) for stage in ('kafedra', 'dekan', 'oquv_bolimi')
        ], ignore_conflicts=True)
        return Response(self.get_serializer(obj).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        dep = serializer.validated_data.get('department', serializer.instance.department)
        _require(self.request, serializer.instance.department_id, dep.id if dep else None)
        obj = serializer.save()
        sync_reja_assignments(obj)

    @action(detail=True, methods=['post'], url_path='yuborish', permission_classes=[IsAuthenticated])
    def yuborish(self, request, pk=None):
        """O'qituvchi rejasini tasdiqlashga yuboradi (kafedra → dekan → o'quv bo'limi)."""
        from .approval_flow import submit
        reja = submit(request.user, self.get_object())
        return Response(self.get_serializer(reja).data)

    @action(detail=True, methods=['post'], url_path='qaror', permission_classes=[IsAuthenticated])
    def qaror(self, request, pk=None):
        """Navbatdagi bosqich rahbari qaror qiladi: {qaror: tasdiqlash|rad_etish, izoh}."""
        from .approval_flow import decide
        reja = decide(request.user, self.get_object(), request.data.get('qaror'), request.data.get('izoh'))
        return Response(self.get_serializer(reja).data)

    def perform_destroy(self, instance):
        _require(self.request, instance.department_id)
        super().perform_destroy(instance)


class TopshiriqViewSet(ODMModelViewSet):
    queryset = Assignment.objects.select_related('reja', 'workload_type', 'subject', 'group')
    serializer_class = AssignmentSerializer

    def get_queryset(self):
        qs = scope_filter(super().get_queryset(), self.request.user,
                          departments_of=lambda o: [o.reja.department_id] if o.reja else [],
                          teacher_of=lambda o: o.reja.teacher_id if o.reja else None,
                          teacher_lookup='reja__teacher')
        reja_id = self.request.query_params.get('rejaId')
        return qs.filter(reja_id=reja_id) if reja_id else qs


class TasdiqlashViewSet(ODMModelViewSet):
    queryset = Approval.objects.select_related('reja', 'acted_by')
    serializer_class = ApprovalSerializer

    def get_queryset(self):
        qs = scope_filter(super().get_queryset(), self.request.user,
                          departments_of=lambda o: [o.reja.department_id] if o.reja else [],
                          teacher_of=lambda o: o.reja.teacher_id if o.reja else None,
                          teacher_lookup='reja__teacher')
        reja_id = self.request.query_params.get('rejaId')
        return qs.filter(reja_id=reja_id) if reja_id else qs

    def perform_create(self, serializer):
        state = serializer.validated_data.get('state', 'kutilmoqda')
        acted = state in ('tasdiqlangan', 'rad_etilgan')
        obj = serializer.save(
            acted_by=self.request.user if acted else None,
            acted_at=timezone.now() if acted else None,
        )
        if acted:
            obj.reja.status = state
            obj.reja.save(update_fields=['status', 'edited_at'])

    def perform_update(self, serializer):
        state = serializer.validated_data.get('state', serializer.instance.state)
        acted = state in ('tasdiqlangan', 'rad_etilgan')
        obj = serializer.save(
            acted_by=self.request.user if acted else None,
            acted_at=timezone.now() if acted else None,
        )
        if acted:
            obj.reja.status = state
            obj.reja.save(update_fields=['status', 'edited_at'])


class NormativViewSet(ODMModelViewSet):
    queryset = WorkloadNorm.objects.select_related('workload_type')
    serializer_class = WorkloadNormSerializer
    role_write = ('oquv_bolimi',)

    def list(self, request, *args, **kwargs):
        record_type = request.query_params.get('type', 'normativ')
        if record_type == 'yuklama_turi':
            qs = WorkloadType.objects.prefetch_related('norms').all()
            return Response(WorkloadTypeSerializer(qs, many=True).data)
        if record_type == 'academic_year':
            return Response(AcademicYearSerializer(AcademicYear.objects.all(), many=True).data)
        if record_type == 'position_norm':
            year = request.query_params.get('oquvYili')
            qs = PositionNorm.objects.select_related('academic_year')
            if year:
                qs = qs.filter(academic_year__name=year)
            return Response(PositionNormSerializer(qs, many=True).data)
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        workload_type_id = self.request.query_params.get('yuklamaTuriId')
        return qs.filter(workload_type_id=workload_type_id) if workload_type_id else qs

    @staticmethod
    def _overlaps(attrs, exclude_pk=None):
        qs = WorkloadNorm.objects.filter(
            workload_type=attrs['workload_type'],
            institution_profile=attrs['institution_profile'],
        )
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        start = attrs['valid_from']
        end = attrs.get('valid_until')
        qs = qs.filter_fn(lambda n: n.valid_until is None or n.valid_until >= start)
        if end:
            qs = qs.filter(valid_from__lte=end)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        overlaps = self._overlaps(serializer.validated_data)
        if overlaps.exists() and not request.data.get('force'):
            return Response({
                'overlap': True,
                'warning': "Tanlangan davrda ushbu profil uchun normativ mavjud.",
                'overlapping': self.get_serializer(overlaps, many=True).data,
            })
        with atomic():
            if overlaps.exists():
                new_start = serializer.validated_data['valid_from']
                overlaps.filter(valid_from__lt=new_start).update(valid_until=new_start - timedelta(days=1))
                overlaps.filter(valid_from__gte=new_start).delete()
            self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class DlMdBiriktirmaViewSet(ODMModelViewSet):
    queryset = DlMdBiriktirma.objects.select_related(
        'teacher', 'department', 'department__faculty', 'department__faculty__otm'
    ).all()
    serializer_class = DlMdBiriktirmaSerializer
    role_write = ('kafedra_mudiri',)

    def get_queryset(self):
        qs = scope_filter(super().get_queryset(), self.request.user,
                          departments_of=lambda o: [o.department_id],
                          teacher_of=lambda o: o.teacher_id, teacher_lookup='teacher')
        p = self.request.query_params
        if p.get('oqituvchiId'):
            qs = qs.filter(teacher_id=p['oqituvchiId'])
        if p.get('kafedraId'):
            qs = qs.filter(department_id=p['kafedraId'])
        if p.get('fakultetId'):
            qs = qs.filter(department__faculty_id=p['fakultetId'])
        if p.get('otmId'):
            qs = qs.filter(department__faculty__otm_id=p['otmId'])
        if p.get('tur'):
            qs = qs.filter(tur=p['tur'])
        return qs

    def perform_create(self, serializer):
        dep = serializer.validated_data.get('department')
        _require(self.request, dep.id if dep else None)
        # Soat birligi: DL = 28, MD = 50 (talaba boshiga)
        tur = self.request.data.get('tur') or 'dl'
        sb = 50 if tur == 'md' else 28
        ts = int(self.request.data.get('talabaSoni') or 0)
        serializer.save(soat_birligi=sb, jami_soat=ts * sb)

    def perform_update(self, serializer):
        obj = serializer.instance
        dep = serializer.validated_data.get('department', obj.department)
        _require(self.request, obj.department_id, dep.id if dep else None)
        tur = self.request.data.get('tur') or obj.tur
        sb = 50 if tur == 'md' else 28
        ts = int(self.request.data.get('talabaSoni', obj.talaba_soni) or 0)
        serializer.save(soat_birligi=sb, jami_soat=ts * sb)

    def perform_destroy(self, instance):
        _require(self.request, instance.department_id)
        super().perform_destroy(instance)
