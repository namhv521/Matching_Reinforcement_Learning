# Prompt rebuild dữ liệu sinh viên và kiểm tra thiên lệch AI trong UniMatch

Sao chép toàn bộ phần dưới vào chat triển khai tại workspace UniMatch.

---

Bạn đang làm việc trong repository UniMatch ở C:\Su\KLTNv2\KLTN. Hãy kiểm tra pipeline hiện tại, sửa lỗi trích kỹ năng, đọc lại tài liệu gốc của sinh viên và xuất CSV đã sửa kèm bằng chứng. Sau đó dựng lại đầu vào matching và chạy đối chứng để xác định lỗi dữ liệu đã ảnh hưởng đến kết quả thế nào. Đọc AGENTS.md nếu có. Áp dụng MLE Workflow và Ponytail. Dùng tài liệu, test và lệnh sẵn trong repo khi phù hợp.

## Lỗi cần xử lý

- Ở 2025.1, CSV đã xử lý có AI ở 63/68 hồ sơ, machine learning ở 52/68 và C++ ở 21/68. Hệ thống đang chuyển lượt nhắc trong PDF thành tín hiệu kỹ năng. Ví dụ đã xác minh gồm AI trong hướng phát triển website, AI/ML trong bảng chữ viết tắt và C++ trong đoạn mô tả những ngôn ngữ VS Code hỗ trợ. Các ví dụ này chưa chứng minh sinh viên đã sử dụng công nghệ đó. Kiểm tra cả ngôn ngữ, framework và các nhóm tag khác với cùng nguyên tắc.
- Trong pipeline hiện tại, tag có thể bật cờ concept và cũng đi vào văn bản tính cosine. Việc đếm một lượt nhắc ở cả hai nơi có thể làm hồ sơ bị lệch về AI, đồng thời làm baseline cosine bị lệch theo. Cần đo mức lệch thay vì kết luận từ tần suất tag.
- Excel nguyện vọng phục vụ ghép danh tính và chấm bài test V1 trên 2025.1. Cột kỹ năng tự khai là nguồn riêng. Tránh lẫn nguyện vọng, tên giảng viên, tên/mã sinh viên hay kết quả GVHD lịch sử vào feature dùng lúc suy luận.
- V1-R3 và R4 có cùng dữ liệu. R4 khởi đầu từ R3 rồi train thêm 131.072 bước, nên cosine validation 2024 tăng từ 0,103404 lên 0,106638 dù top 3 khớp nguyện vọng 2025.1 giảm từ 6/19 còn 4/19. Với V2 và V3, R3 bị loại và R4 quay về cùng checkpoint V1-R4. Báo cáo phải phân biệt lượt tiếp tục train với lượt chạy lại từ cùng cha.

## 1. Đọc lại nguồn và sửa extractor

1. Lập inventory PDF từ các thư mục data/<học kỳ>/student/KLTN. Đối chiếu hash, danh tính, học kỳ và các quyết định partition đã có. Dùng lại text cache khi hash PDF khớp. Trích PDF/OCR khi thiếu text hoặc lỗi font. Đọc lại text với extractor mới, vì cache evidence cũ chứa kết quả của quy tắc đang sửa. Ghi riêng PDF lỗi, trùng hoặc chưa xác định được. Tránh tải thêm nguồn hoặc gửi hồ sơ cá nhân ra ngoài khi chưa cần.
2. Bắt đầu từ scripts/partition_student_pdfs.py và src/data_pipeline/normalization.py. Giữ taxonomy để ánh xạ alias, thêm bước xét ngữ cảnh trước khi chuyển lượt nhắc thành feature. Phân biệt tiêu đề/chủ đề chính, phương pháp/triển khai/thực nghiệm có bằng chứng, kiến thức nền, công nghệ chỉ liệt kê, hướng phát triển và tài liệu tham khảo. Giữ đoạn trích gốc, số trang, hash, lý do và trạng thái review cho từng ứng viên tag.
3. Dùng quy tắc đơn giản và áp dụng đồng đều cho mọi nhóm công nghệ. Bằng chứng trực tiếp như triển khai, cấu hình, thí nghiệm hoặc kết quả hỗ trợ tag kỹ năng. Chủ đề nghiên cứu có thể giữ ở cột chủ đề dù chưa có bằng chứng triển khai. Nội dung chỉ xuất hiện trong mục lục, bảng viết tắt, tài liệu tham khảo, liệt kê công cụ, so sánh lý thuyết hoặc đề xuất tương lai chỉ lưu để audit và có trọng số 0 trong matching. Khi ngữ cảnh chưa đủ rõ, gắn needs_review và mặc định bỏ khỏi feature.
4. Nếu cần giữ tín hiệu chủ đề gián tiếp, thử cấu hình trọng số thấp hơn tín hiệu trực tiếp, chẳng hạn 0,25 so với 1,0. Đây là một cấu hình thử nghiệm. Kiểm tra nó trên validation cùng cấu hình trọng số 0 trước khi chọn. Áp dụng cùng tiêu chuẩn cho AI, web, mobile, nghiên cứu và nhóm kỹ năng khác. Giữ đủ điểm cho AI thực sự là phương pháp chính và có bằng chứng, tránh dùng ngưỡng ép số lượng hồ sơ AI.
5. Theo dõi một tag đi qua cả cờ concept lẫn text encoder. Tag không đạt chuẩn phải được loại khỏi cả hai đường. Nếu dùng trọng số thấp, xác minh code thực sự giảm đóng góp ở nơi sử dụng feature. Ghi 0,25 vào CSV trong khi pipeline chỉ kiểm tra tag có mặt sẽ không tạo ra hiệu ứng mong muốn. Ưu tiên lọc evidence và giữ schema nhị phân hiện có nếu đủ giải quyết lỗi. Nếu đổi schema, version hóa và kiểm tương thích checkpoint.

## 2. Xuất CSV mới và kiểm chất lượng

- Tạo thư mục snapshot mới. Xuất CSV sinh viên theo học kỳ, bảng evidence/audit và manifest hash. Giữ cột schema đang có và chỉ thêm dữ liệu provenance ở sidecar nếu giúp tránh phá người dùng cũ. Ghi rõ CSV nào đã thu thập, CSV nào đã lọc và bộ nào được dùng cho train. Không chạy chế độ di chuyển PDF để re-extract. Giữ run 20261105 làm mốc đối chứng.
- Thêm test hồi quy bằng ví dụ đại diện. Website ghi “sẽ thêm AI chatbot” không có AI skill. Bảng chữ viết tắt AI/ML không cấp kỹ năng. VS Code hỗ trợ C++ không cấp C++. Dự án có train và đánh giá mô hình ML phải giữ ML. Dự án dùng C++ có bằng chứng triển khai phải giữ C++. Nghiên cứu thực nghiệm và dự án web/mobile phải giữ kỹ năng có bằng chứng tương ứng.
- Rà mẫu thật có phân tầng theo web, mobile, nghiên cứu, AI và nhóm khác. Ghi cỡ mẫu, nhãn tay, số đúng/sai và ví dụ bỏ nhầm. Báo số hồ sơ, nguồn lỗi, tag AI/ML/C++ trước và sau, tỷ lệ hồ sơ thiếu bằng chứng và độ phủ kỹ năng có thật ở từng nhóm. Tránh lấy mức giảm tần suất AI làm tiêu chí thành công duy nhất.
- Đối chiếu identity, hash, kỳ, split, dữ liệu thiếu và rò rỉ. 2025.3 tiếp tục đóng băng. Nếu cần xuất lại theo schema mới, chỉ xử lý bằng quy tắc đã chốt và giữ riêng snapshot external, tránh dùng số liệu đó để chỉnh extractor, trọng số hay chọn checkpoint.

## 3. Dựng lại matching và đo tác động

1. Tạo input package mới và chạy kiểm checksum, coverage, score parity. Freeze encoder từ train V1 theo quy trình hiện hành. Dùng corpus GV đúng mốc V1. Rebuild score và concept từ CSV mới. Khi ý nghĩa feature thay đổi, train lại V1 từ đầu trên snapshot mới thay vì tiếp tục checkpoint cũ.
2. Chạy đối chứng trên cùng split, roster, quota, seed và ngân sách bước khi so sánh trước/sau. Tách kết quả baseline cosine/Hungarian khỏi kết quả PPO để thấy thay đổi đến từ dữ liệu hay học thêm. Ghi checkpoint cha thực tế và số bước. Nếu cần thu hẹp thời gian, chạy baseline và kiểm input trước, rồi mới train. Ghi rõ phần đã chạy và phần còn thiếu.
3. Chạy lại bài V1 trên cùng 19 sinh viên 2025.1 đã đối chiếu họ tên, mã, kỳ và nguyện vọng trong Excel. Giữ nguyện vọng ngoài đầu vào. Nếu số SV chấm được thay đổi, báo cả số trên mẫu đầy đủ lẫn mẫu chung để so sánh công bằng. So sánh gợi ý đầu khớp ưu tiên 1, top 3 chứa ít nhất một nguyện vọng và, nếu có gán nhóm, số sinh viên được gán trúng nguyện vọng.
4. Kiểm tra thiên lệch bằng tỷ lệ giảng viên AI xuất hiện trong top 3 của nhóm SV có và không có bằng chứng AI. Cố định roster và cách xác định nhóm GV từ hồ sơ có bằng chứng. Với nhóm không có bằng chứng AI, rà các gợi ý GV AI xem chúng đến từ chuyên môn khác phù hợp hay từ tag nhiễu. Giảng viên đa lĩnh vực vẫn có thể là lựa chọn tốt. Báo rõ nếu chưa đủ dữ liệu để phân nhóm GV tin cậy.
5. Viết báo cáo ngắn có bảng trước/sau. Ưu tiên 4 kết quả dễ đọc gồm tần suất tag nhiễu, mức xuất hiện GV AI trong nhóm SV ngoài AI, mức khớp nguyện vọng 2025.1 và điểm phù hợp trên validation. Kèm đường dẫn CSV, manifest, test hồi quy và các trường hợp cần review. Chỉ diễn giải cải thiện khi so sánh cùng mẫu và chỉ số. Ghi rõ đâu là bằng chứng nguồn, đâu là kết quả đo.

## Nguồn trong repo

- Extractor PDF và taxonomy: scripts/partition_student_pdfs.py, src/data_pipeline/normalization.py và configs/data/taxonomy_v1.yaml.
- Dựng CSV train và đầu vào matching: scripts/prepare_semester_rl_inputs.py, src/features/semester_suite.py và scripts/run_semester_rl.py.
- Run đối chứng: outputs/semester_rl_20261105/training.
- Báo cáo V1 và phụ lục kiểm tra nhiễu: outputs/semester_rl_20261105/bao_cao_v1_test_nguyen_vong_2025_1.md.

---
