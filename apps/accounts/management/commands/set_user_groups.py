"""Foydalanuvchi rollarini (guruhlarini) belgilaydi: admin, dekan, kafedra_mudiri, oquv_bolimi."""
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User

KNOWN = {'admin', 'dekan', 'kafedra_mudiri', 'oquv_bolimi'}


class Command(BaseCommand):
    help = "set_user_groups <email> [guruh ...]; guruhsiz bersangiz, hamma guruhlar olib tashlanadi"

    def add_arguments(self, parser):
        parser.add_argument('email')
        parser.add_argument('groups', nargs='*')

    def handle(self, *args, email, groups, **options):
        unknown = set(groups) - KNOWN
        if unknown:
            raise CommandError(f"Noma'lum guruh: {', '.join(sorted(unknown))}")
        user = User.objects.filter(email__iexact=email.strip()).first()
        if user is None:
            raise CommandError('Foydalanuvchi topilmadi.')
        user.groups = sorted(set(groups))
        user.save(update_fields=['groups'])
        self.stdout.write(self.style.SUCCESS(f"{user.email}: {user.groups or 'guruhsiz'}"))
