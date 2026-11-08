# SPEC — Rebuild UniMatch theo RL hai cấp

Ngày: 30/10/2026. Trạng thái: đề xuất; chưa áp dụng thay đổi implementation.

## 1. Quyết định kiến trúc
Chọn rebuild có kiểm soát trên module hiện có. Không viết trắng toàn bộ repo: cách đó làm tăng nguy cơ lệch API và mất hành vi frontend. Chỉ dọn tài liệu cũng chưa đủ vì cấu hình và entrypoint cần phản ánh hướng RL hiện hành.

Giữ `frontend/` nguyên trạng. Giữ cấu trúc `backend/app/` gồm main, schemas, storage, portal, cohorts, production và các API hiện dùng. Giữ các lớp `src/domain`, `src/environment`, `src/features`, `src/evaluation`, `src/rl`, `src/serving` theo dependency thực tế. Module khác chỉ được loại sau khi rà caller và kiểm thử chứng minh không còn cần.

## 2. Luồng dữ liệu và quyết định
Input được kiểm tra schema; feature và allocation problem được dựng theo contract đã version hoá; baseline/PPO/DQN tạo phương án; evaluator kiểm tra ràng buộc và metric; candidate qua gate hoặc bị loại; retention ledger trỏ đến checkpoint được giữ. Serving chỉ dùng artifact được phát hành riêng.

Data hiện tại được giữ để tham chiếu, không tự động trở thành dataset của đợt rebuild mới. Chưa thay nguồn mặc định trước khi kiểm tra frontend/backend contract. Không hard-code đường dẫn run cũ vào thiết kế mới.

## 3. Hợp đồng vòng RL
Một vòng phải truy vết được: algorithm, academic_term, training_version, cohort_id, round_index, parent, snapshot hash, feature/state contract hash, signal hash, config, seed và code version.

Nguồn triển khai đang có: `src/rl/nested_learning.py`, `src/rl/model_retention.py`, `scripts/train_nested_rl.py` và `scripts/evaluate_nested_final.py`. Tái sử dụng trước khi thêm abstraction.

- Vòng đầu bootstrap khi không có parent hợp lệ.
- Vòng trong kế thừa learner state phù hợp, cùng cohort; tín hiệu phải có provenance và thời điểm.
- Vòng ngoài kế thừa checkpoint accepted gần nhất, không kế thừa candidate rejected.
- Chặn parent không tương thích feature/state contract hoặc thứ tự thời gian.
- PPO thu rollout mới. DQN không tái dùng replay có ngữ nghĩa reward/mask/signal không tương thích.
- Mỗi vòng lưu immutable input, report, decision, checkpoint và manifest hash; không ghi đè parent.

## 4. Dữ liệu để làm sau
Chỉ định nghĩa contract, chưa tạo dữ liệu mới. Giữ riêng academic_term, training_version, event_time, available_at và collected_at. Có stable ID, source, hash và trạng thái review; unknown khác zero.

Quy ước học vụ hiện có: tháng 9–12 năm Y là Y.1; tháng 1–5 là (Y−1).2; tháng 6–8 là (Y−1).3. Không dùng ngày hiện tại hoặc tên file để suy kỳ. Mapping V1–V4 cũ là provenance lịch sử; không mặc định áp dụng cho dataset mới. Snapshot faculty và cửa sổ cohort là hai mốc riêng.

Split theo định danh sinh viên, tránh cùng người xuất hiện cả train và holdout. Feature phải có ở thời điểm quyết định; nguồn hồi cứu phải ghi rõ proxy, không chứng minh khả dụng lịch sử. Không tạo nguyện vọng hoặc outcome thật từ tài liệu khóa luận.

## 5. Evaluation và phát hành
So sánh cùng input/ràng buộc với Hungarian và Greedy. Báo cáo feasibility, unmatched, compatibility, mức sử dụng quota và metric đã được định nghĩa trong evaluator. Gate acceptance/forgetting phải chốt trước training trong config; không bịa ngưỡng số trong spec.

Validation phục vụ chọn model. Final test chỉ mở sau khi khóa lựa chọn; không retune theo test. Acceptance nghiên cứu không tự promote serving. Khi thiếu model hoặc dữ liệu, giữ lỗi/trạng thái rõ theo hợp đồng hiện hành; không tự đổi sang mock.

## 6. Chính sách tài liệu
Giữ tài liệu frontend/portal và RL hai cấp cùng tài sản được chúng tham chiếu. Tạo PRD.md và SPEC.md làm tài liệu sản phẩm/kỹ thuật mới. README.md và DOCS.md cần viết lại làm điểm vào; PRODUCT.md và DESIGN.md được thay bằng hai tài liệu mới nếu nội dung cũ trùng hoặc lỗi thời.

Xoá các báo cáo phase 0–8, kế hoạch rebuild cũ và spec PPO/DQN đơn cấp khi nội dung không còn cần cho frontend hoặc RL hai cấp. Đánh giá bằng nội dung, không chỉ tên file. DOCX trong data/, data_rebuild/, backups/ là nguồn dữ liệu hoặc dependency; không xoá theo extension. README của dependency/cache không thuộc tài liệu dự án cần dọn.

## 7. Thực hiện và kiểm chứng sau duyệt
1. Lưu snapshot Git và patch cho thay đổi cục bộ; lập danh sách file dự kiến xoá.
2. Khoá baseline frontend bằng hash; ghi API đang được gọi.
3. Dọn tài liệu theo danh sách, cập nhật README/DOCS và liên kết.
4. Chuẩn hoá cấu hình/entrypoint quanh nested RL; giữ cấu trúc backend và API. Chỉ sửa logic khi có nhu cầu cụ thể và test phù hợp.
5. Chạy frontend check/build, backend/API tests và nested RL/retention tests; kiểm tra hash frontend và dữ liệu.
6. Báo cáo diff, kết quả kiểm chứng và phần data chưa thực hiện. Không push hoặc deploy trong đợt này.

## 8. Rủi ro và giới hạn
Repo đang có thay đổi tại scripts/export_four_round_results.py, scripts/run_four_round_research.py và file chưa track scripts/prepare_explicit_mock_feedback.py. Bảo toàn chúng. docs/ và tests/ đang nằm trong .gitignore dù nhiều file đã track; phải bảo đảm tài liệu và test mới được Git nhận đúng phạm vi, không đưa dữ liệu riêng tư vào Git.
