# ProYuk: lokal ishga tushirish

Backend: Django + DRF, `http://127.0.0.1:8000`. Frontend: Next.js, `http://localhost:3000`.
Ma'lumotlar Google Firestore'da saqlanadi (SQL baza yo'q). Kompyuterda Firestore
o'rniga `.localstore.json` fayli ishlatiladi (`STORE_BACKEND=jsonfile`, standart).

## Backend (PowerShell)

```powershell
cd D:\Desktop\ProYuk\Yuk_backend
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe manage.py seed_defaults
.\venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Yoki loyiha papkasidagi `start.bat` faylini oching.

## Buyruqlar

| Buyruq | Vazifasi |
|---|---|
| `seed_defaults` | Bo'sh bazaga o'quv yili, yuklama turlari va lavozim normalarini yozadi (bir marta) |
| `ensure_admin` | `ADMIN_EMAIL` / `ADMIN_PASSWORD` bo'yicha administrator yaratadi |
| `set_user_groups <email> [guruh ...]` | Rollar: `admin`, `dekan`, `kafedra_mudiri`, `oquv_bolimi` |
| `import_sqlite [db.sqlite3] [--dry-run] [--wipe]` | Eski SQLite bazani id'lari bilan ko'chiradi |
| `verify_import [db.sqlite3]` | Ko'chirilgan har bir yozuvni SQLite bilan solishtiradi |
| `export_store <fayl.json>` | Hamma ma'lumotni JSON faylga zaxira qiladi |

Firestore'ga ulanish uchun `.env` (yoki Render Environment) da:
`STORE_BACKEND=firestore`, `FIREBASE_PROJECT_ID`, `FIREBASE_CREDENTIALS`
(service account JSON matni yoki uning base64 ko'rinishi). Namuna: `.env.example`.

## Frontend (alohida PowerShell)

```powershell
cd D:\Desktop\ProYuk\Yuk_frontend
npm.cmd install
npm.cmd run dev
```

Backend manzili frontend serverining `DJANGO_API_URL` muhit o'zgaruvchisi orqali
sozlanadi; standart qiymat `http://127.0.0.1:8000`.

## Tekshirish

```powershell
# Backend papkasida; testlar xotiradagi vaqtinchalik store'dan foydalanadi.
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py test config apps --noinput
# API eski backend bilan bir xil javob berishini tekshirish (tools/golden/golden.sqlite3 kerak)
.\venv\Scripts\python.exe tools\golden\replay.py
```

## Hisoblar va ma'lumotlar

- Kirish elektron pochta va parol orqali. Parollar xeshlangan holda store'da saqlanadi,
  email bosh/kichik harfdan qat'i nazar takrorlanmaydi.
- Administrator: `is_superuser` yoki `admin` guruhi. Boshqa rollar guruhlar orqali
  (`set_user_groups`). Ochiq ro'yxatdan o'tish administrator huquqini bermaydi.
- JWT: access 1 soat, refresh 30 kun; refresh token har yangilanishda almashadi,
  eskisi `token_blacklist` ga yoziladi.
- CRUD ro'yxatlari odatda to'liq qaytadi. `?page=1` berilganda 20 tadan sahifalanadi.
