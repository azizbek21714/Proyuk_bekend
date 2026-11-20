"""Ataylab o'zgartirilgan xatti-harakat uchun tanlangan ssenariylarning kutilgan javobini yangilaydi.

    venv/Scripts/python.exe tools/golden/rebaseline.py scenario_name [...]

Faqat diff ko'rib chiqilib, o'zgarish kutilgan deb topilgan ssenariylar uchun ishlating
(masalan, rollar qo'shilganda rahbar o'qituvchilarning ko'rish huquqi). Admin ssenariylari
o'zgarmasligi kerak.
"""
import sys

from replay import RESPONSES_DIR, SCENARIOS, load_store, replay


def main(names):
    if not names:
        raise SystemExit('Ssenariy nomini bering.')
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        raise SystemExit(f"Noma'lum ssenariy: {', '.join(unknown)}")
    store = load_store()
    base = store.snapshot()
    for name in names:
        (RESPONSES_DIR / f'{name}.json').write_text(replay(store, base, name), encoding='utf-8')
        print(f'yangilandi: {name}')


if __name__ == '__main__':
    main(sys.argv[1:])
