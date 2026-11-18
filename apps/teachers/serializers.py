from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from apps.accounts.models import User
from apps.core.drf import ODMSerializer
from .models import AcademicTitle, Speciality, Teacher, TeacherDegree, TeacherPosition, TeacherRate


class TeacherSerializer(ODMSerializer):
    id = serializers.IntegerField(label='ID', read_only=True)
    full_name = serializers.CharField(max_length=255)
    position = serializers.ChoiceField(choices=TeacherPosition.choices, required=False)
    degree = serializers.ChoiceField(choices=TeacherDegree.choices, required=False)
    academic_title = serializers.ChoiceField(choices=AcademicTitle.choices, required=False)
    speciality = serializers.ChoiceField(choices=Speciality.choices, required=False)
    rate = serializers.ChoiceField(choices=TeacherRate.choices, required=False)
    email = serializers.EmailField(allow_blank=True, max_length=255, required=False)
    phone_number = serializers.CharField(allow_blank=True, max_length=50, required=False)
    edited_at = serializers.DateTimeField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    user = serializers.PrimaryKeyRelatedField(
        allow_null=True, queryset=User.objects.all(), required=False,
        validators=[UniqueValidator(queryset=Teacher.objects.all(), message='teacher with this user already exists.')],
    )

    class Meta:
        model = Teacher
