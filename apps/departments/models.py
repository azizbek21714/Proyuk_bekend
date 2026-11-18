from apps.core import odm


class OTM(odm.Model):
    """Oliy ta'lim muassasasi — eng yuqori daraja"""
    name = odm.CharField(max_length=255)
    short_name = odm.CharField(max_length=100, blank=True)
    edited_at = odm.DateTimeField(auto_now=True)
    created_at = odm.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.short_name})" if self.short_name else self.name


class Faculty(odm.Model):
    """Fakultet — OTM ga tegishli"""
    name = odm.CharField(max_length=255)
    otm = odm.ForeignKey(OTM, on_delete=odm.CASCADE, related_name='faculties')
    dean = odm.ForeignKey('teachers.Teacher', on_delete=odm.SET_NULL, null=True, related_name='deaned_faculties')
    edited_at = odm.DateTimeField(auto_now=True)
    created_at = odm.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Department(odm.Model):
    """Kafedra — Fakultet ga tegishli"""
    name = odm.CharField(max_length=255)
    faculty = odm.ForeignKey(Faculty, on_delete=odm.CASCADE, related_name='departments')
    head_of_department = odm.ForeignKey('teachers.Teacher', on_delete=odm.SET_NULL, null=True,
                                        related_name='headed_departments')
    teachers = odm.ManyToManyField('teachers.Teacher', related_name='departments')
    # Kafedraning yillik yuklamasi (soat) — yuklama Excel faylidan hisoblanadi
    yillik_yuklama = odm.IntegerField(positive=True, default=0)
    # Shakllantirilgan yuklama (qatorlar + o'quv yili) — ko'rish/tahrirlash uchun saqlanadi
    yuklama_data = odm.JSONField(default=dict)
    edited_at = odm.DateTimeField(auto_now=True)
    created_at = odm.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
