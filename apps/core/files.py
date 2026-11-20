"""Fayl saqlash qatlami (o'qituvchilar yuklagan ish dalillari).

FILE_STORAGE sozlamasi:
  supabase — Supabase Storage (yopiq bucket; fayllar faqat backend orqali beriladi)
  local    — lokal papka (BASE_DIR/.local_files) — dev uchun
  memory   — xotira — testlar uchun

Fayllar hech qachon ochiq havola bilan berilmaydi: backend huquqni tekshirib, faylni o'zi uzatadi.
"""
from pathlib import Path
from urllib.parse import quote

from django.conf import settings


class FileStorageError(Exception):
    pass


class MemoryFileStorage:
    def __init__(self):
        self.files = {}

    def upload(self, path, data, mime):
        self.files[path] = (bytes(data), mime)

    def download(self, path):
        if path not in self.files:
            raise FileStorageError('Fayl topilmadi.')
        return self.files[path][0]

    def delete(self, paths):
        for path in paths:
            self.files.pop(path, None)


class LocalFileStorage:
    def __init__(self, root):
        self.root = Path(root)

    def _full(self, path):
        full = (self.root / path).resolve()
        if self.root.resolve() not in full.parents:
            raise FileStorageError("Noto'g'ri fayl yo'li.")
        return full

    def upload(self, path, data, mime):
        full = self._full(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)

    def download(self, path):
        full = self._full(path)
        if not full.exists():
            raise FileStorageError('Fayl topilmadi.')
        return full.read_bytes()

    def delete(self, paths):
        for path in paths:
            full = self._full(path)
            if full.exists():
                full.unlink()


class SupabaseStorage:
    """Supabase Storage REST API (service role kaliti bilan, faqat server tomonda)."""

    def __init__(self, url, key, bucket):
        if not url or not key:
            raise FileStorageError('SUPABASE_URL va SUPABASE_SERVICE_ROLE_KEY berilmagan.')
        self.base = url.rstrip('/') + '/storage/v1/object'
        self.key = key
        self.bucket = bucket

    def _headers(self, extra=None):
        headers = {'Authorization': f'Bearer {self.key}', 'apikey': self.key}
        headers.update(extra or {})
        return headers

    def _url(self, path):
        return f'{self.base}/{self.bucket}/{quote(path)}'

    def upload(self, path, data, mime):
        import requests
        res = requests.post(self._url(path), data=data, timeout=60,
                            headers=self._headers({'Content-Type': mime, 'x-upsert': 'true'}))
        if res.status_code >= 300:
            raise FileStorageError(f'Faylni saqlab bo\'lmadi ({res.status_code}).')

    def download(self, path):
        import requests
        res = requests.get(f'{self.base}/authenticated/{self.bucket}/{quote(path)}', timeout=60,
                           headers=self._headers())
        if res.status_code == 404 or res.status_code == 400:
            raise FileStorageError('Fayl topilmadi.')
        if res.status_code >= 300:
            raise FileStorageError(f'Faylni olib bo\'lmadi ({res.status_code}).')
        return res.content

    def delete(self, paths):
        import requests
        if not paths:
            return
        requests.delete(f'{self.base}/{self.bucket}', json={'prefixes': list(paths)}, timeout=30,
                        headers=self._headers({'Content-Type': 'application/json'}))


_storage = None


def get_file_storage():
    global _storage
    if _storage is None:
        kind = getattr(settings, 'FILE_STORAGE', 'local')
        if kind == 'memory':
            _storage = MemoryFileStorage()
        elif kind == 'supabase':
            _storage = SupabaseStorage(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY,
                                       settings.SUPABASE_BUCKET)
        else:
            _storage = LocalFileStorage(Path(settings.BASE_DIR) / '.local_files')
    return _storage


def set_file_storage(storage):
    """Testlar uchun: saqlash qatlamini almashtiradi (None — sozlamadan qayta o'qiydi)."""
    global _storage
    _storage = storage
