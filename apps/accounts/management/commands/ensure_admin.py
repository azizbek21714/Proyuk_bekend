"""Deploy paytida administrator hisobini yaratadi (Render'da terminal bo'lmagani uchun).

ADMIN_EMAIL va ADMIN_PASSWORD muhit o'zgaruvchilari berilgan bo'lsa:
  - shu pochtali foydalanuvchi bo'lmasa — superuser yaratiladi;
  - bor bo'lsa — paroliga tegilmaydi, faqat administrator huquqi tekshiriladi.
O'zgaruvchilar berilmagan bo'lsa, hech narsa qilinmaydi.
"""
import os
from hashlib import sha256

from apps.accounts.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "ADMIN_EMAIL va ADMIN_PASSWORD bo'yicha administrator hisobini yaratadi"

    def handle(self, *args, **options):
        email = (os.environ.get('ADMIN_EMAIL') or '').strip().lower()
        password = os.environ.get('ADMIN_PASSWORD') or ''
        if not email or not password:
            self.stdout.write("ADMIN_EMAIL/ADMIN_PASSWORD berilmagan — admin yaratilmadi.")
            return

        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            # Login pochta orqali ishlaydi; username — texnik, signup bilan bir xil usulda
            username = 'email_' + sha256(email.encode('utf-8')).hexdigest()
            User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f"Administrator yaratildi: {email}"))
            return

        if not (user.is_superuser and user.is_staff):
            user.is_superuser = True
            user.is_staff = True
            user.save(update_fields=['is_superuser', 'is_staff'])
            self.stdout.write(self.style.SUCCESS(f"Administrator huquqi berildi: {email}"))
        else:
            self.stdout.write(f"Administrator allaqachon mavjud: {email}")
