"""Shaxsiy rejadagi ishlar (O'quv-uslubiy, Ilmiy-tadqiqot, Ustoz-shogird) va bajarilish foizi.

Qatorlar reja.data dagi hujjatdan olinadi (frontend reja-shablon.tsx bilan bir xil tuzilma):
  data.variants[stavka].doc.{uslubiy, ilmiy, ustozShogird}  (eski: data.doc.{...})
Har bir qatorning barqaror `id` si bor — ish dalili shu id ga bog'lanadi.

Foiz = qabul qilingan qatorlarning reja soatlari / barcha qatorlarning reja soatlari × 100.
Bo'limda soat ko'rsatilmagan bo'lsa, qatorlar soni bo'yicha hisoblanadi.
"""
from decimal import Decimal, InvalidOperation

SECTIONS = (
    ('uslubiy', 'uslubiy', "O'quv-uslubiy ishlar"),
    ('ilmiy', 'ilmiy', 'Ilmiy-tadqiqot ishlari'),
    ('ustoz', 'ustozShogird', 'Ustoz-shogird ishlari'),
)
SECTION_KEYS = tuple(s[0] for s in SECTIONS)


def _num(value):
    try:
        return Decimal(str(value).replace(',', '.').strip() or '0')
    except (InvalidOperation, ValueError):
        return Decimal('0')


def plan_docs(reja):
    """{stavka: doc} — rejadagi barcha variantlar hujjatlari."""
    data = reja.data if isinstance(reja.data, dict) else {}
    variants = data.get('variants')
    if isinstance(variants, dict) and variants:
        return {rate: (v.get('doc') or {}) for rate, v in variants.items() if isinstance(v, dict)}
    doc = data.get('doc')
    if isinstance(doc, dict):
        return {data.get('stavka') or 'rate_1': doc}
    return {}


def plan_rows(reja):
    """Rejadagi uch bo'lim qatorlari: [{bolim, id, nomi, rejaSoat, muddatReja, variant}]."""
    rows, seen = [], set()
    for rate, doc in plan_docs(reja).items():
        for key, doc_key, _ in SECTIONS:
            for item in doc.get(doc_key) or []:
                if not isinstance(item, dict) or not item.get('id'):
                    continue
                ident = (key, str(item['id']))
                if ident in seen:
                    continue
                seen.add(ident)
                rows.append({
                    'bolim': key,
                    'id': str(item['id']),
                    'nomi': str(item.get('nomi') or '').strip(),
                    'rejaSoat': float(_num(item.get('rejaSoat'))),
                    'muddatReja': str(item.get('muddatReja') or ''),
                    'variant': rate,
                    # Rejadagi qiymat belgilari (kartochkalar uchun): ilmiy — Scopus/WoS va Respub.,
                    # uslubiy — bet soni
                    'scopus': str(item.get('scopus') or '').strip(),
                    'respub': str(item.get('respub') or '').strip(),
                    'rejaBet': str(item.get('rejaBet') or '').strip(),
                })
    return [r for r in rows if r['nomi'] or r['rejaSoat']]


def find_row(reja, bolim, qator_id):
    return next((r for r in plan_rows(reja) if r['bolim'] == bolim and r['id'] == str(qator_id)), None)


def _percent(done, total):
    return round(float(done) / float(total) * 100, 1) if total else 0.0


def compute(reja, dalillar):
    """Bo'limlar bo'yicha va umumiy bajarilish natijasi.

    dalillar — shu rejaga tegishli IshDalili ro'yxati.
    """
    by_row = {(d.bolim, d.qator_id): d for d in dalillar}
    rows = plan_rows(reja)
    bolimlar = []
    total_hours = done_hours = Decimal('0')
    total_rows = done_rows = 0
    for key, _, label in SECTIONS:
        section_rows = [r for r in rows if r['bolim'] == key]
        hours = sum((Decimal(str(r['rejaSoat'])) for r in section_rows), Decimal('0'))
        accepted = [r for r in section_rows
                    if (d := by_row.get((key, r['id']))) is not None and d.holat == 'qabul_qilindi']
        acc_hours = sum((Decimal(str(r['rejaSoat'])) for r in accepted), Decimal('0'))
        foiz = _percent(acc_hours, hours) if hours else _percent(len(accepted), len(section_rows))
        bolimlar.append({
            'bolim': key, 'nomi': label,
            'qatorlar': len(section_rows), 'qabulQilingan': len(accepted),
            'rejaSoat': float(hours), 'bajarilganSoat': float(acc_hours), 'foiz': foiz,
        })
        total_hours += hours
        done_hours += acc_hours
        total_rows += len(section_rows)
        done_rows += len(accepted)
    umumiy = _percent(done_hours, total_hours) if total_hours else _percent(done_rows, total_rows)
    return {
        'oquvYili': reja.oquv_yili,
        'bolimlar': bolimlar,
        'qatorlar': total_rows, 'qabulQilingan': done_rows,
        'rejaSoat': float(total_hours), 'bajarilganSoat': float(done_hours),
        'umumiyFoiz': umumiy,
    }
