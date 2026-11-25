from django.db import models

from apps.core import odm


class TeacherPosition(models.TextChoices):
    PROFESSOR = 'professor', 'Professor'
    ASSOCIATE_PROFESSOR = 'associate_professor', 'Associate Professor'
    SENIOR_TEACHER = 'senior_teacher', 'Senior Teacher'
    TEACHER = 'teacher', 'Teacher'
    ASSISTANT = 'assistant', 'Assistant'


class TeacherDegree(models.TextChoices):
    PHD = 'phd', 'PhD'
    DSC = 'dsc', 'DSc'
    MASTER = 'master', 'Master'
    BACHELOR = 'bachelor', 'Bachelor'


class AcademicTitle(models.TextChoices):
    PROFESSOR = 'professor', 'Professor'
    DOCENT = 'docent', 'Docent'
    SENIOR_RESEARCHER = 'senior_researcher', 'Senior Researcher'
    NONE = 'none', 'None'


class Speciality(models.TextChoices):
    ECONOMICS = 'economics', 'Economics'
    MATHEMATICS = 'mathematics', 'Mathematics'
    COMPUTER_SCIENCE = 'computer_science', 'Computer Science'
    ENGINEERING = 'engineering', 'Engineering'
    OTHER = 'other', 'Other'


class TeacherRate(models.TextChoices):
    RATE_1_5 = 'rate_1_5', '1.5 stavka'
    RATE_1 = 'rate_1', '1 stavka'
    RATE_0_5_ICHKI = 'rate_0_5_ichki', '0.5 ichki stavka'
    RATE_0_5_TASHQI = 'rate_0_5_tashqi', '0.5 stavka tashqi'
    RATE_0_25 = 'rate_0_25', '0.25 stavka'


class Teacher(odm.Model):
    user = odm.OneToOneField('accounts.User', on_delete=odm.SET_NULL, null=True, related_name='teacher_profile')
    full_name = odm.CharField(max_length=255)
    position = odm.CharField(max_length=50, choices=TeacherPosition.choices, default=TeacherPosition.TEACHER)
    degree = odm.CharField(max_length=50, choices=TeacherDegree.choices, default=TeacherDegree.BACHELOR)
    academic_title = odm.CharField(max_length=50, choices=AcademicTitle.choices, default=AcademicTitle.NONE)
    speciality = odm.CharField(max_length=50, choices=Speciality.choices, default=Speciality.OTHER)
    rate = odm.CharField(max_length=50, choices=TeacherRate.choices, default=TeacherRate.RATE_1)
    email = odm.EmailField(max_length=255, blank=True)
    phone_number = odm.CharField(max_length=50, blank=True)
    # "Foydalanuvchilar va rollar"dan qo'shilgan rahbar/xodim (dekan, o'quv bo'limi va h.k.):
    # o'qituvchilar ro'yxatida ko'rsatilmaydi
    faqat_xodim = odm.BooleanField(default=False)
    edited_at = odm.DateTimeField(auto_now=True)
    created_at = odm.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['full_name']
        # Pochta (bo'sh bo'lmasa) katta-kichik harfdan qat'i nazar takrorlanmaydi
        unique = [odm.UniqueKey('teachers_email', lambda o: o.email.lower() if o.email else None)]

    def get_position_display(self):
        return TeacherPosition(self.position).label if self.position in TeacherPosition.values else self.position

    def __str__(self):
        return f"{self.full_name} ({self.get_position_display()})"
