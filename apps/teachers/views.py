from rest_framework import viewsets
from .models import Teacher
from .serializers import TeacherSerializer
from config.permissions import limit_to_own


class TeacherViewSet(viewsets.ModelViewSet):
    queryset = Teacher.objects.all()
    serializer_class = TeacherSerializer

    def get_queryset(self):
        # Telefon va pochta shaxsiy ma'lumot: administrator bo'lmagan foydalanuvchi
        # faqat o'z profilini ko'radi.
        qs = limit_to_own(super().get_queryset(), self.request.user, '')
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
        return qs.distinct()
