#!/usr/bin/env bash
# Render build skripti: paketlar, statik fayllar, migratsiyalar va admin hisobi.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --noinput
python manage.py migrate --noinput

# ADMIN_EMAIL va ADMIN_PASSWORD berilgan bo'lsa, admin hisobi yaratiladi (bor bo'lsa — tegilmaydi)
python manage.py ensure_admin
