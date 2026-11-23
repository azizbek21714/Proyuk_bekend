from django.db import models

from apps.core import odm


class StudyFormat(models.TextChoices):
    FULL_TIME = 'full_time', 'Full Time'
    PART_TIME = 'part_time', 'Part Time'
    EVENING = 'evening', 'Evening'
    DISTANCE = 'distance', 'Distance'


class ProgramType(models.TextChoices):
    BACHELOR = 'bachelor', 'Bachelor'
    MASTER = 'master', 'Master'
    PHD = 'phd', 'PhD'


class Course(models.TextChoices):
    COURSE_1 = 'course_1', 'Course 1'
    COURSE_2 = 'course_2', 'Course 2'
    COURSE_3 = 'course_3', 'Course 3'
    COURSE_4 = 'course_4', 'Course 4'
    COURSE_5 = 'course_5', 'Course 5'


class Semester(models.TextChoices):
    SEMESTER_1 = 'semester_1', 'Semester 1'
    SEMESTER_2 = 'semester_2', 'Semester 2'
    SEMESTER_3 = 'semester_3', 'Semester 3'
    SEMESTER_4 = 'semester_4', 'Semester 4'
    SEMESTER_5 = 'semester_5', 'Semester 5'
    SEMESTER_6 = 'semester_6', 'Semester 6'
    SEMESTER_7 = 'semester_7', 'Semester 7'
    SEMESTER_8 = 'semester_8', 'Semester 8'
    SEMESTER_9 = 'semester_9', 'Semester 9'
    SEMESTER_10 = 'semester_10', 'Semester 10'


class StudyLanguage(models.TextChoices):
    UZ = 'uz', 'Uzbek'
    RU = 'ru', 'Russian'
    EN = 'en', 'English'


class DlMdType(models.TextChoices):
    LECTURE = 'lecture', 'Lecture'
    SEMINAR = 'seminar', 'Seminar'
    LABORATORY = 'laboratory', 'Laboratory'
    INDEPENDENT_WORK = 'independent_work', 'Independent Work'


class PractiseType(models.TextChoices):
    EDUCATIONAL = 'educational', 'Educational'
    INDUSTRIAL = 'industrial', 'Industrial'
    PRE_DIPLOMA = 'pre_diploma', 'Pre-Diploma'


class DakType(models.TextChoices):
    FINAL_EXAM = 'final_exam', 'Final Exam'
    THESIS_DEFENSE = 'thesis_defense', 'Thesis Defense'


class Subject(odm.Model):
    name = odm.CharField(max_length=255)
    department = odm.ForeignKey('departments.Department', on_delete=odm.CASCADE, related_name='subjects', null=True)
    study_format = odm.CharField(max_length=50, choices=StudyFormat.choices, default=StudyFormat.FULL_TIME)
    program_type = odm.CharField(max_length=50, choices=ProgramType.choices, default=ProgramType.BACHELOR)
    course = odm.CharField(max_length=50, choices=Course.choices, default=Course.COURSE_1)
    semester = odm.CharField(max_length=50, choices=Semester.choices, default=Semester.SEMESTER_1)
    study_language = odm.CharField(max_length=10, choices=StudyLanguage.choices, default=StudyLanguage.UZ)
    # Comma-separated list of language codes (e.g. "uz,ru"). Allows a subject
    # to be taught in several languages. `study_language` kept for back-compat.
    study_languages = odm.CharField(max_length=50, blank=True, default='')
    # Hours broken down per mashg'ulot shakli. `hours` stays as the total.
    maruza_hours = odm.IntegerField(positive=True, default=0)
    amaliyot_hours = odm.IntegerField(positive=True, default=0)
    laboratoriya_hours = odm.IntegerField(positive=True, default=0)
    seminar_hours = odm.IntegerField(positive=True, default=0)
    hours = odm.IntegerField(positive=True, default=0)
    edited_at = odm.DateTimeField(auto_now=True)
    created_at = odm.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        # Bitta kafedrada bir xil nomli fan (katta-kichik harfdan qat'i nazar) bo'lmaydi
        unique = [odm.UniqueKey('subjects_name_department',
                                lambda o: [o.department_id, o.name.lower()] if o.department_id is not None else None)]

    def __str__(self):
        return f"{self.name}"


class Group(odm.Model):
    name = odm.CharField(max_length=255)
    department = odm.ForeignKey('departments.Department', on_delete=odm.CASCADE, related_name='groups', null=True)
    course = odm.CharField(max_length=50, choices=Course.choices, default=Course.COURSE_1)
    program_type = odm.CharField(max_length=50, choices=ProgramType.choices, default=ProgramType.BACHELOR)
    study_format = odm.CharField(max_length=50, choices=StudyFormat.choices, default=StudyFormat.FULL_TIME)
    study_language = odm.CharField(max_length=10, choices=StudyLanguage.choices, default=StudyLanguage.UZ)
    oquv_yili = odm.CharField(max_length=20, blank=True, default='')
    students = odm.IntegerField(positive=True, default=0)
    edited_at = odm.DateTimeField(auto_now=True)
    created_at = odm.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Talaba(odm.Model):
    """Guruhdagi talaba (kafedra mudiri qo'lda yoki Excel'dan kiritadi)."""
    group = odm.ForeignKey(Group, on_delete=odm.CASCADE, related_name='talabalar')
    fio = odm.CharField(max_length=255)
    telefon = odm.CharField(max_length=50, blank=True, default='')
    edited_at = odm.DateTimeField(auto_now=True)
    created_at = odm.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['fio']

    def __str__(self):
        return self.fio


class DlMd(odm.Model):
    name = odm.CharField(max_length=255)
    type = odm.CharField(max_length=50, choices=DlMdType.choices, default=DlMdType.LECTURE)
    program_type = odm.CharField(max_length=50, choices=ProgramType.choices, default=ProgramType.BACHELOR)
    study_language = odm.CharField(max_length=10, choices=StudyLanguage.choices, default=StudyLanguage.UZ)
    students = odm.IntegerField(positive=True, default=0)
    edited_at = odm.DateTimeField(auto_now=True)
    created_at = odm.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Dak(odm.Model):
    type = odm.CharField(max_length=50, choices=DakType.choices, default=DakType.FINAL_EXAM)
    hours = odm.IntegerField(positive=True, default=0)
    body = odm.TextField(blank=True)
    edited_at = odm.DateTimeField(auto_now=True)
    created_at = odm.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['type']

    def __str__(self):
        return f"{self.type} ({self.hours} hours)"
