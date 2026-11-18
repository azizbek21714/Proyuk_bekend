#!/usr/bin/env bash
# Render build skripti: paketlar, statik fayllar, boshlang'ich ma'lumotlar va admin hisobi.
# Ma'lumotlar Firestore'da: migratsiya kerak emas.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --noinput

# Bo'sh Firestore'ga o'quv yili, yuklama turlari, lavozim normalarini yozadi (faqat bir marta)
python manage.py seed_defaults

# ADMIN_EMAIL va ADMIN_PASSWORD berilgan bo'lsa, admin hisobi yaratiladi (bor bo'lsa, tegilmaydi)
python manage.py ensure_admin
