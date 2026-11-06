# Bàn giao triển khai advisor skill

Cập nhật: 02/11/2026, Asia/Saigon. Spec sở hữu: `docs/advisor_skill_semester_prd_spec.md` v1.3. Runbook: `docs/advisor_skill_implementation_guide.md`.

## Yêu cầu đã chốt

- Từng skill/framework có P dự đoán và E bằng chứng, cùng thang 0–100.
- Profile=0,4P+0,6E. GVHD=trung bình các KLTN có sử dụng skill, không tính bài không sử dụng vào mẫu số. Final=0,5profile+0,5GVHD.
- Ví dụ P70/E90 và KLTN80/100/không dùng: profile82, GVHD90, final86.
- Crawl trực tiếp không đủ thì điều khiển Chrome; chỉ title thì dự đoán tối giản; có toàn văn phải xử lý đủ và lưu coverage.
- Giữ cutoff, provenance, training split và test ngoài2025.3; không đưa nguồn hiện tại ngược vào lịch sử nếu chưa có availability proof.
- Người dùng yêu cầu dùng agent và kiểm tra quota5giờ trong quá trình làm. Khi còn dưới5%, cập nhật tài liệu bàn giao này trước khi hết quota. Lần kiểm tra gần nhất: used76%, còn24%; chưa chạm ngưỡng. Công cụ: `mcp__codex_app__get_usage_limits({})`, đọc `primary.usedPercent` khi `windowDurationMins=300`; không nhầm quota tuần.

## Đã làm

Ba agent xây scorer, extraction và collection; review chéo đã sửa false positive phủ định/tương lai/baseline/survey. Parent tích hợp CLI và kiểm tra calendar/source boundaries.

File mới:

- `src/features/advisor_skill_scores.py`: reviewed-claim aggregation, unknown/null, canonical dedup, fixed weights, time/split/scope filter, self-thesis exclusion.
- `src/data_pipeline/advisor_skill_extraction.py`: taxonomy rules, exact locators, title prediction, fulltext inventory, conservative application classification. Claim luôn pending; không tự cấp approval.
- `src/data_pipeline/advisor_skill_collection.py`: exact seed collector có ngân sách, raw/status, Chrome queue và API nhập capture UI thật.
- `scripts/advisor_skill_pipeline.py`: collect/extract/score, immutable output, registry/taxonomy validation, semester cutoff guard, external-source guard, code/data/spec/taxonomy hash manifests.
- Bốn test mới `tests/test_advisor_skill_{scores,extraction,collection,pipeline}.py`.
- `docs/advisor_skill_implementation_guide.md`.

Không sửa source frontend/backend/RL cũ hoặc checkpoint. Repo đã có nhiều thay đổi/xóa trước phiên này; không restore/clean chúng. Không thêm dependency. `docs/`, `tests/`, `outputs/`, `data/` hiện bị Git ignore; file mới vẫn local. Chưa stage/commit/push.

## Kiểm chứng

```powershell
python -m pytest -q tests/test_advisor_skill_scores.py tests/test_advisor_skill_extraction.py tests/test_advisor_skill_collection.py tests/test_advisor_skill_pipeline.py tests/rebuild/test_lecturer_crawl.py tests/rebuild/test_fresh_faculty.py
```

Kết quả: **56 passed, 16 subtests passed**,9,57giây. Compileall4file implementation đạt. Check whitespace không phát hiện lỗi; Git cảnh báo chuyển LF/CRLF. Runtime có RequestsDependencyWarning về urllib3/chardet/charset_normalizer; chưa đổi environment chung.

## Pilot thật

Đầu ra `outputs/advisor_skill_20261102/`:

- `pilot_collection/`: registry17advisor,42seedURL; thử4URL của advisor đầu tiên;1official thành công,3needs_chrome,38budget_exceeded.
- Ba Chrome tab thật đã mở Scholar, ResearchGate và GitHub của advisor đầu tiên; Scholar load-more hiển thị39mục, ResearchGate hiển thị6công bố. Đây là số mục hiển thị, không phải39/6fulltext đã đọc.
- `pilot_collection/chrome_captures/`:3capture gồm các đoạn nhìn thấy được chọn lọc, status partial, hash/receipt. Không phải bản export toàn trang; vẫn chưa có historical availability và chưa duyệt identity.
- `pilot_collection/chrome_pilot_summary.json`: thống kê bổ sung. Collection report/queue gốc immutable phản ánh trạng thái trước UI; đọc receipt riêng để biết đã xử lý Chrome, không gọi queue cũ là trạng thái hiện tại.
- `pilot_jobs.jsonl`:5title thực nhìn thấy trên Scholar, chọn cho pilot.
- `pilot_extraction/`:2claim AI từ title, pending/unresolved, không có available_at/split. Không có điểm final thật; không bịa dữ liệu để tạo score.

## Công việc tiếp theo, theo thứ tự

1. Tăng pilot ra toàn bộ42seed, giữ cache/resume và bổ sung status tổng hợp HTTP+Chrome. Collector hiện chỉ thử mỗi URL một lần; chưa có retry/backoff/resume/pagination tự động hoàn chỉnh. Chrome đang được agent orchestration thực hiện bằng UI, Python không tự điều khiển browser.
2. Thu fulltext/paper và repo theo các liên kết có thật; DOI/work-group dedup; metadata ngày/identity có proof. GitHub API traversal và pin immutable ref chưa có trong module mới.
3. Kết nối PDF/OCR reader có sẵn (`src/data_pipeline/pdf_extract.py`) để tạo text-unit inventory tự động. Hiện CLI extract nhận text-unit jobs đã cung cấp, chưa tự đọc PDF.
4. Import thesis evidence có sẵn, xác minh advisor–KLTN, tạo supervision ledger. Không tự duyệt người thật; reviewer cần ghi nguồn và thời điểm. Giữ mẫuCSV40cột.
5. Tạo gold pilot và đo precision/recall/coverage. Rule hiện sentence-local, có thể bỏ sót nội dung phức tạp; chưa có bằng chứng đạt ngưỡng chất lượng PRD.
6. Review claim, xác nhận available_at/split/scope; chạy score riêng từng kỳ vào output mới. Thiếu thành phần giữ null, không renormalize. Chuẩn bị expected-thesis inventory để biết ca còn thiếu thay vì chỉ dựa trên claim đã có.
7. Tạo adapter matching từ final_score + mask và contract hash mới; không ghép feature mới với checkpoint cũ. Sau baseline cùng constraints, mới tích hợp feedback/continual RL, forgetting/retention. Chưa train mới, chưa phục vụ model mới.

Mỗi lần tiếp tục đọc spec/runbook và kiểm tra Git hiện trạng; không rerun output immutable đang có. Khi quota còn<5%, cập nhật đúng trạng thái công việc đang dở, lệnh/run/session đang chạy và kết quả test mới nhất vào file này.


## Bàn giao sau lượt crawl mở rộng ngày 02/11/2026

**Quota Codex 5 giờ đã dùng96%, còn4%: dừng mở lượt mới theo yêu cầu người dùng.**

Đã hoàn tất thử42/42seed,17official profile thành công,25Chrome tasks. Run `outputs/advisor_skill_20261102/full_collection/`; discovery có271citation strings và1817link candidates (có nav, không phải1817bài).

Chrome thực tế đã lưu body text+observed links vào `chrome_full/`:13Scholar và8ResearchGate. Có225detail task URL từ nguồn thực; đã mở và lưu đủ225trang tại `chrome_full/details/`. Báo cáo hash và blocked/short tại `chrome_details_report.json`. Nhiều trang RG bị chặn hoặc ngắn; chưa có fulltext coverage hoàn chỉnh. Các file `_expanded.json` đã được sửa pagination_complete=false vì nút disabled lúc tải không chứng minh hết danh mục. Phải kiểm tra lại phân trang, không được báo tất cả bài đã thu.

`chrome_index/`:210title dedup advisor+normalized title,21/25queued sources có capture (4còn lại GitHub). `full_title_extraction/`:210jobs sinh27claim, pending/unresolved, không dùng historical training. Index lập trước khi đọc225detail nên cần index lại các detail link mới và xử lý DOI/PDF.

GitHub:4/4account enumeration complete,122repo. Run `github_collection/` lấy54repo tree+README,68repo chưa đủ budget. `github_collection_continued/` dùng --resume-from và kiểm tra upstream hash, tái sử dụng54không gọi lại; dừng khi API trả X-RateLimit-Remaining=0.68repo vẫn thiếu do API quota; cần đợi reset hoặc Chrome fallback. Chưa đọc source code first-party đầy đủ, không chấm Implemented từ README một mình.

Code mới lượt này: `scripts/discover_advisor_sources.py`, `scripts/prepare_chrome_publications.py`, `scripts/collect_advisor_repositories.py` và3test tương ứng. Repo vẫn dirty trước đó, không restore/clean hoặc commit data.

**Tiếp tục ưu tiên:** đọc báo cáo blocked/short; kiểm tra phân trang Scholar đúng lúc trang đã ổn định; từ225detail lấy DOI/publisher/PDF URL thật rồi tải bản được phép, dùng reader PDF/OCR hiện có để kiểm kê toàn bộ trang. Mở Chrome khi HTTP không đủ; không vượt CAPTCHA/paywall. Sau GitHub reset tiếp tục từ manifest immutable, không crawl lại54repo. Tiếp đó tạo evidence jobs từ fulltext, xác minh identity/date/supervision và chạy scorer riêng học kỳ. Chưa có gold quality gate, chưa train RL, chưa promote model.


## Tiếp tục ngày 03/11/2026 — ngưỡng mới

Người dùng đổi ngưỡng bàn giao thành **quota5giờ còn dưới3%**, thay ngưỡng5% cũ. Đã kiểm tra đầu phiên used0%, lần gần nhất used82%, còn18%; không được báo đã chạm ngưỡng khi chưa kiểm tra lại. Các quyết định lịch sử ở trên giữ để audit.

Kết quả mới: `outputs/advisor_skill_20261103/`. `github_collection`+`git_remaining/manifest.json` có đủ trạng thái122repo:117nonempty inventories,5empty. RootREADME không tồn tại ở4repo; không tự tạo. Fork chưa có đóng góp riêng được loại khỏi evidence độc lập. `source_reading/Lampx83_Annota` và `Lampx83_BiblioMap` đọc49unit346344bytes, candidate_text_complete theo phạm vi đã khai báo, không audit toàn repo.

`paper_collection`:55PDFcandidate từ225capture,16PDFunique207trang. `paper_chrome_recovered`:1PDFmới11trang. Tổng17PDF218trang. `capture_quality`:80/225trang gốc là blocked,141captured_needs_review,4short;35generic title. Hai attribution flags15/94 chưa duyệt. Không xem mọi bài trongScholar library là của advisor.

`paper_document_jobs_v2` giữ16document identity SHA riêng title candidate; `paper_skill_extraction` đã xử lý207trang/628855text chars,53claim từ14/16document:6usage candidates47unknown. Tất cả claim/identity pending; available_at/split null; không có điểm final hoặc training approval. CLI đã giữ provenance identity và scorer chặn pending article-person/document-match.

Chrome phân trang đã lưu mới `chrome_profiles`:Phạm Xuân Lâm20→39,Nguyễn Trung Tuấn20→100→117,Phạm Minh Hoàn20→26. Các snapshot khác vẫn pending pagination, không gán hết thư viện. `paper_chrome_truth_v2` phân biệt39status files nhưng chỉ21navigation có bằng chứng;10ReferenceError+8debugger transport không coi là site blocked. Chi tiết trong `docs/advisor_skill_progress_20261103.md`.

Batch source đầu `source_reading_batch/manifest.json` interrupted_source_reading AI-Portal,83units đã lưu; không dùng làm dữ liệu đầy đủ. Agent đang sửa hiệu năng lazy Git blob và các review issues:đúng identity_review_status,merge duplicate text/AST claims,preserve partial completeness,alias shadowing. Cần đọc progress/manifest lượt v2 và test cuối phiên trước tiếp tục, không chạy lại output cũ.

Kiểm thử gần nhất parent:55passed16subtests trên11file test mới; collection/recovery/status14passed riêng, không cộng thành tổng unique. Môi trường RequestsDependencyWarning chưa đổi dependency chung.


### Checkpoint source v2 đang xử lý

`source_reading_batch_v2/Lampx83_AI-Portal/manifest.json`:494whole candidate text units,4544859bytes,0missing; source đã lưu nhưng bước skillclaim chưa hoàn tất tại checkpoint này. Reader bulkfetchblob:limit=524288,deadline120giây,per-file progress. Batch đang được tối ưu normalization một lần/unit; không tải lại source đã có. Alias rebinding/params không còn tự nhận used80; identity_review_status=pending; merge maxskillscore và refs; completeness giữ partial; blank-unit ledger tách riêng.

Stop marker: `outputs/advisor_skill_20261103/STOP_SOURCE_BATCH`. Dùng trước khi kết thúc phiên nếu batch còn chạy; sau marker chờ repo bounded hoàn tất và kiểm tra manifest/progress, không để tiến trình không quản lý. Có --resume-from để dùng output stopped tương thích pins/hashes; đọc --help trước run. Batch session gần nhất13209, có thể được agent dừng/restart khi tối ưu; cần xác minh session đang chạy qua bàn giao cuối, không đoán.

Test cuối parent sau sửa scorer/provenance và source:38passed9subtests trên7file test (không phải toàn repository). Lượt trước55passed16subtests trên11file. Các count này overlap, không cộng lại.


### Bàn giao cuối phiên03/11 — đã kiểm thử

Quota kiểm tra gần nhất97%used,3%remaining; đã tạoSTOP_SOURCE_BATCH để chốt an toàn trước ngưỡng dưới3%. Lượt v3 source có progress thực: [{"repository": "Lampx83/AI-Portal", "status": "read_pending_review", "claims": 29, "processed_units": 494, "missing_units": 0}, {"repository": "Lampx83/Annota", "status": "read_pending_review", "claims": 9, "processed_units": 27, "missing_units": 0}, {"repository": "Lampx83/BiblioMap", "status": "read_pending_review", "claims": 7, "processed_units": 22, "missing_units": 0}, {"repository": "Lampx83/Datium", "status": "read_pending_review", "claims": 4, "processed_units": 15, "missing_units": 0}].

Lượt v1 interrupted giữ83unit. V2 sourceAI-Portal494unit/4544859bytes đã hoàn tất; v3 reuse nguồn đó và2pilot, không tải lại. Normalization tối ưu một lần/unit đã vượt regression. Alias rebind,claimdedup,identity_review_status và partialcompleteness đã sửa. Test cuối24passed11subtests cho extraction/pipeline/reader/batch.

Để tiếp tục: kiểm tra v3manifest có đủ122trạng thái và không còn process; dùng --resume-from v3,outputmới,stop-filemới chưa tồn tại (không dùng marker cũ). Source105first-party nonempty,12forkexcluded,5empty. Chỉ read_pending_review được tái sử dụng sau hashcheck; còn lại chưa đọcsource đầy đủ. Đọc running.json/progress.json để biết repo đang dở nếu manifestchưađủ. Không suy toàn bộ105đãđọc.

Chưa training/promotion. Chưa tựduyệt identity,articlematch,GVHD,available_at. Tiếp theo hoàn tất source; ChromePDF18nguồn lỗi điều phối cần sửa,21navigation có bằng chứng; xác minh phầnarticlePDF/tác giả thực trướcchấmđiểm. Công thứcP/E40/60 vàprofile/GVHD50/50, chỉ tính bài dùngskill giữ nguyên.

Quota cuối đã kiểm tra99%used, còn1% (<3%): đã kích hoạt bàn giao. V3Handio đang dở, yêu cầu agent dừng tiến trình và chốt manifest; nếu chưa có manifest phải đọc progress4repo49claims, không chạy lại nguồn494unit. Session73577/PID9684 là tiến trình cần xác minh đãdừng trướcresume. Backupđồngbộ tại docs/handoffs/advisor_skill_handoff_20261103_115400.md.


## Tiếp tục05/11/2026
Bàn giao mới nhất tại docs/advisor_skill_progress_20261105.md. Đọc file mới vàmanifest authoritative thay vì chỉ dùng snapshot03/11. Ngưỡngquota còn dưới3% giữ nguyên.
