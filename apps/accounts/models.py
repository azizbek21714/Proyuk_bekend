"""Application users stored in the document store (replaces django.contrib.auth.User).

Passwords use Django's hashers (no database needed). Groups are a list of names
('admin', 'dekan', 'kafedra_mudiri', 'oquv_bolimi').
"""
from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from apps.core import odm
from apps.core.odm import registry
from apps.core.odm.queryset import QuerySet


class UserQuerySet(QuerySet):
    """Django-compatible helpers (create_user / create_superuser)."""

    def create_user(self, username, email='', password=None, **extra):
        extra.setdefault('is_staff', False)
        extra.setdefault('is_superuser', False)
        return self._create_user(username, email, password, **extra)

    def create_superuser(self, username, email='', password=None, **extra):
        extra['is_staff'] = True
        extra['is_superuser'] = True
        return self._create_user(username, email, password, **extra)

    def _create_user(self, username, email, password, **extra):
        user = self.model(username=username, email=(email or '').strip(), **extra)
        user.set_password(password)
        user.save(force_insert=True)
        return user


class UserManagerDescriptor:
    def __get__(self, instance, owner):
        if instance is not None:
            raise AttributeError('Manager is not accessible via model instances')
        return UserQuerySet(owner)


class User(odm.Model):
    username = odm.CharField(max_length=150)
    email = odm.EmailField(max_length=254, blank=True)
    password = odm.CharField(max_length=128)
    first_name = odm.CharField(max_length=150, blank=True)
    last_name = odm.CharField(max_length=150, blank=True)
    is_active = odm.BooleanField(default=True)
    is_staff = odm.BooleanField(default=False)
    is_superuser = odm.BooleanField(default=False)
    groups = odm.JSONField(default=list)
    date_joined = odm.DateTimeField(null=True)
    last_login = odm.DateTimeField(null=True)

    class Meta:
        collection = 'users'
        ordering = ['id']
        unique = [
            odm.UniqueKey('users_username', lambda o: o.username),
            # Bir pochta — bitta hisob (katta-kichik harf farqlanmaydi)
            odm.UniqueKey('users_email', lambda o: o.email.lower() if o.email else None),
        ]

    is_anonymous = False
    is_authenticated = True

    def save(self, *args, **kwargs):
        if self.date_joined is None:
            self.date_joined = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.username

    def get_username(self):
        return self.username

    def get_full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    def get_short_name(self):
        return self.first_name

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def set_unusable_password(self):
        self.password = make_password(None)

    def check_password(self, raw_password):
        def setter(raw):
            self.set_password(raw)
            self.save(update_fields=['password'])
        return check_password(raw_password, self.password, setter)

    def has_group(self, name):
        return name in (self.groups or [])

    @property
    def teacher_profile(self):
        """Linked Teacher or None (like getattr(user, 'teacher_profile', None))."""
        from apps.teachers.models import Teacher
        return Teacher.objects.filter(user=self.pk).first() if self.pk is not None else None


User.objects = UserManagerDescriptor()
registry.alias('auth.User', User)
