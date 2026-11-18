from apps.core import odm

LESSON_TYPE_CHOICES = [
    ('maruza', "Ma'ruza"), ('amaliyot', 'Amaliyot'), ('laboratoriya', 'Laboratoriya'),
    ('maruza_amaliyot', "ma'ruza/amaliyot"),
    ('maruza_laboratoriya', "ma'ruza/laboratoriya"),
    ('amaliyot_laboratoriya', 'amaliyot/laboratoriya'),
    ('maruza_amaliyot_laboratoriya', "ma'ruza/amaliyot/laboratoriya"),
]


class Yuklama(odm.Model):
    name = odm.CharField(max_length=255)
    file = odm.FileField(max_length=100, null=True)
    department = odm.ForeignKey('departments.Department', on_delete=odm.SET_NULL, null=True, related_name='yuklamalar')
    group = odm.ForeignKey('academics.Group', on_delete=odm.SET_NULL, null=True, related_name='yuklamalar')
    subject = odm.ForeignKey('academics.Subject', on_delete=odm.SET_NULL, null=True, related_name='yuklamalar')
    dak = odm.ForeignKey('academics.Dak', on_delete=odm.SET_NULL, null=True, related_name='yuklamalar')
    dl_md = odm.ForeignKey('academics.DlMd', on_delete=odm.SET_NULL, null=True, related_name='yuklamalar')
    groups_count = odm.IntegerField(positive=True, default=0)
    thread_count = odm.IntegerField(positive=True, default=0)
    control = odm.IntegerField(positive=True, default=0)
    edited_at = odm.DateTimeField(auto_now=True)
    created_at = odm.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Reja(odm.Model):
    """O'qituvchining shaxsiy ish rejasi (yuklama shakllantirishda yaratiladi)."""
    teacher = odm.ForeignKey('teachers.Teacher', on_delete=odm.CASCADE, related_name='rejalar', null=True)
    department = odm.ForeignKey('departments.Department', on_delete=odm.SET_NULL, related_name='rejalar', null=True)
    oquv_yili = odm.CharField(max_length=20, blank=True, default='')
    jami_soat = odm.IntegerField(positive=True, default=0)
    status = odm.CharField(max_length=30, default='loyiha')
    # Shakllantirilgan reja tafsilotlari (kafedra yuklama_data nusxasi)
    data = odm.JSONField(default=dict)
    edited_at = odm.DateTimeField(auto_now=True)
    created_at = odm.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        # Bitta o'qituvchiga bitta o'quv yili uchun bitta reja (o'qituvchisiz rejalar cheklanmaydi)
        unique = [odm.UniqueKey('reja_teacher_year',
                                lambda o: [o.teacher_id, o.oquv_yili] if o.teacher_id is not None else None)]

    def __str__(self):
        return f"Reja #{self.pk} (teacher={self.teacher_id}, {self.oquv_yili})"


class AcademicYear(odm.Model):
    name = odm.CharField(max_length=20)
    starts_on = odm.DateField()
    ends_on = odm.DateField()
    is_active = odm.BooleanField(default=False)

    class Meta:
        ordering = ['-starts_on']
        unique = [odm.UniqueKey('academicyear_name', lambda o: o.name)]

    def __str__(self):
        return self.name


class WorkloadType(odm.Model):
    code = odm.CharField(max_length=50)
    name = odm.CharField(max_length=255)
    clause_number = odm.IntegerField(positive=True, default=1)
    formula_expression = odm.CharField(max_length=255, blank=True)
    is_hourly = odm.BooleanField(default=False)
    is_active = odm.BooleanField(default=True)

    class Meta:
        ordering = ['clause_number', 'name']
        unique = [odm.UniqueKey('workloadtype_code', lambda o: o.code)]

    def __str__(self):
        return f'{self.code} — {self.name}'


class WorkloadNorm(odm.Model):
    workload_type = odm.ForeignKey(WorkloadType, on_delete=odm.CASCADE, related_name='norms')
    institution_profile = odm.CharField(max_length=30, default='barcha')
    coefficient = odm.DecimalField(max_digits=10, decimal_places=3, default=1)
    minimum = odm.IntegerField(positive=True, null=True)
    maximum = odm.IntegerField(positive=True, null=True)
    valid_from = odm.DateField()
    valid_until = odm.DateField(null=True)
    note = odm.TextField(blank=True)
    created_at = odm.DateTimeField(auto_now_add=True)
    edited_at = odm.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-valid_from', '-created_at']


class PositionNorm(odm.Model):
    position = odm.CharField(max_length=50)
    academic_year = odm.ForeignKey(AcademicYear, on_delete=odm.CASCADE, related_name='position_norms')
    minimum_hours = odm.IntegerField(positive=True)
    maximum_hours = odm.IntegerField(positive=True)

    class Meta:
        ordering = ['position']
        unique = [odm.UniqueKey('positionnorm_position_year', lambda o: [o.position, o.academic_year_id])]


class Assignment(odm.Model):
    lesson_type = odm.CharField(max_length=32, blank=True, default='', choices=LESSON_TYPE_CHOICES)
    reja = odm.ForeignKey(Reja, on_delete=odm.CASCADE, related_name='assignments')
    workload_type = odm.ForeignKey(WorkloadType, on_delete=odm.PROTECT, related_name='assignments')
    subject = odm.ForeignKey('academics.Subject', on_delete=odm.SET_NULL, null=True)
    group = odm.ForeignKey('academics.Group', on_delete=odm.SET_NULL, null=True)
    semester_number = odm.IntegerField(positive=True, default=1)
    hours = odm.DecimalField(max_digits=10, decimal_places=2)
    calculation_type = odm.CharField(max_length=30, default='rejali')
    formula_input = odm.JSONField(default=dict)
    note = odm.TextField(blank=True)
    created_at = odm.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['semester_number', 'id']


class Approval(odm.Model):
    reja = odm.ForeignKey(Reja, on_delete=odm.CASCADE, related_name='approvals')
    stage = odm.CharField(max_length=40)
    state = odm.CharField(max_length=30, default='kutilmoqda')
    comment = odm.TextField(blank=True)
    acted_by = odm.ForeignKey('accounts.User', on_delete=odm.SET_NULL, null=True)
    acted_at = odm.DateTimeField(null=True)
    created_at = odm.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        unique = [odm.UniqueKey('approval_reja_stage', lambda o: [o.reja_id, o.stage])]


class DlMdBiriktirma(odm.Model):
    """O'qituvchiga biriktirilgan DL (diplom loyiha) / MD (magistrlik dissertatsiyasi)
    rahbarligi. Talabalar soni × soat birligi = jami soat. Shaxsiy ish rejaga chiqadi."""
    teacher = odm.ForeignKey('teachers.Teacher', on_delete=odm.CASCADE, related_name='dlmd_biriktirmalar')
    department = odm.ForeignKey('departments.Department', on_delete=odm.CASCADE, related_name='dlmd_biriktirmalar')
    tur = odm.CharField(max_length=10, default='dl')  # 'dl' | 'md'
    talim_shakli = odm.CharField(max_length=30, blank=True)
    semestr = odm.CharField(max_length=10, default='bahorgi')  # 'kuzgi' | 'bahorgi'
    talaba_soni = odm.IntegerField(positive=True, default=0)
    soat_birligi = odm.IntegerField(positive=True, default=0)
    jami_soat = odm.IntegerField(positive=True, default=0)
    oquv_yili = odm.CharField(max_length=20, blank=True)
    edited_at = odm.DateTimeField(auto_now=True)
    created_at = odm.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"DlMd #{self.pk} ({self.tur}, teacher={self.teacher_id}, {self.talaba_soni} ta)"
