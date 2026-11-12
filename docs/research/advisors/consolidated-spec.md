# PRD & SPEC hiện hành — Hồ sơ skill giảng viên, KLTN GVHD và snapshot theo kỳ

**Ngày cập nhật:** 05/11/2026\
**Trạng thái:** triển khai pipeline dữ liệu đang tiếp diễn; **chưa có snapshot đủ điều kiện train/evaluate mới**.\
**Baseline đối chiếu:** `docs/advisor_skill_semester_prd_spec.md` v1.3 ngày 02/11/2026, cùng `PRD.md`, `SPEC.md` và `data/AGENTS.md`.\
**Mục đích tài liệu này:** thay thế phần “trạng thái implementation” rải rác bằng một contract vận hành duy nhất. Không xóa hoặc làm mất hiệu lực provenance của PRD/SPEC cũ.

---

## 1. Tóm tắt quyết định

Mục tiêu vẫn là xây dựng hồ sơ chuyên môn giảng viên có bằng chứng, kết hợp:

1. Công trình, tài liệu và repository thuộc đúng giảng viên;
2. Kinh nghiệm hướng dẫn rút ra từ khóa luận có liên kết GVHD đã xác minh;
3. Yêu cầu chuyên môn của sinh viên có tại thời điểm quyết định;
4. Snapshot có hash, cutoff, review và split xác định;
5. Hungarian/Greedy/Random làm baseline trước khi nghiên cứu RL hai cấp.

Pipeline trích skill, công thức điểm và adapter matching đã có. Phần còn lại không phải là “điền dữ liệu cho đủ”, mà là thu nguồn còn thiếu, xác minh liên kết người–công trình/GVHD, chứng minh `available_at`, khử trùng, review và đóng snapshot. Không được biến output crawler/parser thành approval hay training data.

### 1.1. Trạng thái tổng quát

| Hạng mục | Trạng thái | Kết luận vận hành |
|---|---|---|
| Taxonomy, trích xuất claim và score formula | Có implementation | Chỉ dùng claim đã review theo gate. |
| Crawl lịch sử đến hết năm 2024 | Đã chạy một phần, có checkpoint | Chưa hoàn tất toàn văn/identity/availability/dedup. |
| Crawl riêng năm dương lịch 2025 | Có entrypoint scoped theo năm | Chưa có bằng chứng trong repo rằng đợt crawl đầy đủ đã chạy xong. |
| Đọc repo GitHub | Đã đọc phần lớn nguồn và có resume | Một số repo timeout; claim còn pending review. |
| Chuẩn bị liên kết GVHD/KLTN | Đã tạo candidate/job | Không có approval GVHD hay score GVHD thật. |
| Trích skill KLTN | Đã chạy pilot và batch 2025.1 | Claim vẫn pending, toàn văn chưa đủ ở các job liên quan. |
| Review/availability/duplicate resolution | Có review pack + close contract | Chưa có reviewer decision thật đạt gate. |
| Snapshot đóng kỳ | Có implementation | Chưa có closed snapshot `ready_for_training` từ dữ liệu thật. |
| Split 2025.1 | Có grouped split theo `thesis_id` | Chưa chạy trên cohort/contract đã review. |
| Hungarian baseline từ điểm mới | Có implementation | Chưa chạy trên snapshot đủ điều kiện. |
| RL train/evaluate 2025.1 từ điểm mới | Chưa làm | Bị chặn bởi snapshot/requirements/outcomes/contract. |
| 2025.3 external test | Có guard chặn train | Không được mở làm dữ liệu train; benchmark lịch sử đã quan sát không phải final test mới. |

---

## 2. Phạm vi, thuật ngữ và nguyên tắc không thay đổi

### 2.1. Các mốc thời gian phải tách riêng

| Trường | Ý nghĩa | Không được suy từ |
|---|---|---|
| `event_date` / `event_year` | Ngày/năm công trình, commit hoặc sự kiện | Tên thư mục, ngày crawl, tiêu đề có năm. |
| `academic_term` | Kỳ học vụ thực tế tại thời điểm sự kiện | Pool lưu trữ hoặc version model. |
| `available_at` | Thời điểm bằng chứng thực sự có thể dùng cho quyết định | `event_date`, publication year, crawl time, file name. |
| `collected_at` | Thời điểm pipeline thu được nguồn | `available_at`. |
| `source_pool` / `storage_pool` | Vị trí corpus/snapshot theo protocol | `academic_term`. |
| `cutoff` | Mốc prediction-time cho một snapshot | Cuối kỳ nếu quyết định diễn ra đầu kỳ. |

Múi giờ học vụ là **Asia/Saigon**. Academic term thực tế:

- Tháng 09–12 năm Y: `Y.1`;
- Tháng 01–05 năm Y: `(Y-1).2`;
- Tháng 06–08 năm Y: `(Y-1).3`.

### 2.2. Quy tắc mới cho corpus giảng viên năm 2025

Quy tắc mới thay cách **xếp dữ liệu giảng viên**, không thay cách chia cohort sinh viên:

- Mọi advisor artifact có **năm sự kiện 2025** được lưu/staging vào `data/2025.1/advisors/faculty_corpus/`.
- Mỗi dòng vẫn giữ `academic_term` thật. Ví dụ event tháng 03/2025 có `academic_term=2024.2` nhưng `storage_pool=2025.1`.
- Dữ liệu giảng viên đến 2024 ở pool `2024`.
- Các event sau 31/08/2026 không tự tạo kỳ/pool mới.
- `2025.3` là external test; không dùng làm input train, fit feature, model selection hoặc tuning.

### 2.3. Chính sách evidence và review

1. `pending`, `needs_review`, `rejected`, `unknown`, `null` không đồng nghĩa với `approved`, `false` hoặc `0`.
2. Parser/crawler thành công chỉ tạo candidate claim; không chứng minh identity, supervision, document match, public availability hoặc chuyên môn.
3. Claim được `approved` phải có decision có `evidence_id`, `reviewer`, `reviewed_at` có timezone và `reason`.
4. Review ledger chỉ cập nhật metadata review; không được tự ghi đè `available_at`, `split`, `training_eligibility`, cutoff hoặc source provenance.
5. Thiếu bằng chứng cho một skill phải giữ `null`/`insufficient_data`; không renormalize trọng số và không thay bằng 0.
6. Không tạo outcome, preference, quota, faculty presence hoặc approval từ PDF khóa luận/crawler.

---

## 3. Yêu cầu chức năng và trạng thái đối chiếu PRD/SPEC cũ

### 3.1. Thu thập và chuẩn hóa corpus giảng viên

| Mã | Yêu cầu trong PRD/SPEC cũ | Đã làm | Còn thiếu / gate |
|---|---|---|---|
| C1 | Duyệt nguồn công khai theo danh bạ 17 giảng viên, lưu raw/hash/receipt | Có collector seed, collector paper/Git, queue Chrome, registry và manifest | Không đảm bảo “toàn bộ Internet”; phải báo coverage/source blocked. |
| C2 | Crawl lịch sử theo event time, không dùng tên pool làm ngày | Có audit calendar và package lịch sử đến 2024 | Còn nguồn title-only/unknown date/full text pending. |
| C3 | Ưu tiên full text trước title-only và repo thiếu nội dung/timeout | Có job PDF, Chrome queue, Git batch/resume và retry hướng cache | Chrome/browser chưa khả dụng trong checkpoint; 6 repo extraction timeout cần chunk retry. |
| C4 | Xác minh person–article/document/repository link | Có attribution candidates, quarantine logic và review fields | Chưa có reviewer approval đầy đủ; không claim skill chuyên môn đã xác minh. |
| C5 | Khử trùng mirror/PDF/DOI/title variant trước score | `mark_duplicate_candidates()` gom nhóm theo DOI hoặc tiêu đề chuẩn hóa trong cùng giảng viên, gắn `duplicate_group_id` và `dedup_status`; `partition` tự chạy bước này; scorer chặn trùng theo `artifact_id` | Không tự gộp hay xóa dòng. Reviewer vẫn phải chọn artifact chuẩn cho mỗi nhóm `pending_review`. |
| C6 | Mở crawl riêng năm dương lịch 2025 | `collect_advisor_history_2024.py --calendar-year 2025` đã có | Chưa chứng minh đã chạy hết request budget, Chrome queue, full text và review cho toàn năm. |
| C7 | Đưa dữ liệu năm 2025 vào `2025.1/advisors/`, giữ term/availability | Có `partition` trong `close_advisor_skill_snapshot.py`, cho phép `--data-root data` | Chưa được phép coi staging là evidence reviewed/training-ready. |

### 3.2. Trích skill và tính score giảng viên

| Mã | Yêu cầu trong PRD/SPEC cũ | Đã làm | Còn thiếu / gate |
|---|---|---|---|
| S1 | Trích title/abstract/full text/repo theo taxonomy, giữ locator/completeness | Có `advisor_skill_collection`, `advisor_skill_extraction`, repository reader và `advisor_skill_pipeline extract` | Claim raw chưa phải skill verified. |
| S2 | Không gọi title-only là full text; partial phải chặn final | Có `content_scope`, `content_completeness`, expected units và scorer gate | Còn nhiều paper/repo/thesis partial hoặc chưa mở toàn văn. |
| S3 | Profile `= 0.4P + 0.6E` | Có implementation `advisor_skill_scores.py` | Chỉ xuất profile hoàn chỉnh khi prediction/evidence đều đủ reviewed. |
| S4 | GVHD = trung bình các KLTN có dùng skill | Có scorer channel `thesis`; `not_used` không vào mẫu số, used score 0 vẫn hợp lệ | Chưa có claim GVHD approved đủ điều kiện. |
| S5 | Final `= 0.5 profile + 0.5 GVHD` | Có implementation, không renormalize khi thiếu component | Chưa có score final thật để train/evaluate. |
| S6 | Dedupe same channel/artifact/skill và báo mâu thuẫn | Có conflict detection trong scorer | Cần canonical artifact mapping/review upstream hoàn chỉnh. |
| S7 | Không đưa 2025.3 vào score training | Có guard trong pipeline/snapshot | Phải tiếp tục giữ guard ở mọi caller mới. |

### 3.3. KLTN, liên kết GVHD và split

| Mã | Yêu cầu trong PRD/SPEC cũ | Đã làm | Còn thiếu / gate |
|---|---|---|---|
| T1 | Tìm candidate GVHD ở nhãn cover, đối chiếu roster, không lấy tên bất kỳ trong nội dung | Có `prepare_advisor_supervision.py`, evidence span/quote/match method | 208 candidate links vẫn là candidate, không phải link đã xác nhận. |
| T2 | Đọc toàn văn KLTN, loại bibliography, ghi OCR/partial | Có cache/PyMuPDF/page inventory; bibliography exclusion; partial khi không đủ text | OCR/full text còn thiếu ở một phần job; không được fake complete. |
| T3 | Trích tiếp hồ sơ KLTN, ưu tiên 2025.1 | Đã chuẩn bị 208 jobs; pilot 5 và batch thêm 10 `2025.1` tạo evidence | Còn 193 theo trạng thái yêu cầu; cần resume batch, review content/link/time. |
| T4 | Giữ cùng khóa luận ở cùng split | Extractor giữ `student_ids`, `thesis_id`, `supervision_id`; grouped split theo `thesis_id` đã có | Chưa chạy trên input review-complete 2025.1. |
| T5 | Chia train/validation/test theo student, không leakage | Split deterministic 70/15/15 theo nhóm `thesis_id`, mỗi phía có ít nhất một nhóm; không dùng identity làm feature | Cần contract cohort/requirements thật, kiểm tra shared student xuyên kỳ và freeze split. |
| T6 | 2025.3 là tập test ngoài | Có chặn source/student `2025.3` trong training split/snapshot | Không được tái tuyên bố unseen final test vì training guide nói kỳ này đã từng được mở. |

### 3.4. Snapshot, matching, baseline và RL

| Mã | Yêu cầu trong PRD/SPEC cũ | Đã làm | Còn thiếu / gate |
|---|---|---|---|
| M1 | Snapshot immutable có hashes, cutoff, scope, taxonomy/code versions | `advisor_skill_pipeline` đã có manifest batch; CLI close ghi input/output hash, status, blocking reasons, contract hash | Chưa có closed snapshot từ dữ liệu thật đạt `ready_for_training`. |
| M2 | Không đủ evidence trả trạng thái rõ | `close_snapshot()` trả `not_evaluable`, `baseline.status=not_run` | Cần vận hành thật và lưu receipt của các gate fail/pass. |
| M3 | Yêu cầu sinh viên phải predecision, reviewed, available trước cutoff | `build_skill_problem()` kiểm tra review/scope/evidence_scope/available_at | Chưa có requirements 2025.1 đã review theo contract. |
| M4 | Hungarian, Greedy, Random cùng utility/constraints trước RL | `close` chạy cả ba baseline trên cùng `AllocationProblem`, ghi `baseline_hungarian.json`, `baseline_greedy.json`, `baseline_random.json`; Hungarian quyết định trạng thái | Chưa có baseline thực từ score mới/constraints operator thật. |
| M5 | Mask quota/eligibility/presence; không suy operator constraints | Adapter nhận capacities/eligible/present bắt buộc | Chưa có operator contract 2025.1 đã đóng. |
| M6 | Train/evaluate 2025.1 sau snapshot; external 2025.3 sau freeze | RL framework/nested learning có sẵn, adapter yêu cầu checkpoint contract mới | Chưa train/evaluate với điểm mới; không gắn score mới vào checkpoint cũ. |
| M7 | Acceptance, retention, promotion tách riêng | `production_promoted=false`; score/snapshot không cấp quyền deploy | Chưa có config metric/margin/forgetting/seed đã freeze cho thí nghiệm mới. |

---

## 4. Trạng thái dữ liệu đã quan sát

Các số dưới đây là inventory/progress tại checkpoint, **không phải số evidence đã được duyệt hoặc dữ liệu train**.

### 4.1. Lịch sử giảng viên đến hết 2024

Theo `outputs/advisor_history_through_2024/README.md`:

- 459 dòng candidate trong package lịch sử; 60 Git snapshots theo commit.
- 396 dòng công trình/giải thưởng candidate:
  - 376 title-only;
  - 11 PDF toàn văn, 144 trang, còn chờ xác minh tác giả;
  - 2 tài liệu quarantine do gán người không chắc chắn;
  - 7 award metadata-only.
- 61 tác vụ Chrome chờ thực hiện tại checkpoint cũ.
- 27 dòng sau 2024 bị loại; 184 dòng không xác định năm không vào package đóng.
- Toàn bộ candidate lịch sử có `available_at=null` và `historical_training_eligible=false` tại package đó.
- Corpus lịch sử chưa có dòng nào đủ điều kiện historical training.

### 4.2. Partition corpus cũ

Manifest staging cũ ghi:

- 365 candidate legacy vào `2024`;
- 18 candidate legacy vào `2025.1`;
- `historical_training_eligible_rows=0`;
- staging không phải training snapshot và chưa merge/dedup với crawl package.

Quy tắc mới trong tài liệu này thay partition advisor: record event year 2025 đi `2025.1/advisors/`, vẫn giữ `academic_term` thực.

### 4.3. Repository source

Checkpoint 05/11 ghi batch 122 repo:

- 99 `read_pending_review`;
- 6 `extraction_timeout`;
- 12 fork bị loại;
- 5 repository rỗng.

Các claim source đã trích vẫn pending review; timeout phải retry từ cache/chunk, không tải Git lại khi cache pin/hash còn hợp lệ.

### 4.4. KLTN/GVHD

Checkpoint chuẩn bị supervision ghi:

- 208 candidate supervision links và 208 thesis skill jobs;
- 250 thesis unique đã đọc trong preparation;
- jobs theo pool: 101 (`2024`), 58 (`2025.1`), 49 (`2025.2`);
- 60 unresolved;
- 20 sinh viên external `2025.3` bị loại khỏi training preparation;
- 0 identity approvals, 0 score GVHD published.

Đã trích skill thực nghiệm trên 5 KLTN pilot và thêm 10 KLTN `2025.1`; batch 10 tạo 151 candidate skill evidence. Các claim/liên kết vẫn pending, `available_at` chưa có và không được dùng để xuất score.

---

## 5. Thiết kế kỹ thuật hiện hành

### 5.1. Thành phần chính

| Thành phần | Trách nhiệm |
|---|---|
| `src/data_pipeline/advisor_skill_collection.py` | Thu URL seed trực tiếp, raw/status/Chrome queue. |
| `src/data_pipeline/advisor_skill_extraction.py` | Trích taxonomy claim có locator/completeness từ text units. |
| `scripts/collect_advisor_history_2024.py` | Crawl dated works; mặc định đến 2024, hoặc `--calendar-year 2025` cho đợt riêng. |
| `scripts/read_advisor_repository_batch.py` | Đọc source Git pin SHA, checkpoint/resume/time bounded. |
| `scripts/prepare_advisor_supervision.py` | Tạo candidate supervision links và thesis jobs; không approve. |
| `scripts/advisor_skill_pipeline.py` | `collect`, `extract`, `score`; bảo toàn thesis/student/supervision metadata. |
| `src/features/advisor_skill_scores.py` | Công thức profile/GVHD/final, dedup, cutoff/split/scope/review gates. |
| `src/features/advisor_skill_matching.py` | Dựng `AllocationProblem` từ final score và requirement predecision. |
| `src/data_pipeline/advisor_skill_snapshot.py` | Partition, review-decision gate, thesis-group split, close/not-evaluable receipt. |
| `scripts/close_advisor_skill_snapshot.py` | CLI `partition`, `review-pack`, `close`; tạo manifest và baseline receipt. |
| `src/baselines/rebuild_baselines.py` | Hungarian, Greedy, Random với cùng constraint contract. |

### 5.2. Công thức và null semantics

Với từng cặp `(advisor_id, skill_id)`:

```text
P       = mean(prediction claims có usage_status=used)
E       = mean(evidence claims có usage_status=used)
profile = 0.4 * P + 0.6 * E

GVHD    = mean(thesis claims có usage_status=used)
final   = 0.5 * profile + 0.5 * GVHD
```

Điều kiện:

- `profile` là `null` nếu thiếu P hoặc E.
- `GVHD` là `null` nếu chưa có KLTN hợp lệ dùng skill đó.
- `final` là `null` nếu thiếu profile/GVHD hoặc có evidence partial/unreviewed cho skill đang xét.
- Không dùng claim `not_used`/`unknown` trong mẫu số.
- `usage_status=used` với score `0` là observation hợp lệ, không bị lọc như missing.
- Không chia lại trọng số để bù component thiếu.

### 5.3. Close snapshot contract

`close` chỉ gọi Hungarian khi đồng thời có:

1. Registry advisor hợp lệ;
2. Claim profile/thesis đã `approved`, đúng `training_eligibility`, `available_at` có timezone và không sau cutoff;
3. Score final `complete`;
4. Requirements sinh viên đã approved, `evidence_scope=predecision_requirement`, available trước cutoff;
5. `student_ids`, capacities, eligibility và presence do operator cung cấp đầy đủ;
6. Split grouped theo `thesis_id`, không có thesis cross-split;
7. Không có source/student `2025.3` trong training snapshot.

Nếu thiếu bất cứ điều kiện nào, output phải giữ:

```json
{
  "status": "not_evaluable",
  "baseline": {"status": "not_run"},
  "production_promoted": false
}
```

với `blocking_reasons` cụ thể. Đây là kết quả đúng; không phải lỗi được phép né bằng data fallback hoặc mock.

---

## 6. Quy trình vận hành chuẩn còn lại

### Bước A — Hoàn tất crawl đến 2024

1. Resume từ checkpoint/package hiện hành, ưu tiên:
   - paper thiếu full text;
   - Chrome queue/source landing còn chưa thử;
   - repo timeout/thiếu content;
   - PDF attribution/document match;
   - canonical work dedup.
2. Dùng cache/hash/pinned commit; không download lại repo khi retry extraction chunk.
3. Ghi receipt cho mỗi request/browser action; blocked/CAPTCHA là trạng thái thật, không bypass.
4. Tạo review pack; reviewer xác minh identity, article-document match, availability và duplicate groups.

### Bước B — Crawl và staging năm 2025

```powershell
python scripts/collect_advisor_history_2024.py `
  --calendar-year 2025 `
  --max-requests 100 `
  --output outputs/advisor_history_calendar_2025

python scripts/close_advisor_skill_snapshot.py partition `
  --candidates outputs/advisor_history_calendar_2025/dated_advisor_candidates.jsonl `
  --data-root data `
  --output outputs/advisor_history_calendar_2025/calendar_partition
```

`partition` chỉ append file corpus có suffix hash; không ghi đè corpus, không set review status/availability và không đóng snapshot.

### Bước C — Hoàn tất KLTN/GVHD

1. Resume 193 job còn lại, ưu tiên `2025.1`.
2. Đọc toàn bộ expected text unit hoặc đánh dấu partial/OCR required.
3. Review cover-label span, roster match, student identity, thesis document hash và temporal availability.
4. Chỉ reviewer quyết định link `supervision_review_status=approved` và claim review status.
5. Sinh review pack cho claim profile/thesis; không dùng decision để bịa fields evidence.

### Bước D — Đóng 2025.1 và baseline

1. Freeze cutoff thực tế của quyết định.
2. Freeze requirements predecision, roster, capacities, eligibility, presence và split seed.
3. Chạy `close`.
4. Nếu `not_evaluable`, xử lý đúng `blocking_reasons`, không train.
5. Nếu `ready_for_training`, lưu immutable manifest, chạy Hungarian/Greedy/Random cùng contract trước RL.

### Bước E — Train/evaluate nghiên cứu

Chỉ sau khi snapshot đủ gate:

1. Train/validation theo 2025.1 với train-only feature fit;
2. Freeze primary metric, margin, coverage floor, forgetting tolerance, seed và config trước run;
3. Chạy baseline, warm start/parent và RL theo cùng constraints;
4. Giữ candidate/rejected lineage; không promote tự động;
5. `2025.3` giữ ngoài train/model selection. Vì đã từng được mở trong nghiên cứu trước, không được gọi là final unseen test mới.

---

## 7. Tiêu chí nghiệm thu cập nhật

### 7.1. Data readiness

- [ ] Toàn bộ source trong scope có status/receipt: success, partial, blocked, deferred hoặc unresolved rõ ràng.
- [ ] Full text/document inventory, hash, completeness và locator có thể truy vết.
- [ ] Identity, author/document association, repository ownership và supervision link có decision reviewer khi cần cho score.
- [ ] `available_at` có timezone và bằng chứng; không có field được suy từ crawl time/event year.
- [ ] Duplicate/canonical `artifact_id` đã xử lý và mâu thuẫn được resolved/rejected.
- [ ] Mọi raw/pending evidence nằm ngoài scorer strict.

### 7.2. Score/snapshot readiness

- [ ] Score component đúng 40/60 và 50/50, không renormalize.
- [ ] Missing/unknown là `null`, không phải zero.
- [ ] GVHD chỉ tính thesis có dùng skill đó.
- [ ] Manifest có input/output/taxonomy/code hashes, cutoff, scope, status, blocking reasons và feature contract hash.
- [ ] Split theo thesis/student không leakage; 2025.3 bị chặn ở input training.
- [ ] Hungarian chạy feasible trên cùng operator constraints trước RL hoặc output `not_evaluable` có lý do.

### 7.3. Research readiness

- [ ] Có config freeze metric/margin/tolerance/seed/split trước training.
- [ ] Cohort/requirements/outcome provenance được review; không dùng KLTN hoàn thành làm requirement prediction-time.
- [ ] Train-only transforms, fixed validation và external evaluation protocol được ghi manifest.
- [ ] Không tự tuyên bố RL hơn Hungarian, historical skill recovery là ground truth, hoặc production-ready khi chưa có evidence.

---

## 8. Verification và giới hạn kỹ thuật hiện tại

Các test bao phủ score, matching và snapshot contract: partition 2025, khử trùng DOI/tiêu đề, review provenance, cấm review ghi đè availability/scope, split 70/15/15 theo thesis, guard 2025.3, pending claims, calendar-year crawl, CLI `partition` ghi vào data root có sẵn, và ba baseline.

Kết quả chạy ngày 05/11/2026:

```text
32 passed, 5 subtests passed
```

Lệnh chạy lại:

```powershell
python -m pytest -q `
  tests/test_advisor_history_2024.py `
  tests/test_advisor_skill_scores.py `
  tests/test_advisor_skill_matching.py `
  tests/test_advisor_skill_snapshot.py `
  tests/test_close_advisor_skill_snapshot_cli.py
```

Môi trường Conda hiện có in `RequestsDependencyWarning` (urllib3/chardet lệch phiên bản). Warning này không làm test fail, nhưng nên đồng bộ lại dependency trước khi chạy crawl dài.

---

## 9. Những điều tài liệu này không tuyên bố

- Không tuyên bố đã crawl hết Internet, toàn bộ năm 2025 hoặc toàn bộ source queue.
- Không tuyên bố 17 giảng viên đã có điểm chuyên môn verified.
- Không tuyên bố 208 candidate GVHD là 208 liên kết hướng dẫn đúng.
- Không tuyên bố score mới đã được đưa vào checkpoint/model/serving.
- Không tuyên bố train/evaluation 2025.1 từ điểm mới đã diễn ra.
- Không tuyên bố 2025.3 là final test hoàn toàn chưa nhìn thấy.
- Không cấp quyền production allocation, model promotion hoặc quyết định học vụ.

Mọi tuyên bố trên chỉ có thể thay đổi khi xuất hiện snapshot immutable có review decisions, availability evidence, operator contract, baseline result và evaluation manifest tương ứng.