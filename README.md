# UniMatch

UniMatch là đồ án hỗ trợ phân công sinh viên với giảng viên hướng dẫn khóa luận. Hệ thống dùng thông tin đề tài, hồ sơ chuyên môn của giảng viên và chỉ tiêu hướng dẫn để tạo các phương án phân công. Người phụ trách có thể xem từng lựa chọn và đối chiếu các phương án trước khi quyết định.

## Portal hỗ trợ gì?

- **Chuẩn bị hồ sơ** từ Excel hoặc CSV, xem lỗi theo dòng, xác nhận danh sách sinh viên và xuất workbook chuẩn hóa.
- **Tra cứu giảng viên** theo nội dung đề tài và hồ sơ chuyên môn đã duyệt. Kết quả gợi ý theo từng sinh viên và kết quả phân công cả nhóm được hiển thị riêng.
- **So sánh phương án phân công** trên cùng danh sách sinh viên, giảng viên và quota. Kết quả có bảng phân bổ, biểu đồ, mô phỏng 3D từng quyết định và dữ liệu xuất để xem lại.
- **Xem kết quả nghiên cứu** qua báo cáo huấn luyện và đánh giá đã lưu. Portal phục vụ mô hình đã đóng gói và chạy suy luận khi người dùng yêu cầu phân công.

## Bài toán và phương pháp

UniMatch biểu diễn mỗi đợt phân công bằng danh sách sinh viên, điểm tương thích với giảng viên, điều kiện ghép hợp lệ và chỉ tiêu còn lại. Điểm tương thích đến từ nội dung đề tài và hồ sơ chuyên môn. Khi hồ sơ sinh viên thiếu ý tưởng, hệ thống dùng quota còn lại để ghép và để điểm tương thích ở trạng thái chưa xác định.

Hệ thống so sánh **Hungarian**, **Greedy**, **Random**, **Maskable PPO** và **Masked DQN**. Hungarian là phương pháp đối chiếu tối ưu tổng điểm trong bài toán đã mô hình hóa. Greedy và Random cho thêm hai mốc so sánh. PPO và DQN ra quyết định tuần tự với mặt nạ hành động để lọc lựa chọn vi phạm ràng buộc.

## Dữ liệu và đánh giá

| Phiên bản | Tập theo kỳ | Vai trò |
| --- | --- | --- |
| V1 | 2024 | Giai đoạn huấn luyện đầu |
| V2 | 2025.1 | Giai đoạn huấn luyện tiếp theo |
| V3 | 2025.2 | Giai đoạn huấn luyện cuối |
| Test ngoài | 2025.3 | Đánh giá sau khi đóng băng checkpoint |

Danh mục Strict có GitHub gồm sáu checkpoint, tương ứng PPO và DQN ở round 4 của V1, V2 và V3. Báo cáo kỳ 2025.3 dùng 19 hồ sơ sinh viên để đối chiếu điểm, độ bao phủ và vi phạm ràng buộc. Đây là đánh giá hồi cứu trên dữ liệu tài liệu. Điểm số mô tả phương án trong phạm vi bộ dữ liệu và cần được người phụ trách xem xét khi áp dụng vào thực tế.

Dữ liệu gốc, hồ sơ sinh viên, thông tin kết nối và các gói trọng số được lưu riêng. Repository chứa mã, hợp đồng dữ liệu, mẫu nhập và tài liệu nghiên cứu.

## Cấu trúc repository

| Đường dẫn | Nội dung |
| --- | --- |
| [frontend/](frontend/) | Giao diện HTML, CSS, JavaScript và mô phỏng 3D |
| [backend/](backend/) | API FastAPI, xác thực, lưu hồ sơ và kết quả, nạp gói mô hình |
| [src/](src/) | Pipeline dữ liệu, đặc trưng, ràng buộc, baseline, RL, đánh giá và suy luận |
| [scripts/](scripts/) | Công cụ chuẩn bị dữ liệu, chạy thí nghiệm và phát hành mô hình |
| [configs/](configs/) và [database/](database/) | Taxonomy, hợp đồng cấu hình và lược đồ lưu trữ |
| [tests/](tests/) | Kiểm thử hợp đồng dữ liệu, thuật toán, API và lưu trữ |
| [docs/](docs/) | Tài liệu sản phẩm, vận hành, nghiên cứu và lưu trữ |

[Chỉ mục tài liệu UniMatch](docs/README.md)
