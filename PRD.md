# PRD — UniMatch RL hai cấp

Ngày: 30/10/2026. Trạng thái: bản đề xuất để rà soát trước rebuild.

## 1. Mục tiêu
Rebuild UniMatch quanh bài toán phân công sinh viên–giảng viên có ràng buộc và RL hai cấp. Giữ frontend hiện tại, giữ cấu trúc backend và hợp đồng API mà frontend đang dùng. Dữ liệu sẽ xây dựng lại ở giai đoạn riêng.

## 2. Người dùng và luồng chính
- Sinh viên: nhập hồ sơ, xem giảng viên, khai báo nguyện vọng, xem đề xuất.
- Giảng viên: cung cấp phản hồi có nguồn và thời điểm xác nhận.
- Điều phối viên: kiểm tra quota/eligibility, so sánh phương án, duyệt kết quả và xuất CSV.
- Người nghiên cứu: chạy PPO/DQN, so sánh baseline, kiểm tra lineage và quyết định giữ hoặc loại candidate.

Giữ nguyên bố cục, interaction và các trạng thái giao diện hiện có. Không thêm màn hình hoặc redesign trong đợt này.

## 3. Phạm vi rebuild
1. Giữ frontend và cấu trúc backend/app; tái sử dụng module domain, environment, evaluation và RL đang đáp ứng thiết kế mới.
2. Chuẩn hoá entrypoint, cấu hình và tài liệu để RL hai cấp là hướng hiện hành duy nhất.
3. Loại bỏ tài liệu cũ không liên quan RL hai cấp hoặc frontend; cập nhật liên kết đến tài liệu thay thế.
4. Không crawl, tạo dataset mới, train lại hoặc thay checkpoint phục vụ trong đợt rebuild nền tảng.
5. Bảo toàn dữ liệu nguồn và thay đổi chưa commit; không xoá dependency hoặc code chỉ vì tên có chữ rebuild/legacy.

## 4. Định nghĩa RL hai cấp
Hai cấp là hai thang cập nhật theo thời gian, không mặc định là kiến trúc manager–worker.
- Cấp trong: cập nhật nhiều vòng trên cùng cohort trong một học kỳ khi có tín hiệu mới hợp lệ.
- Cấp ngoài: chuyển sang học kỳ tiếp theo từ checkpoint gần nhất đã được chấp nhận.
- Candidate bị loại không được trở thành parent; thiếu phản hồi phải ghi skipped/unavailable.
- PPO và DQN là hai learner độc lập, không phải hai cấp của hệ thống.

## 5. Yêu cầu sản phẩm
- FR01: bảo toàn luồng frontend và cấu trúc response API hiện dùng.
- FR02: mỗi vòng có định danh học kỳ, cohort, thuật toán, parent, snapshot, signal và config.
- FR03: kiểm tra quota, eligibility, action mask và phương án không khả thi trước khi công bố kết quả.
- FR04: phân biệt phản hồi thật, mock và proxy; không dùng mock làm bằng chứng học vụ.
- FR05: so sánh PPO/DQN với Hungarian và Greedy cùng bài toán, cùng ràng buộc.
- FR06: phân biệt research acceptance, checkpoint retention và production promotion.
- FR07: thiếu dữ liệu/artifact phải trả trạng thái rõ; không âm thầm dùng dataset hoặc kết quả cũ như dữ liệu mới.

## 6. Tiêu chí nghiệm thu
- Frontend source không đổi; kiểm tra cú pháp và build thành công.
- Backend giữ package/route đang được frontend gọi; kiểm tra hợp đồng và luồng chính đạt.
- Test RL bao phủ kế thừa parent, candidate bị loại, thiếu tín hiệu và ràng buộc phân công.
- Không thay raw data, dataset, checkpoint hoặc ba script đang có thay đổi cục bộ ngoài phạm vi được duyệt.
- Danh sách tài liệu giữ/xoá có thể kiểm tra; không còn liên kết tài liệu nội bộ bị hỏng trong tài liệu hiện hành.
- Không tuyên bố RL tốt hơn Hungarian hoặc cải thiện kết quả giáo dục nếu chưa có bằng chứng mới.

## 7. Giai đoạn tiếp theo
Sau khi rebuild nền tảng được kiểm chứng: chốt nguồn dữ liệu, contract, split và cutoff; thu thập lại; chạy baseline; train/evaluate; chỉ xét phát hành sau gate riêng. Không đặt trước số lượng hồ sơ hoặc metric đạt được.
