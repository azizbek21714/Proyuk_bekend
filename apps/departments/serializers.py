from rest_framework import serializers

from apps.core.drf import ODMSerializer
from apps.teachers.models import Teacher
from .models import OTM, Faculty, Department


class OTMSerializer(ODMSerializer):
    id = serializers.IntegerField(label='ID', read_only=True)
    name = serializers.CharField(max_length=255)
    short_name = serializers.CharField(allow_blank=True, max_length=100, required=False)
    edited_at = serializers.DateTimeField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = OTM


class FacultySerializer(ODMSerializer):
    id = serializers.IntegerField(label='ID', read_only=True)
    name = serializers.CharField(max_length=255)
    otm = serializers.PrimaryKeyRelatedField(queryset=OTM.objects.all())
    # Frontend "otmId" yoki "otm" yuborishi mumkin
    otmId = serializers.PrimaryKeyRelatedField(source='otm', queryset=OTM.objects.all(), write_only=True, required=False)
    dean = serializers.PrimaryKeyRelatedField(allow_null=True, queryset=Teacher.objects.all(), required=False)
    edited_at = serializers.DateTimeField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Faculty

    def validate(self, attrs):
        if 'otm' not in attrs and not self.instance:
            raise serializers.ValidationError({'otm': 'Bu maydon majburiy.'})
        return attrs


class DepartmentSerializer(ODMSerializer):
    id = serializers.IntegerField(label='ID', read_only=True)
    name = serializers.CharField(max_length=255)
    faculty = serializers.PrimaryKeyRelatedField(queryset=Faculty.objects.all())
    # Frontend "fakultetId" yoki "faculty" yuborishi mumkin
    fakultetId = serializers.PrimaryKeyRelatedField(source='faculty', queryset=Faculty.objects.all(),
                                                    write_only=True, required=False)
    head_of_department = serializers.PrimaryKeyRelatedField(allow_null=True, queryset=Teacher.objects.all(),
                                                            required=False)
    teachers = serializers.PrimaryKeyRelatedField(many=True, queryset=Teacher.objects.all(), required=False)
    yillik_yuklama = serializers.IntegerField(required=False)
    yuklama_data = serializers.JSONField(required=False)
    edited_at = serializers.DateTimeField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Department

    def validate(self, attrs):
        if 'faculty' not in attrs and not self.instance:
            raise serializers.ValidationError({'faculty': 'Bu maydon majburiy.'})
        return attrs
