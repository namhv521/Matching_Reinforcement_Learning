# TÓM TẮT RL HAI CẤP TRONG PHÂN CÔNG GIẢNG VIÊN HƯỚNG DẪN

**Mục tiêu.** Xây dựng mô hình phân công sinh viên–giảng viên theo mức phù hợp chuyên môn, nguyện vọng, sự đồng ý của giảng viên và chỉ tiêu. Hai cấp gồm **Continual RL giữa ba version theo thời gian** và **RL qua các vòng phản hồi trong từng version**. Đây là cách tổ chức huấn luyện, chưa phải Hierarchical RL với hai policy quản lý–thực thi. Bản thiết kế này chỉ sử dụng dữ liệu thật được cung cấp.

**1. Cấp ngoài — Ba model liên tục.** **V1 là model nguyên sơ**, dùng toàn bộ lịch sử đến **31/08/2025**, gồm các khóa luận 2024.1, 2024.2, 2024.3 và các năm trước. Hồ sơ giảng viên cùng toàn bộ danh mục nghiên cứu, bài báo được đưa vào kho dữ liệu khởi tạo; đặc trưng dùng để huấn luyện lịch sử phải có thông tin khả dụng không muộn hơn cutoff. **V2 ứng với kỳ 2025.1**, học tiếp với dữ liệu từ **01/09 đến 31/12/2025**. **V3 ứng với kỳ 2025.2**, học tiếp với dữ liệu từ **01/01 đến 31/05/2026**. V2 và V3 kế thừa trọng số, optimizer và bộ đếm từ model được chấp nhận gần nhất, không khởi tạo lại. Biểu diễn đặc trưng được giữ tương thích; thông tin giảng viên mới được cập nhật theo thời điểm khả dụng.

**2. Cấp trong — Bốn round trong mỗi version.** Giữ cùng nhóm sinh viên của version, cập nhật theo phản hồi thật và kế thừa model giữa các round. Riêng V1 gộp dữ liệu nhiều kỳ, không đồng nhất V1 với một học kỳ đơn lẻ.

| Vòng | Đầu vào bổ sung | Cách cập nhật |
|---|---|---|
| R1 | Hồ sơ, chuyên môn và chỉ tiêu giảng viên | Khởi tạo V1; với V2/V3, học tiếp từ version trước. |
| R2 | Lựa chọn của **một phần** sinh viên | Cập nhật preference cho các cặp được chọn; người chưa chọn vẫn có trạng thái chưa biết. |
| R3 | Giảng viên nhận/từ chối từng yêu cầu | Cập nhật điều kiện ghép cặp; cặp bị từ chối bị chặn, sinh viên vẫn có thể được phân công cho người khác. |
| R4 | Điều chỉnh của điều phối, nếu có | Hiện giữ nguyên dữ liệu R3 và train tiếp; phải ghi rõ không có tín hiệu mới. |

Giảng viên chấp nhận nghĩa là cặp đó được phép xem xét, chưa khóa phân công cuối cùng. Checkpoint được giữ sau các round là nguồn cho R1 của version kế tiếp. Thiếu phản hồi phải ghi nhận là chưa có, không tự tạo nhãn nhận/từ chối.

**3. RL trong từng round.** PPO hoặc DQN học qua tương tác với môi trường phân công xây dựng từ dữ liệu thật. **Trạng thái** gồm đặc trưng sinh viên, mức phù hợp/nguyện vọng, chỉ tiêu còn lại và các cặp hợp lệ. **Hành động** là chọn giảng viên cho sinh viên đang xét. Môi trường cập nhật chỉ tiêu, trả **reward** theo mục tiêu phân công và trạng thái mới; mask chặn các hành động không hợp lệ. Một episode phân công cả nhóm; một step là một quyết định. Lặp lại episode để tối ưu policy không đồng nghĩa có thêm sinh viên hay thêm phản hồi mới.

**4. Đầu vào và đầu ra.** Đầu vào gồm khóa luận/hồ sơ sinh viên có tháng năm, chuyên môn và công bố giảng viên có thời điểm khả dụng, chỉ tiêu, lựa chọn/nhận/từ chối theo từng cặp và checkpoint trước đó. Đầu ra gồm **checkpoint từng round, đề xuất phân công, metric và quyết định giữ/loại candidate**. So parent/candidate trên cùng validation và kiểm tra holdout cũ để phát hiện quên kiến thức. Candidate không đạt vẫn được lưu, nhưng không làm nguồn trọng số kế thừa; tổng bước tính toán khác với bộ đếm của model được giữ.

**5. Test ngoài và trạng thái triển khai.** **Kỳ 2025.3 từ 01/06 đến 31/08/2026 được để ngoài cả V1, V2, V3**, chỉ dùng làm test cho V3 sau khi đóng băng model. Không dùng nhóm này để train, fit đặc trưng, chỉnh reward, chọn checkpoint hoặc điều chỉnh ngưỡng. Các version vẫn cần train/validation riêng trước bước test ngoài. Theo dõi utility, đáp ứng nguyện vọng, coverage và vi phạm ràng buộc, đối chiếu Hungarian/Greedy; utility không phải accuracy hay điểm khóa luận. **Dữ liệu thật 2025.2 sẽ được cung cấp sau; V3 hiện là giai đoạn chờ dữ liệu.** Đây là summary và sơ đồ kế hoạch mới, không phải kết quả đã train theo cấu trúc này.
