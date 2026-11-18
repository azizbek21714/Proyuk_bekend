from rest_framework import serializers

from apps.core.drf import ODMSerializer
from apps.departments.models import Department
from .models import Course, Dak, DakType, DlMd, DlMdType, Group, ProgramType, Semester, StudyFormat, StudyLanguage, Subject


def _kafedra_chain(obj):
    """Read-only nested kafedra chain (kafedra -> fakultet -> otm) for the UI cascade."""
    d = obj.department
    if not d:
        return None
    fak = d.faculty
    return {
        'id': d.id,
        'nomi': d.name,
        'fakultet': {
            'id': fak.id,
            'nomi': fak.name,
            'otmId': fak.otm_id,
        } if fak else None,
    }


class SubjectSerializer(ODMSerializer):
    # Write uses the plain `department` PK field.
    id = serializers.IntegerField(label='ID', read_only=True)
    kafedra = serializers.SerializerMethodField(read_only=True)
    name = serializers.CharField(max_length=255)
    study_format = serializers.ChoiceField(choices=StudyFormat.choices, required=False)
    program_type = serializers.ChoiceField(choices=ProgramType.choices, required=False)
    course = serializers.ChoiceField(choices=Course.choices, required=False)
    semester = serializers.ChoiceField(choices=Semester.choices, required=False)
    study_language = serializers.ChoiceField(choices=StudyLanguage.choices, required=False)
    study_languages = serializers.CharField(allow_blank=True, max_length=50, required=False)
    maruza_hours = serializers.IntegerField(required=False)
    amaliyot_hours = serializers.IntegerField(required=False)
    laboratoriya_hours = serializers.IntegerField(required=False)
    seminar_hours = serializers.IntegerField(required=False)
    hours = serializers.IntegerField(required=False)
    edited_at = serializers.DateTimeField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    department = serializers.PrimaryKeyRelatedField(allow_null=True, queryset=Department.objects.all(), required=False)

    class Meta:
        model = Subject

    def get_kafedra(self, obj):
        return _kafedra_chain(obj)


class GroupSerializer(ODMSerializer):
    id = serializers.IntegerField(label='ID', read_only=True)
    kafedra = serializers.SerializerMethodField(read_only=True)
    name = serializers.CharField(max_length=255)
    course = serializers.ChoiceField(choices=Course.choices, required=False)
    program_type = serializers.ChoiceField(choices=ProgramType.choices, required=False)
    study_format = serializers.ChoiceField(choices=StudyFormat.choices, required=False)
    study_language = serializers.ChoiceField(choices=StudyLanguage.choices, required=False)
    oquv_yili = serializers.CharField(allow_blank=True, max_length=20, required=False)
    students = serializers.IntegerField(required=False)
    edited_at = serializers.DateTimeField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    department = serializers.PrimaryKeyRelatedField(allow_null=True, queryset=Department.objects.all(), required=False)

    class Meta:
        model = Group

    def get_kafedra(self, obj):
        return _kafedra_chain(obj)


class DlMdSerializer(ODMSerializer):
    id = serializers.IntegerField(label='ID', read_only=True)
    name = serializers.CharField(max_length=255)
    type = serializers.ChoiceField(choices=DlMdType.choices, required=False)
    program_type = serializers.ChoiceField(choices=ProgramType.choices, required=False)
    study_language = serializers.ChoiceField(choices=StudyLanguage.choices, required=False)
    students = serializers.IntegerField(required=False)
    edited_at = serializers.DateTimeField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = DlMd


class DakSerializer(ODMSerializer):
    id = serializers.IntegerField(label='ID', read_only=True)
    type = serializers.ChoiceField(choices=DakType.choices, required=False)
    hours = serializers.IntegerField(required=False)
    body = serializers.CharField(allow_blank=True, required=False, style={'base_template': 'textarea.html'})
    edited_at = serializers.DateTimeField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Dak
