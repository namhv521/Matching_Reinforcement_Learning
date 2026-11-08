# Hướng dẫn chạy pipeline skill giảng viên

Ngày: 02/11/2026. Theo `advisor_skill_semester_prd_spec.md` v1.3.

## 1. Phần đã triển khai

| Thành phần | Chức năng hiện có |
|---|---|
| `src/data_pipeline/advisor_skill_collection.py` | Thu exact URL trong seed, lưu raw/status và hàng đợi Chrome |
| `src/data_pipeline/advisor_skill_extraction.py` | Trích claim theo taxonomy từ các text unit được cung cấp, giữ locator và completeness |
| `src/features/advisor_skill_scores.py` | Tính điểm skill từ claim đã rà soát, lọc thời gian/split/scope và chống duplicate |
| `scripts/advisor_skill_pipeline.py` | CLI `collect`, `extract`, `score`; xuất manifest và hash |

Đây là batch pipeline ban đầu. Chưa có traversal toàn bộ paper/GitHub, tự động xác minh GVHD, hoặc tích hợp feature mới vào RL/serving.

Chạy lệnh từ `C:\Su\KLTNv2\KLTN`. Python hiện kiểm tra được: `C:\Users\Lenovo\miniconda3\python.exe`, phiên bản 3.12.9. Runtime này có pytest, requests, BeautifulSoup và PyMuPDF. Không cần cài dependency mới cho các lệnh dưới đây.

## 2. Thu thập seed

```powershell
python scripts/advisor_skill_pipeline.py collect --seed-csv data/2024/advisors/faculty_profiles/advisors_profile.csv --max-urls 4 --output outputs/advisor_skills/pilot_collection
```

`--max-urls` là số URL trực tiếp tối đa, không phải số giảng viên. Collector kiểm tra toàn bộ seed và giữ registry đầy đủ. URL ngoài ngân sách có status `budget_exceeded`; không coi đó là đã crawl. Chỉ chấp nhận HTTPS của các nền tảng trong danh bạ; HTTP redirect không được tự theo. Response giới hạn 5 MiB. Thu mỗi seed một lần trong run; không ghi đè run đã tồn tại.

Output gồm `registry.jsonl`, `sources.jsonl`, `profiles.jsonl`, `chrome_queue.jsonl`, `collection_report.json` và `raw/`. Profile official được parse bằng parser có sẵn. Nội dung nguồn bên ngoài được lưu nhưng vẫn cần review pagination/completeness; title danh mục không được gọi là full text bài báo.

### Fallback Chrome

`chrome_queue.jsonl` là danh sách công việc cần agent/người điều khiển Chrome thực hiện. Collector **chưa tự mở Chrome**. Agent dùng công cụ Chrome/computer-use, mở đúng URL, lấy text thực tế, xử lý phân trang và ghi trạng thái truy cập. Không vượt CAPTCHA hoặc tự xuất cookie.

Sau thao tác thật, lưu capture bằng API:

```python
from src.data_pipeline.advisor_skill_collection import record_chrome_capture

receipt = record_chrome_capture(
    run_dir, request_id,
    text=actual_browser_text,
    final_url=actual_final_url,
    status="success",
    captured_at=actual_timestamp_with_timezone,
)
```

`request_id` phải tồn tại trong queue. Các biến trong ví dụ do phiên điều khiển Chrome cung cấp, không phải nội dung mẫu để import. Status hợp lệ: `success`, `partial`, `blocked`, `requires_user_action`. Capture thành công cần text không rỗng, URL cùng host seed và timestamp có múi giờ.

Receipt và text được lưu bất biến trong `chrome_captures/<request_id>/`. Queue gốc không bị sửa; đối soát queue với receipt để xác định việc còn chờ. Capture mặc định vẫn là `partial_full_text`, chưa xác minh availability lịch sử và chưa có reviewer approval. Không dùng nó trực tiếp như dữ liệu training đã duyệt.

## 3. Trích xuất text unit

CLI nhận JSONL, mỗi dòng là một job với các trường:

| Trường | Ý nghĩa |
|---|---|
| `artifact_id`, `advisor_id` | ID công trình canonical và advisor trong registry |
| `content_scope` | `title_only`, `abstract_only`, `partial_full_text`, `full_text_complete` |
| `text_units` | Danh sách `{unit_id, text, section?}`; mỗi unit là trang/section/file |
| `expected_units` | Danh sách ID đầy đủ từ kiểm kê nguồn; cần để xác nhận đã xử lý toàn văn |
| `available_at` | Timestamp khả dụng có bằng chứng, không tự lấy ngày crawl |
| `split` | `train`, `validation` hoặc `test`, theo membership đã khóa |
| `training_eligibility` | Phạm vi đã xác minh; thiếu thì `unresolved` |
| `source_url` | URL truy vết nguồn |
| `channel` | Đặt `thesis` cho KLTN; thiếu trường này dùng prediction/evidence theo content scope |

```powershell
python scripts/advisor_skill_pipeline.py extract --jobs outputs/advisor_skills/jobs.jsonl --output outputs/advisor_skills/extraction
```

Title chỉ dự đoán thuật ngữ trực tiếp và một số suy luận đơn giản, không đoán framework phổ biến. Nội dung dùng rule theo câu để nhận dạng sử dụng/triển khai/đánh giá; related work, phủ định và tương lai không tự trở thành evidence sử dụng. Rule còn có thể bỏ sót mô tả phức tạp hoặc xuyên nhiều câu; reviewer xử lý những ca đó.

Nếu khai `full_text_complete` nhưng thiếu inventory/trang, output bị hạ thành `partial_full_text`. `expected_units` do bước kiểm kê thực tế cung cấp, không tạo danh sách giả để đạt completeness. KLTN không được chấm từ title-only.

Output `skill_evidence.jsonl` luôn là claim `pending`; việc chạy parser thành công không tự cấp `approved`. Job KLTN còn có `supervision_review_status=pending`. Giữ output gốc; tạo file claim đã review riêng để ghi quyết định và audit của người có thẩm quyền.

## 4. Dữ liệu đầu vào tính điểm

Mỗi dòng profile/thesis claim cần ít nhất:

```text
advisor_id, skill_id, artifact_id, channel, score,
usage_status, review_status, available_at, split, training_eligibility
```

- Profile có channel `prediction` hoặc `evidence`; KLTN có channel `thesis`.
- `usage_status=used` yêu cầu score hữu hạn 0–100. `not_used` hoặc `unknown` yêu cầu `score=null`.
- `review_status` là `pending`, `needs_review`, `approved`, `rejected`. Chỉ claim approved mới được tính; việc duyệt phải xác minh cả liên kết advisor–công trình. Nếu có `identity_review_status` hoặc `supervision_review_status`, chúng cũng phải approved.
- `content_completeness` là `complete` hoặc `partial`. Input partial/chưa review có thể chặn công bố final của skill tương ứng.
- `available_at` bắt buộc có múi giờ. Không bịa historical availability từ ngày xuất bản hoặc ngày crawl.
- `artifact_id` đã gộp mirror, PDF/DOCX và alias trước scoring. Claim trùng cùng kênh/công trình/skill được dedup; mâu thuẫn điểm thì báo lỗi.
- `evidence_id` hoặc `evidence_ids` giữ tham chiếu nguồn. Claim ID không tự chứng minh reviewer đã duyệt.

CLI hiện chỉ tính membership `train`. `scope=point_in_time_verified` chỉ lấy claim đúng scope này và trước cutoff. `scope=retrospective_proxy` giữ riêng phân tích hồi cứu; không tự chuyển claim `retrospective_document_proxy` sang scope khác. Module Python hỗ trợ scope cũ, nhưng CLI không có lựa chọn đó; cần review và mapping rõ trước khi sử dụng dữ liệu cũ.

## 5. Tính snapshot

```powershell
python scripts/advisor_skill_pipeline.py score --profile-claims outputs/advisor_skills/reviewed_profile.jsonl --thesis-claims outputs/advisor_skills/reviewed_theses.jsonl --registry data/2024/advisors/faculty_profiles/advisors_profile.csv --semester 2025.2 --cutoff 2026-05-31T23:59:59+07:00 --scope point_in_time_verified --output outputs/advisor_skills/scores_2025_2
```

Cutoff trong ví dụ là giới hạn cuối kỳ; khi đánh giá quyết định đầu kỳ phải truyền đúng thời điểm quyết định, không dùng cutoff cuối kỳ thay thế. CLI không suy availability hoặc membership từ nhãn semester. `--semester` chỉ nhận `2024`, `2025.1`, `2025.2`; không mở external test 2025.3. Dùng `--exclude-thesis-id` lặp lại để loại công trình đang đánh giá và duplicate group canonical, tránh self-leakage.

Mỗi advisor–skill có:

```text
P = mean(điểm prediction của các công trình có dự đoán skill)
E = mean(điểm evidence của các công trình có sử dụng skill)
profile = 0.4*P + 0.6*E
GVHD = mean(điểm các KLTN có sử dụng skill)
final = 0.5*profile + 0.5*GVHD
```

Không dùng skill thì không đánh giá và không vào mẫu số. Hai KLTN dùng skill đạt 80/100, bài thứ ba không dùng ⇒ GVHD=90. P=70, E=90 ⇒ profile=82 và final=86. Thiếu một thành phần thì null/`insufficient_data`, không tự chia lại trọng số. Trạng thái dùng skill phải theo evidence, không dùng bộ lọc `score>0`: một điểm 0 thật sự đã chấm với `usage_status=used` vẫn là quan sát hợp lệ.

Output: JSONL/CSV điểm, `report.json`, `snapshot_manifest.json` chứa hash đầu vào/đầu ra, taxonomy, spec, code và trọng số cố định. Mỗi output directory phải mới. Không sửa dữ liệu nguồn hoặc checkpoint đang phục vụ.

### 5.1. Đóng snapshot có review gate và baseline

`src/data_pipeline/advisor_skill_snapshot.py` và `scripts/close_advisor_skill_snapshot.py` bổ sung lớp đóng snapshot phía sau crawler/extractor. Lớp này không crawl, không suy `available_at` và không tự duyệt claim. Mọi decision `approved` phải có `evidence_id`, `reviewer`, `reviewed_at` có timezone và `reason`; thiếu một trường sẽ bị từ chối.

Mở đợt crawl riêng theo toàn bộ năm dương lịch 2025 (request ledger/resume/Chrome queue vẫn tách với đợt đến 2024):

```powershell
python scripts/collect_advisor_history_2024.py `
  --calendar-year 2025 --max-requests 100 `
  --output outputs/advisor_history_calendar_2025
```

Lệnh chỉ đưa các record có `event_year=2025` vào `eligible_works.jsonl`; record không có ngày vẫn ở `unresolved_dates.jsonl`. Dùng `--resume` trên đúng output chưa có `report.json` và truyền các `--prior-run` khi cần tránh lặp request. Không tự suy `available_at`, xác minh tác giả hay approval.

Phân tách candidate có ngày sự kiện rõ theo năm dương lịch, đồng thời giữ `academic_term` thực tế; chỉ thêm một file corpus gắn hash vào data khi truyền `--data-root`:

```powershell
python scripts/close_advisor_skill_snapshot.py partition `
  --candidates outputs/<run>/dated_advisor_candidates.jsonl `
  --data-root data `
  --output outputs/<run>/calendar_partition
```

Theo quy tắc mới cho **giảng viên**, mọi candidate có năm sự kiện 2025 được đưa vào `data/2025.1/advisors/faculty_corpus/`, kể cả khi `academic_term` thực tế của tháng 01–08 là `2024.2`/`2024.3`. Quy tắc này không đổi cohort/split sinh viên. `available_at` được giữ nguyên, không suy từ `event_date` hay thời điểm crawl. Nguồn sau 31/08/2026 bị từ chối, không tự tạo kỳ mới.

Tạo review pack trước khi có quyết định người rà soát:

```powershell
python scripts/close_advisor_skill_snapshot.py review-pack `
  --claims outputs/<run>/profile_claims.jsonl outputs/<run>/thesis_claims.jsonl `
  --output outputs/<run>/review_pack
```

Sau khi reviewer cung cấp `decisions.jsonl`, chỉ đóng snapshot cùng matching contract đầy đủ (requirements đã duyệt trước decision, students/thesis mapping, quota, eligibility và presence do operator cung cấp):

```powershell
python scripts/close_advisor_skill_snapshot.py close `
  --profile-claims outputs/<run>/profile_claims.jsonl `
  --thesis-claims outputs/<run>/thesis_claims.jsonl `
  --decisions outputs/<run>/decisions.jsonl `
  --registry data/2024/advisors/faculty_profiles/advisors_profile.csv `
  --semester 2025.1 --cutoff 2025-12-01T00:00:00+07:00 `
  --scope point_in_time_verified `
  --requirements outputs/<run>/student_skill_requirements.jsonl `
  --students outputs/<run>/students_with_thesis_ids.jsonl `
  --capacities outputs/<run>/capacities.json `
  --eligible outputs/<run>/eligibility.json `
  --present outputs/<run>/present.json `
  --output outputs/<run>/closed_2025_1
```

Lệnh tạo split deterministic theo `thesis_id`; mọi `student_id` dùng chung một KLTN bị buộc vào cùng train/validation/test. `2025.3` không được chấp nhận làm training snapshot. Nếu claims chưa đủ approval/evidence hoặc thiếu matching contract, output vẫn đóng immutable với `status=not_evaluable`, `baseline.status=not_run` và `blocking_reasons`; không chạy RL hay Hungarian giả. Khi đủ contract, Hungarian chạy trước và output vẫn có `production_promoted=false`.

## 6. Kiểm thử và phần tiếp theo

```powershell
python -m pytest -q tests/test_advisor_skill_collection.py tests/test_advisor_skill_extraction.py tests/test_advisor_skill_scores.py tests/test_advisor_skill_matching.py tests/test_advisor_skill_snapshot.py
```

Các bước còn lại: traversal liên kết công bố/PDF và toàn repo theo ngân sách, kiểm kê/OCR tự động và Chrome orchestration đầy đủ; gold/reviewer cho danh tính, supervision và application claims; tạo snapshot từng kỳ có availability proof; tích hợp contract feature mới vào adapter RL và chạy baseline/forgetting gates. Chưa được gắn điểm mới vào checkpoint cũ hoặc tuyên bố pipeline này đã train RL hai cấp.
