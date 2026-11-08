# Tiến độ thu thập nguồn giảng viên ngày 03/11/2026

Phạm vi báo cáo: seed, paper PDF và Chrome fallback. Các số dưới đây là snapshot đã kiểm tra; không đại diện toàn bộ Internet hoặc toàn bộ công bố của giảng viên. Không sửa PRD hoặc nguồn trong `data/`.

## Kết quả đã có

- Seed: 17 giảng viên, 42 URL đã thử trực tiếp; 17 profile official được parse, 25 nguồn chuyển Chrome. Run: `outputs/advisor_skill_20261102/full_collection`.
- Index Chrome: 210 nhóm advisor–title công bố từ liên kết quan sát được; 210 title jobs tạo 27 skill claim bảo thủ, pending. Run: `outputs/advisor_skill_20261102/chrome_index` và `full_title_extraction`.
- Browser detail: 225 capture. Kiểm tra chất lượng phân biệt 80 trang blocked, 141 cần review và 4 quá ngắn. Capture không tự chứng minh article–advisor link hoặc full text. Nguồn: `outputs/advisor_skill_20261103/capture_quality`.
- PDF trực tiếp: 55 URL PDF quan sát được đã thử; lấy và trích toàn bộ 16 PDF độc lập, 207 trang; 39 nguồn cần Chrome. Run: `outputs/advisor_skill_20261103/paper_collection`.
- Recovery từ redirect Chrome thực tế: thêm 1 PDF độc lập, 11 trang. Run: `outputs/advisor_skill_20261103/paper_chrome_recovered`. Tổng hai run: **17 PDF khác hash, 218 trang**.

Toàn văn trên nghĩa là đã xử lý tất cả trang của tài liệu tải xuống. Một PDF có thể là proceedings hoặc khác bài dự định; `downloaded_document_matches_article` và liên kết người–bài vẫn pending. Chưa có điểm giảng viên được duyệt, chưa có historical availability hợp lệ và chưa train/promote RL mới từ nguồn này.

## Trạng thái Chrome đúng theo bằng chứng

Snapshot mới nằm trong `outputs/advisor_skill_20261103/paper_chrome_truth_v2`; không ghi đè báo cáo recovery cũ.

| Kết quả của 39 nguồn PDF chờ | Số lượng | Diễn giải |
|---|---:|---|
| Orchestration `ReferenceError: bt is not defined` | 10 | Lỗi code trước thao tác nguồn, không tính đã thử duyệt nguồn |
| `Debugger unattached` | 8 | Transport không sẵn sàng, không tính đã thử duyệt nguồn |
| Lỗi điều hướng/timeout | 10 | Đã yêu cầu điều hướng; chưa xác nhận đã đọc nguồn |
| Trang lỗi | 1 | Có trang lỗi, không phải nội dung paper |
| Capture rỗng | 4 | Không có text; không tự khẳng định có/không có PDF |
| Text cần review | 5 | Có text; chưa xác nhận toàn văn hoặc danh tính |
| Trang yêu cầu xác minh truy cập | 1 | Challenge, chưa đọc được nội dung |

Có 39 file trạng thái nhưng chỉ **21 yêu cầu điều hướng nguồn có bằng chứng**, gồm cả các timeout. Không được báo “39 nguồn đã crawl bằng Chrome”. Ba trang Academia được mở có thể chỉ là trang giới thiệu/đăng nhập; text không tự chứng minh đã tải PDF. Một redirect public đã được recovery thành PDF là kết quả riêng, không xóa lịch sử timeout của request gốc.

## Lệnh và artifact chính

Chạy từ `C:\Su\KLTNv2\KLTN`, Python 3.12.9 hiện có. Chọn output directory mới cho mọi lần chạy.

```powershell
python scripts/collect_advisor_papers.py --captures outputs/advisor_skill_20261102/chrome_full/details --publication-index outputs/advisor_skill_20261102/chrome_index/publications.jsonl --capture-quality outputs/advisor_skill_20261103/capture_quality/capture_quality.jsonl --max-downloads 60 --output outputs/advisor_skill_20261103/paper_collection_NEXT

python scripts/audit_paper_chrome_status.py --queue outputs/advisor_skill_20261103/paper_collection/chrome_queue.jsonl --chrome-dir outputs/advisor_skill_20261103/paper_chrome --output outputs/advisor_skill_20261103/paper_chrome_truth_NEXT
```

Không chạy lại tải toàn bộ chỉ để cập nhật metadata. Downloader kiểm tra IP công khai cho mọi redirect, pin IP khi kết nối, kiểm tra TLS hostname, giới hạn 25 MiB và timeout socket 15 giây. Không vượt CAPTCHA/paywall. `raw/`, `extracted/`, receipt từng request và manifest hash phục vụ kiểm tra lại bytes, trang và parser.

Run PDF đầu đã hoàn tất trước khi bổ sung `http_status` riêng: status kết quả đã thay numeric status gốc trong receipt đầu. Giữ nguyên run đó và ghi nhận hạn chế; bản code mới lưu hai trường riêng. Bản mới cũng join công bố theo URL nguồn gốc, lưu hash implementation và loại capture blocked nếu truyền quality ledger có hash khớp.

Signed CDN URL được giữ ở metadata browser gốc trong storage local; recovery receipt chỉ lưu host và hash URL, không echo token ra log.

## Kiểm tra và bước tiếp theo

```powershell
python -m pytest -q tests/test_paper_chrome_status.py tests/test_advisor_paper_recovery.py tests/test_advisor_paper_fulltext.py tests/test_advisor_skill_collection.py
```

Kết quả tại thời điểm báo cáo: **14 passed**. Đây là nhóm test collection/fulltext/recovery/status, không phải toàn bộ test repository.

Cần sửa orchestration/transport trước khi đánh giá lại 18 nguồn chưa thực sự được điều hướng; không gắn chúng là site blocked. Các trang còn thiếu chỉ retry có mục tiêu theo nguồn, không thử ngẫu nhiên. Tiếp tục review title/authors/affiliation, đối chiếu PDF với bài và advisor, xác minh GVHD và thời điểm. Sau đó mới tính điểm 40/60 và 50/50 theo từng skill rồi tích hợp feature contract mới vào RL qua baseline/forgetting gates. Giữ `2025.3` ngoài training/tuning.
