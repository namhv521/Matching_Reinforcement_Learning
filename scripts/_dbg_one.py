import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.data_pipeline import evidence_context as ec
from src.data_pipeline.normalization import load_taxonomy, normalize_mentions

text = 'Amazon là hình mẫu điển hình về việc sử dụng AI để tối ưu hóa toàn bộ mạng lưới.'
m = [x for x in normalize_mentions(text, load_taxonomy()) if x['tag'] == 'ai'][0]
out = []
r = ec.classify_mention(text, m)
out.append(repr(r['reason']))
for p in ec.DIRECT_RESULT_RE:
    if p.search(text):
        out.append('RESULT ' + p.pattern[:60] + ' -> ' + p.search(text).group(0))
for p in ec.THIRD_PARTY_SUBJECT_RE:
    s = p.search(text)
    out.append('THIRD ' + str(bool(s)) + (' ' + s.group(0) if s else ''))
(ROOT / 'outputs/_dbg.txt').write_text('\n'.join(out), encoding='utf-8')
