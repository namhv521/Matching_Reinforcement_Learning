# Tóm tắt công việc: hồ sơ skill giảng viên và RL theo kỳ

Ngày: 05/11/2026

## 1. Đã hoàn thành

### Code

| File | Nội dung |
|---|---|
| `src/data_pipeline/advisor_skill_snapshot.py` (mới) | Chia dữ liệu giảng viên theo năm sự kiện: đến 2024 vào pool `2024`, toàn bộ năm 2025 vào `2025.1`, vẫn giữ `academic_term` thật. Đánh dấu bản trùng theo DOI hoặc tiêu đề chuẩn hóa, không gộp hay xóa dòng. Kiểm tra quyết định duyệt: bắt buộc có người duyệt, thời điểm có múi giờ và lý do; không cho ghi đè `available_at`, split hay `training_eligibility`. Chia train/validation/test 70/15/15 theo khóa luận, chặn `2025.3`. Đóng snapshot: đủ điều kiện thì chạy Hungarian, Greedy, Random; thiếu thì trả `not_evaluable` kèm lý do. |
| `scripts/close_advisor_skill_snapshot.py` (mới) | CLI `partition`, `review-pack`, `close`, có manifest hash. `partition --data-root data` ghi thêm file gắn hash, không ghi đè. |
| `scripts/collect_advisor_history_2024.py` | Thêm `--calendar-year` để crawl riêng năm 2025. |
| `scripts/advisor_skill_pipeline.py` | Claim khóa luận giữ `student_ids`, `thesis_id`, `supervision_id` để chia split theo khóa luận. |

### Tài liệu

- `docs/advisor_skill_prd_spec_current.md`: PRD/SPEC hợp nhất, đối chiếu với spec cũ v1.3. Ghi rõ phần đã làm, phần còn thiếu và các gate trước khi train.
- `docs/advisor_skill_implementation_guide.md`, mục 5.1: lệnh crawl 2025, partition, review-pack, close.

### Kiểm thử

```text
32 passed, 5 subtests passed
```

Gồm `tests/test_advisor_history_2024.py`, `test_advisor_skill_scores.py`, `test_advisor_skill_matching.py`, `test_advisor_skill_snapshot.py`, `test_close_advisor_skill_snapshot_cli.py`.

## 2. Hiện trạng dữ liệu (đã kiểm tra, chưa thay đổi)

Giảng viên, gói lịch sử `outputs/advisor_history_through_2024/dataset`:

- 459 dòng ứng viên: 396 công trình/giải thưởng và 63 dòng metadata phần mềm, năm sự kiện từ 1995 đến 2024.
- 60 snapshot Git theo commit, năm 2018–2024.
- 184 dòng không xác định được năm và 27 dòng sau 2024 nằm ngoài gói này.

Sinh viên, theo ngày trên bìa khóa luận:

| Pool | Tổng | Năm trên bìa | Không có năm |
|---|---|---|---|
| 2024 | 136 | 2024: 34, 2025: 97 | 5 |
| 2025.1 | 68 | 2025: 64 | 4 |
| 2025.2 | 64 | 2026: 60 | 4 |
| 2025.3 | 20 | 2026: 20 | 0 |

Claim skill giảng viên trong `outputs/`: tất cả đang `pending`. Phần lớn là dự đoán từ nhan đề hoặc nội dung repo chưa đầy đủ; `available_at` chưa có.

RL hiện tại (`scripts/run_semester_rl.py`): ba version V1 (`2024`), V2 (`2025.1`), V3 (`2025.2`), mỗi version 4 round:

- R1: suite gốc từ tài liệu;
- R2: nguyện vọng thật từ khảo sát;
- R3: trạng thái đăng ký, chỉ lưu biên nhận, không đổi eligibility;
- R4: `extra_steps_no_new_signal`, train thêm bước trên cùng input.

`2025.3` chỉ đánh giá một lần sau khi đóng băng.

Lưu ý: thư mục `data/` nằm trong `.gitignore`, Git không theo dõi. Xóa dòng trong `data/` sẽ không khôi phục được từ Git, cần sao lưu trước.

## 3. Chưa làm (yêu cầu gần nhất)

1. Chia toàn bộ dữ liệu theo năm và loại bỏ dòng không có năm. Dự kiến loại 184 dòng giảng viên không có năm và 13 hồ sơ sinh viên không có năm trên bìa. Cần sao lưu `data/` trước khi chạy.
2. File `.md` hướng dẫn train model.
3. Sửa PRD/SPEC và code: giữ R1–R3, thay R4 bằng round đưa điểm skill chuyên môn của giảng viên vào train và xuất model cuối của version. Điểm tính từ skill đã tổng hợp theo công thức `profile = 0,4P + 0,6E`, `final = 0,5 profile + 0,5 GVHD`.
   Scorer hiện chỉ nhận claim đã duyệt và có `available_at`. Vì mọi claim đang `pending`, R4 cần thêm chế độ proxy, ghi nhãn `retrospective_document_proxy`, không gọi là điểm đã xác minh.
