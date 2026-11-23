"""Guruh talabalari: ro'yxat (CRUD) va Excel'dan yuklash.

Talaba guruh orqali kafedraga tegishli: kafedra mudiri faqat o'z kafedrasi guruhlariga yozadi,
rahbarlar o'z hududini ko'radi. Har o'zgarishdan keyin Group.students = talabalar soni.
"""
import re

from rest_framework import serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import user_scope
from apps.core.drf import ODMModelViewSet, ODMSerializer
from apps.core.odm import atomic
from config.permissions import require_departments, scope_filter
from .models import Group, Talaba

ALLOWED_EXCEL_EXTENSIONS = ('.xlsx', '.xlsm', '.xls')
MAX_EXCEL_SIZE = 10 * 1024 * 1024  # 10 MB
_PHONE = re.compile(r'^\+?[\d\s\-()]{7,20}$')
_HEADER_WORDS = ('fio', 'f.i.o', 'f.i.sh', 'fish', 'familiya', 'ism', 'талаба', 'фио', 'name')


def _require(user, department_id):
    if not user_scope(user).is_admin:
        require_departments(user, [department_id])


def _sync_count(group):
    group.students = Talaba.objects.filter(group_id=group.id).count()
    group.save(update_fields=['students', 'edited_at'])


def _clean_fio(value):
    return ' '.join(str(value or '').split())


class TalabaSerializer(ODMSerializer):
    id = serializers.IntegerField(label='ID', read_only=True)
    group = serializers.PrimaryKeyRelatedField(queryset=Group.objects.all())
    fio = serializers.CharField(max_length=255)
    telefon = serializers.CharField(max_length=50, allow_blank=True, required=False)
    created_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Talaba

    def validate_fio(self, value):
        value = _clean_fio(value)
        if not value:
            raise serializers.ValidationError('FIO ni kiriting.')
        return value


class TalabaViewSet(ODMModelViewSet):
    """GET /api/crud/talabalar/?guruhId= — guruh talabalari; yozish: kafedra mudiri (o'z kafedrasi)."""
    queryset = Talaba.objects.all()
    serializer_class = TalabaSerializer
    role_write = ('kafedra_mudiri',)

    def get_queryset(self):
        qs = super().get_queryset()
        guruh_id = self.request.query_params.get('guruhId')
        if guruh_id:
            qs = qs.filter(group_id=guruh_id)
        groups = {g.id: g.department_id for g in Group.objects.all()}
        return scope_filter(qs, self.request.user, departments_of=lambda o: [groups.get(o.group_id)])

    def perform_create(self, serializer):
        group = serializer.validated_data['group']
        _require(self.request.user, group.department_id)
        with atomic():
            serializer.save()
            _sync_count(group)

    def perform_update(self, serializer):
        old_group = serializer.instance.group
        group = serializer.validated_data.get('group', old_group)
        _require(self.request.user, old_group.department_id)
        _require(self.request.user, group.department_id)
        with atomic():
            serializer.save()
            if group.id != old_group.id:
                _sync_count(old_group)
                _sync_count(group)

    def perform_destroy(self, instance):
        group = instance.group
        _require(self.request.user, group.department_id)
        with atomic():
            instance.delete()
            _sync_count(group)


def parse_student_rows(rows):
    """Excel qatorlaridan [{fio, telefon}] — T/r ustuni va sarlavha qatorlari o'tkazib yuboriladi."""
    result = []
    for row in rows:
        cells = [c for c in (row or [])]
        texts = [str(c).strip() if c is not None else '' for c in cells]
        if not any(texts):
            continue
        lowered = ' '.join(texts).lower()
        if any(word in lowered for word in _HEADER_WORDS) and not any(ch.isdigit() for ch in lowered.replace('.', '')):
            continue
        fio, telefon = '', ''
        for cell, text in zip(cells, texts):
            if not text:
                continue
            if isinstance(cell, (int, float)) and not fio and len(text.replace('.0', '')) <= 4:
                continue  # T/r raqami
            if _PHONE.match(text) and sum(ch.isdigit() for ch in text) >= 7:
                telefon = telefon or text
                continue
            if not fio and any(ch.isalpha() for ch in text):
                fio = _clean_fio(text)
        if fio and fio.lower() not in _HEADER_WORDS:
            result.append({'fio': fio, 'telefon': telefon})
    return result


class TalabaImportView(APIView):
    """POST /api/crud/talabalar-import/ (multipart): file, guruh_id, save.

    save yuborilmasa — faqat oldindan ko'rish; save=true — guruhda yo'q FIO'lar qo'shiladi.
    """
    parser_classes = [MultiPartParser, FormParser]
    role_write = ('kafedra_mudiri',)

    def post(self, request, *args, **kwargs):
        group = Group.objects.filter(pk=request.data.get('guruh_id') or 0).first()
        if group is None:
            return Response({'detail': 'Guruh topilmadi.'}, status=status.HTTP_400_BAD_REQUEST)
        _require(request.user, group.department_id)

        file_obj = request.FILES.get('file')
        if file_obj is None:
            return Response({'detail': "Fayl yuborilmadi. 'file' maydonida Excel fayl yuboring."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not (file_obj.name or '').lower().endswith(ALLOWED_EXCEL_EXTENSIONS):
            return Response({'detail': "Faqat .xlsx, .xlsm yoki .xls formatdagi Excel fayl qabul qilinadi."},
                            status=status.HTTP_400_BAD_REQUEST)
        if file_obj.size and file_obj.size > MAX_EXCEL_SIZE:
            return Response({'detail': 'Fayl hajmi 10 MB dan oshmasligi kerak.'}, status=status.HTTP_400_BAD_REQUEST)

        from apps.workload.excel_parser import _read_excel_rows
        try:
            rows = parse_student_rows(_read_excel_rows(file_obj))
        except Exception as exc:  # noqa: BLE001 - foydalanuvchiga toza xabar
            return Response({'detail': f"Faylni o'qishda xatolik: {exc}"}, status=status.HTTP_400_BAD_REQUEST)
        if not rows:
            return Response({'detail': "Faylda talabalar FIO si topilmadi."}, status=status.HTTP_400_BAD_REQUEST)

        existing = {t.fio.lower() for t in Talaba.objects.filter(group_id=group.id)}
        seen, new_rows, skipped = set(), [], 0
        for row in rows:
            key = row['fio'].lower()
            if key in existing or key in seen:
                skipped += 1
                continue
            seen.add(key)
            new_rows.append(row)

        save_flag = str(request.data.get('save', '')).lower() in ('1', 'true', 'yes', 'ha')
        if save_flag and new_rows:
            with atomic():
                for row in new_rows:
                    Talaba.objects.create(group=group, fio=row['fio'], telefon=row['telefon'])
                _sync_count(group)
        return Response({
            'saved': save_flag,
            'talabalar': new_rows,
            'yangi': len(new_rows),
            'takror': skipped,
            'jami': len(rows),
        })
