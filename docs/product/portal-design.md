# UniMatch · Hướng dẫn triển khai portal khóa luận

Tài liệu này ghi lại định hướng thiết kế và tiêu chí nghiệm thu đề xuất cho portal khóa luận. [README dự án](../../README.md) mô tả phạm vi hệ thống hiện tại.

## 1. Hành trình chính

| Màn hình | Người dùng cần làm được |
|---|---|
| Trang chủ | Hiểu UniMatch trong một màn hình, xem mô phỏng minh họa và bắt đầu quy trình nhập danh sách |
| Nhập danh sách | Tải Excel, ánh xạ cột, xem lỗi theo dòng và tải mẫu chuẩn hóa |
| Thiết lập phân công | Chọn kỳ, kiểm tra danh sách giảng viên, quota và phương pháp |
| Kết quả | Xem bảng ghép, so sánh thuật toán, lọc theo sinh viên hoặc giảng viên, duyệt phương án và xuất kết quả |
| Mô phỏng | Phát lại các quyết định theo từng bước, xem quota còn lại và lý do ghép |
| Trợ lý | Tra cứu chủ đề, giảng viên và kết quả trong phạm vi được cấp quyền, kèm nguồn |

Khách xem trang chủ và demo dùng dữ liệu giả lập. Điều phối viên được cấp quyền theo kỳ có thể import, thiết lập quota, chạy so sánh và duyệt phương án. Sinh viên chỉ xem hồ sơ của chính mình và kết quả đã được công bố. Backend kiểm tra quyền theo vai trò, kỳ và đối tượng ở từng thao tác, kể cả khi mở link trực tiếp. Luồng làm việc theo thứ tự **Nhập → Xem trước → Chốt quota → Chạy thử → Duyệt và công bố**. Mọi kết quả chạy thử giữ trạng thái đề xuất.

## 2. UI và ngôn ngữ thiết kế

**Hướng thiết kế.** Gợi không khí trường đại học hiện đại. Trang chủ dùng xanh nước biển đậm, bề mặt trắng xanh và ảnh khuôn viên được phép sử dụng hoặc minh họa 3D tự dựng. Đề xuất `#073B78` cho màu chủ đạo, `#165BB5` cho hành động và `#F3F7FD` cho nền nhẹ. Các màu này lấy cảm hứng từ Kinh tế Quốc dân. Mọi nội dung nhận diện chính thức cần dùng asset được cấp phép.

- Hero dùng tiêu đề **“Từ ý tưởng đến người hướng dẫn phù hợp”**. Nút chính của khách là **“Vào UniMatch”**, nút phụ **“Xem mô phỏng mẫu”**. Sau đăng nhập, điều phối viên thấy **“Nhập danh sách sinh viên”**, sinh viên thấy **“Xem hồ sơ khóa luận”**. Chỉ khôi phục đường dẫn nội bộ mà vai trò đó được phép mở.
- Trên desktop, đặt nội dung và CTA bên trái, mô phỏng khuôn viên bên phải. Trên mobile, đưa tiêu đề và CTA lên trước, sau đó mới đến hình minh họa. Hiển thị giao diện thao tác ngay khi tải trang.
- Dùng một họ chữ hỗ trợ tiếng Việt như Be Vietnam Pro hoặc font hệ thống. Chia sẻ token màu, khoảng cách, typography và focus. Các thao tác ưu tiên dùng nút chính màu xanh. Hành động phụ dùng viền, còn xóa dùng màu cảnh báo và xác nhận rõ đối tượng.
- Dùng nhãn theo công việc thật: **“Kiểm tra dữ liệu”**, **“Tải Excel chuẩn”**, **“Chạy so sánh”**, **“Xem phân công”**. Trạng thái tải, lỗi, thành công, trống và thiếu quyền có nội dung rõ. Lỗi nhập trỏ đến dòng và cột cần sửa.
- Dùng điều hướng bàn phím, focus thấy rõ, bảng có tiêu đề, màu trạng thái kèm nhãn. Nút tương tác trên màn hình cảm ứng có mục tiêu khoảng 44 px. Kiểm thử ở 360, 768 và 1440 px, với chữ tiếng Việt dài và chế độ giảm chuyển động.

## 3. Nhập Excel và chuẩn hóa

1. Điều phối viên chọn kỳ và tải `.xlsx`. Phiên bản đầu nhận một sheet dữ liệu do người dùng chọn, một dòng tiêu đề và một dòng cho mỗi sinh viên. Tên là trường bắt buộc đối với dòng sinh viên. Chấp nhận file chỉ có cột tên. Cho ánh xạ cột có tên khác mẫu.
2. Backend kiểm tra định dạng workbook và giới hạn kích thước cả trước lẫn sau giải nén, số sheet, số dòng, số cột và độ dài ô. Báo lỗi cho ô công thức trong các cột nhập, workbook có macro và dữ liệu phụ thuộc liên kết ngoài. Lỗi định dạng, sheet thiếu tiêu đề và dòng trùng mã phải hiện ở bước xem trước.
3. Chuẩn hóa khoảng trắng và Unicode tiếng Việt. Đọc mã sinh viên từ ô dạng text để giữ số 0 đầu. Nếu Excel đã chuyển mã thành số và có nguy cơ mất số 0, đánh dấu dòng cần kiểm tra. Giữ nguyên nội dung ý tưởng gốc và hiển thị đề xuất chuẩn hóa từ taxonomy để điều phối viên xem trước. Phân biệt mô tả gốc, tag tự khai và tag suy ra trong provenance.
4. Xuất workbook với sheet `SinhVien`, cột `student_id`, `student_name`, `topic_title`, `topic_description`, `skills`, `preferred_advisors` và metadata phiên bản schema. Với file chỉ có tên, tạo định danh tạm lúc xác nhận và lưu vào workbook chuẩn. Giữ định danh đó khi import lại dù dòng đổi vị trí. Trùng tên cần xem trước. Tài khoản sinh viên chỉ được liên kết sau khi đối chiếu mã chính thức. Khi xuất Excel và CSV, trung hòa công thức trong nội dung người dùng nhập.
5. Adapter map `topic_title` → `thesis_title`, `topic_description` → `thesis_abstract`, `skills` → `skills_tags`, và giải `preferred_advisors` về `preferred_advisor_ids` theo roster của kỳ. Tên giảng viên mơ hồ cần xác nhận. Kỳ lấy từ lựa chọn đã chốt. Các trường thiếu dữ liệu giữ trống hoặc unknown theo contract. Trả tóm tắt số dòng hợp lệ, cần sửa, có ý tưởng và chưa có ý tưởng. Chỉ tạo cohort sau khi xác nhận. File chuẩn import lại phải tái tạo cùng bản ghi kể cả khi thứ tự dòng thay đổi.

**Quy tắc phân biệt dòng trống.** Dòng thiếu tên và mọi ô đều trống được bỏ qua. Dòng thiếu tên nhưng có nội dung khác bị báo lỗi. Hiển thị riêng sinh viên chưa có ý tưởng, ý tưởng cần bổ sung và ý tưởng đã nhập nhưng encoder không nhận ra tín hiệu. Điều phối viên kiểm tra hai nhóm sau trước khi xác nhận đưa vào nhánh ghép theo quota dư.

**Phân công khi thiếu ý tưởng.** Khóa roster, quota và điều kiện hợp lệ trước khi chạy. Hiện `AllocationProblem.allowed` kết hợp `available`, `eligible` và `present`. Sinh viên thiếu điểm có thể bị loại khỏi đồ thị hiện tại. Vì vậy, dùng điều kiện hợp lệ và quota để dựng đồ thị khả thi riêng cho cả cohort, đồng thời giữ trạng thái điểm tương thích chưa biết. Các lựa chọn cho nhóm có tín hiệu phải chừa đủ suất hợp lệ cho phần còn lại, kể cả khi một sinh viên chỉ ghép được với một giảng viên. Sau đó dùng Random có seed trên các suất còn dư, lọc các lựa chọn làm phần còn lại mất tính khả thi. Ghi nhãn **“Ghép theo quota còn lại”**, seed và quota trước/sau. Nếu ngay từ đầu không có phương án đủ chỗ, báo phương án chưa khả thi và chỉ rõ dòng hoặc ràng buộc cần xử lý trước khi công bố.

## 4. Thuật toán, checkpoint và dữ liệu

### Danh mục phục vụ

- Hỗ trợ **Hungarian, Greedy, Random, PPO và DQN** trên cùng API so sánh. Đăng ký riêng sáu checkpoint Strict có GitHub **PPO/DQN × V1-R4, V2-R4, V3-R4**. Cho phép đăng ký phiên bản cũ và các checkpoint hợp lệ khác qua cùng cơ chế. Hiện phiên bản Strict trước khi bổ sung GitHub có roster hoạt động khác nên cần ghi rõ nguồn dữ liệu khi xem kết quả lịch sử.
- Dùng xếp hạng theo cosine trong màn hình gợi ý giảng viên cho từng sinh viên. Hiển thị quota còn lại riêng để người dùng phân biệt thứ hạng cá nhân với kết quả phân công cả nhóm. Biến thể `topic` chỉ hiện như cấu hình dữ liệu nghiên cứu cho đến khi có checkpoint tương thích.
- Mỗi mục có ID ổn định, phiên bản, số step, hash model, encoder, taxonomy, thứ tự feature, thứ tự giảng viên, reward và điều kiện tương thích. Model và snapshot chỉ nằm ở server. Portal hiện dựng điểm từ pipeline E4. Checkpoint theo học kỳ dùng encoder và feature contract riêng của suite. Cần adapter dựng đúng bài toán cho từng checkpoint và kiểm tra hash, state contract, roster, reward và quota trước khi gọi loader. Dùng fixture tổng hợp và ca đối chiếu kết quả với evaluator gốc để phát hiện lỗi đổi thứ tự feature hoặc hành động.
- Cho phép chọn checkpoint nghiên cứu trong màn hình so sánh. Kỳ thật dùng phương pháp mặc định đã được điều phối viên duyệt. Kết quả benchmark hồi cứu không tự động thay cấu hình này. Khi contract không khớp, báo lý do ngay trong bộ chọn. Chỉ đối chiếu điểm trực tiếp khi cùng cohort, cách tính điểm, roster, điều kiện ghép và quota.
- Mỗi lần chạy có mã run, ID snapshot, ID model, seed, tổng quota, phạm vi dữ liệu và thời điểm. Ở trạng thái thiếu khả thi, trả lý do rõ ràng. Fallback chỉ chạy khi điều phối viên chọn hoặc cấu hình kỳ đã bật. Kết quả ghi phương pháp thực tế.

### Nguồn và hợp đồng dữ liệu

- Đóng băng nguồn, kiểm tra hash, giữ danh mục giảng viên, thứ tự hành động và encoder đúng với từng model. Hiển thị riêng quota được duyệt, tình trạng tham gia và độ phủ dữ liệu. Thiếu vector có nghĩa model thiếu căn cứ tính điểm cho cặp tương ứng. Điều phối viên xử lý trường hợp đó theo quy tắc của kỳ. Kỳ thật dùng quota được duyệt và tính đến suất đã dùng. Quota chia đều trong benchmark là cấu hình thử nghiệm. Khóa luận kỳ 2025.3 giữ vai trò kiểm thử hồi cứu và không dùng để fit encoder, train hay chỉnh hyperparameter.
- Snapshot Strict có GitHub hiện đủ 17 giảng viên trong bài test 2025.3. Bản ghi công trình theo năm và README tại commit lịch sử là nguồn hồi cứu. Chỉ gắn nhãn khả dụng tại thời điểm phân công khi có bằng chứng tương ứng.
- Với pipeline skill được duyệt, giữ công thức `profile = 0.4 × prediction + 0.6 × evidence` và `final = 0.5 × profile + 0.5 × supervision`. Thành phần supervision lấy trung bình các khóa luận hợp lệ có dùng skill. Giá trị thiếu giữ trạng thái unknown. Chỉ tính score từ claim được duyệt theo hợp đồng, đúng scope và cutoff. Khử trùng theo nguồn công trình chuẩn và lưu provenance.
- Tài liệu vận hành snapshot cần giữ các gate sau: review ledger, cutoff có căn cứ, yêu cầu trước phân công, roster và ràng buộc operator. Thiếu đầu vào thì ghi `not_evaluable` cùng lý do. Snapshot hồi cứu giữ nhãn riêng khi hiển thị benchmark.

## 5. Kết quả, biểu đồ và mô phỏng 3D

- **Kết quả tổng hợp:** hiển thị số sinh viên đã ghép, số chưa ghép, điểm tương thích trung bình, số sinh viên có điểm, quota đã dùng và số vi phạm. Tính điểm trung bình trên các cặp có điểm và ghi rõ mẫu số. Khi các phương pháp có độ phủ điểm khác nhau, dùng cùng tập sinh viên có điểm để so sánh trung bình. Ô chưa có điểm trong bảng và heatmap hiển thị dấu gạch ngang. Dùng thanh ngang cho điểm trung bình, heatmap sinh viên × phương pháp và biểu đồ số sinh viên theo giảng viên. Cho đổi phương pháp và giữ thang đo cố định trong cùng biểu đồ.
- **Bảng và drill-down:** mỗi hàng có sinh viên, đề tài, giảng viên, điểm, phương pháp thực tế, quota và ghi chú. Lọc theo mã, giảng viên và trạng thái. Nhấn một hàng để xem phương án của các checkpoint và baseline. Với sinh viên ghép ngẫu nhiên do thiếu ý tưởng, hiển thị điểm chưa có và lý do.
- **Mô phỏng:** dùng lại Three.js và trace phát lại hiện có. Landing dùng cảnh khuôn viên giả lập. Cảnh kết quả đọc các bước phân công từ run được cấp quyền và dùng nhãn nội bộ như “SV 01”. Có phát, dừng, tua, đổi tốc độ, chuyển bước và xem quota trước/sau. Giải thích dựa trên điểm, quota và điều kiện thực tế trong trace. Với Hungarian, hiển thị các cặp từ nghiệm toàn cục theo thứ tự phát lại. Bảng và trình phát 2D cho cùng thông tin khi tắt 3D.
- **Xuất:** trả Excel hoặc CSV đã lọc theo quyền, kèm phiên bản schema, phương pháp, model và snapshot. Dữ liệu riêng tải qua endpoint đã xác thực và dùng `Cache-Control: private, no-store`.

## 6. RAG và AI agent

Đưa trợ lý vào cạnh màn hình làm việc. Các câu hỏi ưu tiên gồm **“Ai có kinh nghiệm NLP?”**, **“Vì sao sinh viên này được ghép như vậy?”** và **“Giảng viên nào còn quota?”**.

1. Index tài liệu nguồn được duyệt theo ID, kỳ, phiên bản và quyền. Metadata dùng để lọc **trước retrieval**. Dùng truy vấn SQL trực tiếp cho quota và kết quả run. Dùng tìm kiếm văn bản có sẵn cho nguồn tài liệu, bổ sung embedding khi kiểm thử cho thấy truy vấn tiếng Việt cần tìm ngữ nghĩa. Trích dẫn có tên tài liệu và phần liên quan.
2. Chỉ đưa đoạn trích cần thiết vào câu trả lời. Khi thiếu căn cứ, trả “Chưa có dữ liệu xác nhận” và chỉ rõ phạm vi tìm kiếm. Tài liệu truy xuất và ô Excel là dữ liệu đầu vào, mọi chỉ dẫn nằm trong đó được xử lý như văn bản.
3. Có thể bổ sung AI agent sau khi luồng tra cứu ổn định. Agent dùng các công cụ đã giới hạn quyền như tìm nguồn, xem quota và soạn bản nháp phân công. Mọi thao tác chạy phân công, đổi quota, nhập hoặc xuất dữ liệu cần người dùng thực hiện qua màn hình có quyền tương ứng. Chỉ gửi dữ liệu sang dịch vụ AI ngoài sau khi có cấu hình được duyệt và quy tắc giảm dữ liệu.

## 7. Bảo vệ dữ liệu và hiệu năng

- Dùng session và kiểm tra quyền ở backend cho cohort, run, trace, RAG, artifact và export. Đặt mã sinh viên, tên, Excel nguồn, báo cáo cá nhân và model ngoài thư mục static. Landing, asset, bundle, demo và ảnh kiểm thử chỉ dùng dữ liệu giả lập hoặc số liệu đã được duyệt để công khai. Báo cáo HTML có dữ liệu từng sinh viên thuộc phạm vi nội bộ và phải được bảo vệ như file xuất.
- Với endpoint riêng tư, lọc trường trả về, giới hạn truy cập theo kỳ/đối tượng và kiểm tra quyền khi export. Log kỹ thuật chỉ giữ mã run và mã lỗi cần thiết. Lưu audit ai đã import, chạy, đổi quota hoặc xuất. Chính sách giữ và xóa file nguồn cần được người vận hành chốt trước khi đưa vào dùng.
- Trang chủ hiển thị CTA và ảnh thay thế trước. Lazy-load Three.js khi cảnh vào viewport hoặc khi nhấn xem. Dừng vòng lặp khi tab ẩn, giảm pixel ratio và chất lượng cho máy yếu, giải phóng tài nguyên khi đổi màn hình. Bật chế độ tĩnh khi người dùng giảm chuyển động hoặc WebGL lỗi.
- Đặt mục tiêu nghiệm thu đề xuất **LCP ≤ 2,5 giây**, **INP ≤ 200 ms** và **CLS ≤ 0,1**. Đo LCP/CLS khi tải mới và INP trong các thao tác nhập, lọc và đổi biểu đồ trên thiết bị và mạng đã ghi lại. Mô phỏng nhắm 60 fps trên thiết bị tham chiếu, tự hạ chất lượng hoặc chuyển 2D nếu dưới 30 fps kéo dài. Đo thời gian xem trước Excel, thời gian chạy từng model và độ trễ RAG theo kích thước cohort, phân biệt lần nạp model đầu tiên và lượt đã có cache. Ghi số đo trước khi chốt ngưỡng backend.
- Backend nạp model theo nhu cầu và cache theo phiên bản. Việc parse Excel và chạy nhiều model dùng job có tiến độ nếu vượt thời gian phản hồi tương tác. Tránh tải lại khi người dùng bấm nhiều lần. Phân trang bảng và truyền trace theo đoạn khi kích thước vượt ngưỡng đo được.

## 8. Tổ chức code và thứ tự triển khai

Giữ FastAPI, frontend tĩnh và Three.js hiện có. Tách module theo trách nhiệm, mỗi module dùng contract có version. Dùng token và component chung. Đặt adapter import, danh mục model, engine phân công và RAG ở backend. Trang và component frontend chỉ đọc API đã định kiểu, cùng nguồn dữ liệu cho bảng, biểu đồ và mô phỏng.

Khi thêm model, đăng ký một mục trong catalog và chạy kiểm tra contract. Khi thêm cột Excel, cập nhật schema, template và fixture nhập lại cùng một thay đổi. Khi thêm kỳ, tạo snapshot có version và hash, kèm cấu hình quota riêng. Giữ mã nguồn, mẫu tổng hợp, artifact nội bộ và dữ liệu vận hành ở các vị trí riêng để dễ sao lưu và phục hồi theo kỳ.

| Thứ tự | Việc triển khai | Kiểm tra trước khi sang bước tiếp |
|---|---|---|
| 1 | Khóa contract cohort, model registry, quota, quyền và dữ liệu tổng hợp | Kiểm tra hash model, đủ giảng viên theo snapshot, kiểm thử truy cập trái quyền |
| 2 | Trang chủ, điều hướng và import Excel | Responsive, bàn phím, xem trước, import lại Excel đã chuẩn hóa |
| 3 | Phân công, nhánh thiếu ý tưởng và bảng kết quả | Chạy đủ 5 thuật toán, 6 checkpoint, kiểm tra quota và tái lập bằng seed |
| 4 | Biểu đồ và phát lại 3D/2D | Số liệu khớp bảng, trace phát lại đúng, đo hiệu năng và chế độ giảm chuyển động |
| 5 | RAG có trích dẫn và giới hạn quyền | Hỏi có nguồn, thiếu nguồn, dữ liệu khác kỳ và truy vấn chèn chỉ dẫn |
| 6 | AI agent tùy chọn | Tool chỉ truy cập dữ liệu đúng quyền, thao tác được ghi audit |

**Nghiệm thu cuối.** Dùng ít nhất một workbook chỉ có tên, một workbook trộn sinh viên có và chưa có ý tưởng, một workbook lỗi, một kỳ thiếu quota và một kỳ dùng đủ 17 giảng viên. Thêm ca nhóm có ý tưởng và nhóm chưa có ý tưởng cạnh tranh cho một suất duy nhất, cùng ca checkpoint sai contract. Kiểm tra truy cập trực tiếp vào run, trace, kết quả chưa công bố và export bằng tài khoản khách, sinh viên khác và điều phối viên khác kỳ. Thử truy vấn RAG chứa mã của sinh viên khác kỳ. Xác nhận export hợp lệ, biểu đồ khớp kết quả backend và trình phát 3D/2D đọc cùng trace. Ghi lại giới hạn, trình duyệt, cấu hình máy và snapshot dùng khi kiểm thử.

Các hướng dẫn đang phục vụ vận hành nằm ở [cài đặt portal](../operations/portal-setup.md) và [triển khai production](../operations/production-deployment.md).
