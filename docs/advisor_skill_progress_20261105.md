# Bàn giao advisor skill ngày05/11/2026

Ngưỡng hiện hành: dừng và lưu bản sao khi quota5giờ còn dưới3%. Công cụ get_usage_limits không trả lời/không khả dụng trong phiên; đọc event token_count.rate_limits của rollout hiện hành làm fallback. Chỉ xem event mới có timestamp gần thời gian hiện tại; không suy quota từ log cũ. Path rollout root: C:/Users/Lenovo/.codex/sessions/2026/11/02/rollout-2026-11-02T16-56-40-01a19bb0-8817-75b2-b420-06657653151b.jsonl. Không dump nội dung transcript hoặc dữ liệu cá nhân; chỉ đọc primary.used_percent/window_minutes/resets_at. Lần gần nhất91%used9%remaining; kiểm tra cuối trước khi kết thúc.

## Kết quả kỹ thuật

Đã thêm src/features/advisor_skill_matching.py +tests/test_advisor_skill_matching.py (5tests đạt). Adapter đưa final_score vào AllocationProblem native/Hungarian, không renormalize khi thiếu skill. Requirement canonical dùng requirement_weight, evidence_scope=predecision_requirement,review_status approved,timestamp trước cutoff; không lấy KLTN hoàn thành làm yêu cầu đầu kỳ. Quota/eligible/present bắt buộc từ operator. Thiếu mandatory skill có mask bảo thủ và needs_review diagnostics. Contract hash gồm thứ tựadvisor,thứ tựskill,scorer schema,taxonomy hash,weights vàcoverage floor; chưa tự ghép checkpoint cũ. Chưa nối serving hoặc train mới khi dữ liệu chưa duyệt.

Source batch: hard60s child extraction perrepo, nguồn Git120s deadline,cache hash/pins/progress. Repo heavy timeout giữ nguồn đủ vàclaims_complete=false, chuyển repo khác. source_reading_batch (Nov5 đầu) đã dừng,authoritative hiện source_reading_batch_bounded. Không dùng run Nov3 làm trạng thái mới nhất.

## Trạng thái source tại checkpoint

[
  {
    "repository": "Lampx83/AI-Portal",
    "status": "read_pending_review",
    "claims": 29,
    "processed_units": 494
  },
  {
    "repository": "Lampx83/Annota",
    "status": "read_pending_review",
    "claims": 9,
    "processed_units": 27
  },
  {
    "repository": "Lampx83/BiblioMap",
    "status": "read_pending_review",
    "claims": 7,
    "processed_units": 22
  },
  {
    "repository": "Lampx83/Datium",
    "status": "read_pending_review",
    "claims": 4,
    "processed_units": 15
  },
  {
    "repository": "Lampx83/Handio",
    "status": "extraction_timeout",
    "claims": null,
    "processed_units": 471
  },
  {
    "repository": "Lampx83/hello-app",
    "status": "read_pending_review",
    "claims": 2,
    "processed_units": 4
  },
  {
    "repository": "Lampx83/LakeFlow",
    "status": "read_pending_review",
    "claims": 15,
    "processed_units": 156
  },
  {
    "repository": "Lampx83/Lampx83",
    "status": "read_pending_review",
    "claims": 7,
    "processed_units": 1
  },
  {
    "repository": "Lampx83/library-regulations",
    "status": "read_pending_review",
    "claims": 8,
    "processed_units": 15
  },
  {
    "repository": "Lampx83/LibrarySearch",
    "status": "read_pending_review",
    "claims": 7,
    "processed_units": 17
  }
]

105firstparty nonempty đủđiềukiện,12forkexcluded,5empty. Chưa có toàn bộ105source đã đọc. Handio source471unit giữ đủ nhưng extraction timeout; v3 cũ có4repo49claims vẫn tái sửdụng. MarkerSTOP: outputs/advisor_skill_20261105/STOP_SOURCE_BATCH; batch hoàn tấtmanifest khi dừng. Dùng --resume-from authoritative bounded manifest vớioutputmới vàstopfilemới.

## GVHD và KLTN

Script mới scripts/prepare_advisor_supervision.py; 4focused tests đạt, bao gồm thesis nhiều sinhviên chỉ1job,sourceCSV không đổi,2025.3không mở để train,STOP checkpoint. Hiện supervision_preparation_v4 authoritative; v1/v2/v3 bị dừng nhưng raw/cache giữ nguyên vàv4reuses theoSHA +pageinventory.

{
  "current_pool": "2025.1",
  "links": 116,
  "jobs": 116,
  "unresolved": 37,
  "unique_theses_read": 148,
  "source_coverage_counts": {
    "existing_page_text_cache": 91,
    "pymupdf_all_pages_embedded_text": 57,
    "source_unresolved": 5
  },
  "stop_requested": false
}

Source CSV:136bootstrap+68kỳ2025.1+64kỳ2025.2;20external2025.3 loại khỏitrain. Trích advisor từspan có nhãnhướngdẫn trênbìa vàkhớproster,không lấy tên bấtkỳ trongnội dung. Tất cả link/job pending; available_at/split chưa tự tạo. NativePyMuPDF đọc embedded text toànbộtrang; OCRoff giữ scan/lowtext làpartial,không fakefulltext. Chưa chấmđiểmGVHD người thật. STOPprep:outputs/advisor_skill_20261105/STOP.

## Paper và Chrome

17PDFunique/218trang vẫn là sốfulltext thực. Paper_attribution_v2:15candidate cótitle/authors hỗtrợ đểreview,1wrong-author Indonesiantourism,1NguyễnThanhHương affiliationHUST cần phânbiệt. Không loại bàiTốngThịHảoTâm chỉvì chủđềvật lý; PDFthực cótên/NEUIT affiliation.

HTTP publisher_resolution vàpublisher_resolution_lam:35landing cónguồnthực đãthử,1PDFtrùng,0PDFunique mới. Không xem referencepdf làbàiadvisor. 18sourcechưa được điềuhướng trướcđó nằm paper_attribution/priority_browser_sources.jsonl. Chrome không khảdụng trongphiênNov5; createBrowserTab báo Browser is not available:chrome, inventorybịabort. Không gọi18nguồn làđãthu/blocked từsite. Cầnkhôiphụckếtnối Chrome rồimớithửlại.

## Tiếp tục

1. Kiểmtra finalmanifest/progress2batch + khôngcònworker,quota mới.
2. Tiếp tụcsource từboundedcheckpoint, ưu tiênclaimtimeoutchunkretry dùng cache,không tảiGitlại.
3. Tiếp tụcKLTN từv4cache vàmởcácsourcechưađọc; giữexternal2025.3ngoàitrain. Chạytríchskilljob chuẩn sau khiđủnguồn,bibliographyexclude vàOCRneeds riêng.
4. Tạoreviewpack thật choidentity/link/GVHD/time; không tựapprove vìparser thànhcông.
5. Saukhiđượcreview,côngthức từngskill:profile=.4P+.6E,GVHD=mean(chỉKLTNcódùngskill),final=.5profile+.5GVHD;unknownnull,khôngchia trọngsốlại.
6. Baseline/Hungarian cùngconstraints trước RL2cấp;chỉtrain từdatacontract đủđiềukiện,không promote hayghép featuremới vào modelcũ.

Không sửa/xóa cácdirtychanges cótrướctrongrepo.Khôngcommitdata,checkpoint hoặcsecret. docs/tests/outputs/data hiện bịGitignore;chưastage/commit/push.


## Cập nhật heartbeat lúc 04:48 ngày 05/11/2026

Quota 5 giờ đã reset; log phiên lúc 21:48 UTC ghi used0%. Hai batch trước đã tự hoàn tất, không còn worker của chúng cần dừng.

Source manifest đầy đủ 122 repo: {"empty_repository": 5, "excluded_fork": 12, "extraction_timeout": 6, "read_pending_review": 99}. Như vậy 99 repo đã trích claim, 6 repo còn timeout trích xuất nhưng giữ cache; 12 fork và 5 repo rỗng không được tính là đã đánh giá source. Tiếp tục 6 timeout bằng chia nhỏ unit và merge theo artifact/skill, không tải lại Git.

GVHD preparation đã hoàn tất lượt chuẩn bị: {"candidate_links": 208, "thesis_jobs": 208, "unique_theses_read": 250, "jobs_per_pool": {"2024": 101, "2025.1": 58, "2025.2": 49}, "unresolved": 60, "source_coverage_counts": {"existing_page_text_cache": 149, "pymupdf_all_pages_embedded_text": 101, "source_unresolved": 18}, "stop_requested": false, "excluded_external_students": 20, "identity_approvals_granted": 0, "historical_training_ready": false, "scores_published": 0}. 208 job là ứng viên chờ duyệt, không phải 208 liên kết đã xác nhận. 60 unresolved cần kiểm tra lý do trong unresolved.jsonl.

Đã chạy thật bộ trích skill cho 5 KLTN có lượng text nhỏ nhất (đọc toàn bộ text unit của từng job, tổng 244729 ký tự) tại outputs/advisor_skill_20261105/thesis_skill_pilot_0001. Tạo 41 claim; kiểm tra hash output đạt; tất cả claim và liên kết GVHD vẫn pending, available_at null, chưa xuất điểm giảng viên. Selection/input hash nằm ở thesis_skill_pilot_0001_input/selection.json. Không được gọi 5 bài này là mẫu đại diện chất lượng toàn cohort.

Bước tiếp theo: trích 203 job KLTN còn lại theo batch nhỏ có resume, bỏ qua 5 artifact đã có; giữ nguyên approval/time gate. Hoàn thiện 6 repo timeout từ cache; sau đó review identity/GVHD/document match, nguồn thiếu ngày/OCR rồi mới tính điểm và đánh giá RL. Chrome tiếp tục là dependency chưa khả dụng trong lượt trước, không tự đánh dấu nguồn đã crawl.
