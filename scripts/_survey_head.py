"""Temporary: print survey header and value counts (UTF-8 to file)."""
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
path = next((ROOT / 'data').glob('Khảo sát*.xlsx'))
wb = load_workbook(path, read_only=True, data_only=True)
out = []
for sheet in wb:
    rows = list(sheet.values)
    out.append(f'sheet={sheet.title} rows={len(rows)}')
    for i, h in enumerate(rows[0]):
        out.append(f'  col{i} {chr(65+i) if i < 26 else i}: {h}')
    out.append('types: ' + str(Counter(str(r[1]) for r in rows[1:] if len(r) > 1)))
    out.append('terms: ' + str(Counter(str(r[18]) for r in rows[1:] if len(r) > 18).most_common(12)))
    out.append('sample H: ' + ' || '.join(str(r[7])[:80] for r in rows[1:6] if len(r) > 7))
(ROOT / 'outputs/_survey_head.txt').write_text('\n'.join(out), encoding='utf-8')
print('ok')
