# Hướng dẫn chạy và train RL hai cấp

Ngày cập nhật: 01/11/2026. Workspace: `C:\Su\KLTNv2\KLTN`.

Tài liệu này mô tả lần rebuild theo `docs/research/rl/summary.md` và yêu cầu mỗi round ít nhất 100.000 step. Hướng dẫn được tạo trước khi chạy huấn luyện. Các lệnh dưới đây sẽ được kiểm tra trên chính workspace trước khi bàn giao.

## 1. Thiết kế thực thi

Tái sử dụng môi trường phân công, PPO, bộ kiểm tra checkpoint và cơ chế giữ model accepted hiện có. Bổ sung adapter đọc CSV theo kỳ; không tái tạo thuật toán RL hoặc tạo một stack ML khác.

| Version | Cohort sinh viên | Cutoff | Nguồn trọng số |
|---|---|---|---|
| V1 | Pool `2024` | 31/08/2025 | Khởi tạo ngẫu nhiên, không dùng checkpoint cũ |
| V2 | `2025.1` | 31/12/2025 | Checkpoint accepted gần nhất từ V1 |
| V3 | `2025.2` | 31/05/2026 | Checkpoint accepted gần nhất từ V2 hoặc model được giữ lại |
| Test ngoài | `2025.3` | 31/08/2026 | Chỉ đánh giá sau khi đóng băng lựa chọn cuối |

Cấp ngoài là kế thừa giữa các version. Cấp trong là học tiếp qua các round của cùng cohort. PPO là thuật toán chính của lần chạy này; Hungarian, Greedy và Random là baseline, không phải hai cấp RL.

## 2. Dữ liệu và giới hạn sử dụng

- Danh sách thí nghiệm gồm 17 giảng viên từ `data/2024/advisors/faculty_profiles/advisors_profile.csv`. Giữ cố định thứ tự advisor_id giữa mọi checkpoint.
- Khóa luận hoàn thành và skill trích từ tài liệu là `retrospective_document_proxy`, không phải bằng chứng kỹ năng có sẵn ở đầu kỳ.
- Nội dung giảng viên mới crawl không được tự coi là snapshot web đã tồn tại trong quá khứ. Ngày công bố, thời điểm khả dụng và thời điểm crawl được lưu riêng.
- Corpus của từng kỳ chứa phần bổ sung; snapshot processed được kế thừa tích luỹ, không đếm lại công trình cũ thành công trình mới.
- Các mục thiếu tháng hoặc có ngày mâu thuẫn nằm trong danh sách chờ. Không ép bài chỉ ghi năm 2025 vào một học kỳ cụ thể.
- Metadata GitHub được gắn ngày tạo repository; đây không phải ngày công bố bài báo hoặc bằng chứng repository đã công khai vào thời điểm đó.
- Scholar/ResearchGate bị chặn được ghi nhận đúng trạng thái. Không dùng CAPTCHA/login bypass và không coi bị chặn là không có công trình.
- Giảng viên thực tế ghi trên khóa luận không được biến thành nguyện vọng sinh viên hoặc phản hồi nhận/từ chối.

Không đổi dữ liệu nguồn thành approved chỉ để chạy model. Thí nghiệm trên proxy phải giữ nhãn proxy trong input, checkpoint, báo cáo và giao diện.

## 3. Các round và ngân sách

| Round | Tín hiệu | Cách kế thừa | Ngân sách mặc định |
|---|---|---|---:|
| R1 | Hồ sơ, chuyên môn, chỉ tiêu | V1 khởi tạo; V2/V3 kế thừa accepted | 131.072 step |
| R2 | Lựa chọn của một phần sinh viên | Kế thừa accepted và ngữ cảnh R1 | 131.072 step |
| R3 | Nhận/từ chối của giảng viên theo từng yêu cầu | Kế thừa accepted và ngữ cảnh R2 | 131.072 step |
| R4 nếu được giữ trong protocol | Train tiếp, không thêm tín hiệu | Giữ đầu vào R3; ghi rõ optimization-only | 131.072 step |

Protocol hiện giữ bốn round theo tài liệu RL hai cấp: 524.288 step/version, tổng ba version là 1.572.864 step cho PPO. CLI cũng hỗ trợ protocol ba round nếu khởi tạo một lượt mới; không thay số round ngầm trong protocol đang chạy.

CLI của lượt train chính phải từ chối ngân sách nhỏ hơn 100.000. Bài kiểm tra kỹ thuật có thể chạy ít step trong thư mục test riêng; không được đưa vào báo cáo như lượt train chính.

`steps_added` là bước thực chạy của candidate. `steps_after` thuộc checkpoint candidate. Nếu candidate bị loại, compute đã tiêu vẫn được báo cáo nhưng không cộng vào bộ đếm của checkpoint được giữ. Không hứa bộ đếm accepted bằng tổng compute khi có round bị loại.

## 4. Chỉ tiêu và phản hồi

Người dùng đã chọn **chia đều cho tất cả 17 giảng viên tham gia**. Với một cohort N sinh viên, tổng chỉ tiêu bằng N; từng giảng viên nhận floor(N/17) hoặc ceil(N/17), thứ tự advisor_id cố định quyết định phần dư. Train/validation/test là các episode riêng, nên chỉ tiêu được tính theo kích thước từng cohort, không cộng số chỗ của các tập lại.

Phản hồi dùng file khảo sát thật. Không tạo phản hồi mô phỏng. Các khả năng khác dưới đây chỉ mô tả cách xử lý nếu sau này được yêu cầu:

1. Dữ liệu thật: import tín hiệu có nguồn, chỉ cập nhật các cặp đã có thông tin. Theo yêu cầu đã chốt, thiếu thông tin thì bỏ qua tín hiệu và vẫn train tiếp cùng cohort.
2. Thí nghiệm mô phỏng, chỉ khi được cho phép: dùng chỉ tiêu cân bằng và tạo lựa chọn/nhận-từ chối có seed cố định. Mọi record và báo cáo ghi `simulated_feedback_not_human`. Không ghi trở lại CSV nguồn như dữ liệu thật.

Từ chối chỉ chặn cặp được yêu cầu, không loại sinh viên khỏi cohort. Nhận nghĩa là cho phép xét cặp, không tự khóa phân công cuối. Sinh viên chưa chọn giữ preference unknown. Validation và test không được tạo feedback mô phỏng.

## 5. Feature và chống rò rỉ

Encoder văn bản chỉ fit trên sinh viên train V1. Từ vựng/IDF và thứ tự feature được đóng băng để dùng cho V2, V3 và test. Văn bản sử dụng tiêu đề, nội dung mô tả và các tag có bằng chứng; loại định danh cá nhân khỏi đặc trưng tương đồng.

Skill là dấu hiệu xuất hiện trong tài liệu, không phải mức thành thạo. Trường chưa biết phải có mask; không diễn giải giá trị lưu 0 thành đã xác nhận không có kỹ năng.

Chia train/validation theo student_id nhất quán qua các kỳ. MSSV xuất hiện nhiều kỳ luôn giữ cùng membership; không dùng người đã train ở kỳ trước làm validation ở kỳ sau. Không fit encoder, chỉnh reward, chọn checkpoint hoặc ngưỡng theo `2025.3`.

Giữ reward native của môi trường: score 1.0, preference 0.1, fairness 0.15, terminal completion 1.0. Utility là mục tiêu của môi trường; không gọi utility là accuracy hoặc chất lượng học thuật thực.

## 6. Chuẩn bị môi trường

Mở PowerShell tại workspace:

```powershell
Set-Location C:\Su\KLTNv2\KLTN
$env:PYTHONIOENCODING = 'utf-8'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
python -X utf8 -c "import torch, gymnasium, sklearn, sb3_contrib; print(torch.__version__)"
```

Dùng dependency hiện có trong repository. Không cần cloud, Docker hoặc GPU để chạy PPO CPU hiện tại. Bộ ML nằm trong `requirements-rebuild-rl.txt`; bộ API nằm trong `requirements-rebuild-web.txt`.

## 7. Quy trình chạy

Chuẩn bị suite từ snapshot đã kiểm tra. `--quota-policy equal` thực hiện yêu cầu chia đều cho 17 giảng viên; đây là chính sách do người dùng chọn, không phải chỉ tiêu tổ chức đã quan sát:

```powershell
python -X utf8 scripts/run_semester_rl.py prepare --inputs data/training_prepared_20261101 --output outputs/semester_rl_20261101/suites --quota-policy equal
```

Chạy V1/R1 từ khởi tạo mới, thêm 131.072 step. Lệnh dừng sau R1 để không tự tạo phản hồi cho các round sau:

```powershell
python -X utf8 scripts/run_semester_rl.py train --suites outputs/semester_rl_20261101/suites --output outputs/semester_rl_20261101/training --rounds 4 --timesteps 131072 --stop-after V1-R1
```

Lệnh train đọc protocol đã ghi khi resume; nếu đổi ngân sách, seed hoặc số round phải xử lý như thay đổi protocol, không âm thầm đổi một lượt đang có. Resume bỏ qua round đã hoàn tất chỉ sau khi xác minh hash, ngân sách và input. Thư mục round bị ngắt giữa chừng phải được giữ để rà soát, không tự ghi đè.

Khảo sát gốc là XLSX, không phải CSV. Lọc cột B sau chuẩn hoá khoảng trắng/Unicode, chỉ nhận `Đăng ký làm Đề án, Đăng ký Khoá luận tốt nghiệp` và `Đăng ký Khoá luận tốt nghiệp`. Đối chiếu cột D với MSSV, ưu tiên G/J/K tạo lựa chọn R2; cột I tạo hồ sơ trạng thái đăng ký R3. Giữ số dòng, worksheet, timestamp và hash XLSX. Không đưa phone/email vào feature.

**Quy tắc người dùng chốt ngày 01/11/2026:** chỉ MSSV có thông tin mới tạo tín hiệu tương ứng. Không có MSSV hoặc thiếu thông tin R2/R3 thì bỏ qua tín hiệu, không loại sinh viên khỏi cohort và không suy thành từ chối. Khi một round không có tín hiệu mới, vẫn chạy đủ ngân sách với đầu vào giữ nguyên và ghi `optimization_only`. Không tạo dữ liệu mô phỏng để lấp chỗ trống. Đối chiếu dựa trên MSSV; nhãn kỳ khai trên phiếu nếu mâu thuẫn chỉ được ghi audit, không tự loại thông tin khớp MSSV. Timestamp sau cutoff và dữ liệu holdout vẫn không được đưa vào training.

`Chưa đăng ký` không chứng minh giảng viên từ chối; `Đã đăng ký thành công` không tự khóa phân công hoặc chứng minh chấp nhận ưu tiên 1 nếu không có xác nhận cặp. R3 phải ghi rõ tác động thực lên đầu vào; receipt không đổi ràng buộc thì là train tiếp có bằng chứng trạng thái, không được báo thành đã học từ quyết định nhận/từ chối.

Không lấy khảo sát 2025–2026 làm phản hồi lịch sử của V1/2024. Theo yêu cầu mới, round không có phản hồi phù hợp vẫn chạy đủ ngân sách như optimization-only.

Import khảo sát bằng Python bundled có sẵn thư viện đọc XLSX, không sửa workbook:

```powershell
& "$env:USERPROFILE/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe" -X utf8 scripts/import_registration_survey.py --source "data/Khảo sát Đăng ký làm chuyên đề, thực tập tốt nghiệp (Responses).xlsx" --output data/registration_survey_20261101.json
python -X utf8 scripts/run_semester_rl.py feedback --suites outputs/semester_rl_20261101/suites --survey data/registration_survey_20261101.json --inputs data/training_prepared_20261101 --output outputs/semester_rl_20261101/survey_feedback_mssv --allow-empty-optimization
```

Exporter giữ cả dòng có MSSV sai định dạng trong audit và không tự sửa số. Chọn bản gửi mới nhất trước cutoff cho mỗi MSSV trong train. Không đưa preference của validation/test vào round train. Mâu thuẫn nhãn kỳ được giữ trong audit; đối chiếu tín hiệu theo MSSV như người dùng yêu cầu, không tự di chuyển khóa luận hoặc đổi cohort.

Ưu tiên 1/2/3 được chuyển thành trọng số 1, 2/3, 1/3 như quy tắc của hệ thống, không phải điểm sinh viên tự chấm. Tên giảng viên không thuộc roster 17 người được báo riêng, không tự đổi người. Các ưu tiên lặp cùng giảng viên chỉ giữ mức ưu tiên cao nhất.

Chạy tiếp toàn bộ chuỗi sau khi readiness feedback sẵn sàng:

```powershell
python -X utf8 scripts/run_semester_rl.py audit-sources --suites outputs/semester_rl_20261101/suites --inputs data/training_prepared_20261101 --output outputs/semester_rl_20261101/source_audit.json
python -X utf8 scripts/run_semester_rl.py train --suites outputs/semester_rl_20261101/suites --feedback outputs/semester_rl_20261101/survey_feedback_mssv --source-audit outputs/semester_rl_20261101/source_audit.json --output outputs/semester_rl_20261101/training --rounds 4 --timesteps 131072
```

Cờ `--allow-empty-optimization` thực hiện quy tắc bỏ qua tín hiệu thiếu do người dùng vừa chốt. Không tạo mock. Output đã tồn tại là immutable; khi đổi quy tắc phải chọn output mới. R2/R3 không có thông tin được gắn `optimization_only`.

`audit-sources` đối chiếu lại ma trận tương đồng với corpus và encoder đóng băng, kiểm tra hash nguồn raw rồi tạo receipt mới. Receipt không sửa checkpoint R1 hoặc giả nhận hash đã được ghi trước đó. Lượt train tiếp pin hash receipt trong `source_binding.json`; thay corpus sau khi pin sẽ bị từ chối. Các lần chuẩn bị suite mới tự ghi hash corpus và bản ghi được chọn vào manifest.

Sau khi toàn bộ round hoàn tất và selection đã đóng băng, đánh giá test ngoài:

```powershell
python -X utf8 scripts/run_semester_rl.py evaluate --suites outputs/semester_rl_20261101/suites --training outputs/semester_rl_20261101/training
```

Lệnh này từ chối chạy nếu thiếu round hoặc round chưa đủ 100.000 step. Thư mục `training/final_test/` được tạo độc quyền trước khi mở test; kể cả lần mở bị ngắt cũng không tự thử lại. Không xoá marker để lấy thêm lượt test trong cùng protocol.

Theo dõi trực tiếp một round đang chạy:

```powershell
Get-Content outputs/semester_rl_20261101/training/V1/R1/learning_curve.jsonl -Tail 1
Get-Content outputs/semester_rl_20261101/training/status.json
```

Curve có dòng mới mỗi 8.192 step; bước 0 là baseline trước train. `status.json` cập nhật sau khi một round đóng gói và xác minh xong. Không coi thư mục checkpoint chưa có manifest hoàn chỉnh là model sẵn sàng.

Thứ tự bắt buộc:

1. Crawl URL công khai; lưu raw bytes, hash, trạng thái và bằng chứng ngày.
2. Phân corpus theo kỳ, giữ unresolved riêng; tạo snapshot 17 giảng viên.
3. Kiểm tra nguồn và chia membership; đóng băng encoder và input.
4. Kiểm tra suite R1, tín hiệu R2/R3, cohort, mask, quota và hash.
5. Train từng round >=100.000 step; lưu checkpoint và đánh giá validation định kỳ.
6. So candidate/parent trên cùng validation và holdout các kỳ cũ. Giữ model accepted; candidate bị loại không thành nguồn trọng số.
7. Hoàn tất V1, V2, V3; đóng băng lựa chọn cuối và hash.
8. Mở test ngoài một lần; báo kết quả PPO và baseline, không quay lại tune theo test.
9. Kết nối model và dữ liệu mới vào web, kiểm tra inference thật và trạng thái thí nghiệm.

## 8. Kiểm tra checkpoint và kết quả

### Lượt đã hoàn tất ngày 01/11/2026

V1/2024 R1 đã chạy thật: bắt đầu từ 0, thêm 131.072 step, kết thúc ở 131.072 step. Không có parent checkpoint. Native gate chấp nhận checkpoint trong phạm vi nghiên cứu; reload và inference parity đều đạt. Thời gian train đo được khoảng 732,46 giây trên CPU hiện tại.

Artifact: `outputs/semester_rl_20261101/training/V1/R1/`. Báo cáo nằm trong `report.json`; hash và kiểm kê nằm trong `manifest.json`. Utility validation cuối là khoảng 0,099553/sinh viên, thấp hơn Hungarian khoảng 0,145377 trên cùng validation. Đây chưa phải kết quả của toàn bộ V1 và chưa phải kết quả test.

Khảo sát có 163 dòng đúng điều kiện loại đăng ký, 148 MSSV phân biệt. Có một MSSV chỉ 7 chữ số được giữ ở audit, không sửa tự động. Theo quy tắc đối chiếu MSSV đã chốt, V1 có 0, V2 có 1 và V3 có 20 sinh viên train có thông tin khảo sát. Nhãn kỳ khác của dòng V2 được ghi audit, không loại thông tin khớp MSSV. Các dòng vắng hoặc thiếu giá trị không tạo tín hiệu; toàn bộ cohort vẫn giữ nguyên.

Đã hoàn tất cả 12 round V1–V3, mỗi round thêm 131.072 step, tổng compute 1.572.864 step. Mỗi version chạy 524.288 step. Cả 11 round kế thừa đều xác nhận trọng số khởi đầu bằng checkpoint parent. Các candidate sau bootstrap không qua gate; checkpoint cuối được giữ là V1/R1 với bộ đếm trọng số 131.072 step. Không cộng compute của candidate bị loại vào trọng số được giữ. V3 có cải thiện trên validation mới nhưng không đạt điều kiện giữ chất lượng trên các cohort cũ; không điều chỉnh gate sau khi xem kết quả.

Test 2025.3 đã được mở đúng một lần sau freeze, gồm 20 sinh viên. Kết quả utility/sinh viên:

| Phương pháp | Utility/sinh viên | Bao phủ | Vi phạm |
|---|---:|---:|---:|
| PPO | 0,092261 | 100% | 0 |
| Hungarian | 0,127053 | 100% | 0 |
| Greedy | 0,118207 | 100% | 0 |
| Random | 0,079025 | 100% | 0 |

PPO thấp hơn Hungarian trên mục tiêu hiện tại; kết quả không chứng minh RL tốt hơn baseline hoặc chất lượng hướng dẫn thực tế. Lượt này có một seed và dữ liệu proxy hồi cứu, chưa được promote production. Không dùng kết quả test này để train lại hoặc chọn checkpoint trong cùng protocol.

Web local đã nối checkpoint accepted và telemetry thật. Đã kiểm tra dashboard desktop/mobile, không tràn ngang toàn trang; upload CSV ba sinh viên thuộc train, chọn 17 giảng viên, chia quota và so sánh phân bổ chạy thành công. PPO bao phủ 100%, không có hành động sai; DQN báo chưa khả dụng vì chưa train. Kiểm tra trình duyệt dùng phiên QA local, không phải bằng chứng đăng nhập OAuth bên ngoài. Kết quả nằm ở `outputs/semester_rl_20261101/qa/browser-result.json`; test ngoài ở `training/final_test/results.json`.

Upload chế độ semester chấp nhận confidence để trống khi có loại bằng chứng `inferred_from_thesis` và tham chiếu nguồn. Giá trị này vẫn chưa biết, không tự điền số; tag sai taxonomy, thiếu bằng chứng hoặc confidence sai định dạng vẫn bị từ chối. Hợp đồng upload cũ giữ mặc định nghiêm ngặt.

Mỗi round phải có input snapshot, contract/feature hash, model, optimizer, bộ đếm, provenance, learning curve, report, decision và manifest. Khi kế thừa, kiểm tra trọng số ban đầu bằng parent, optimizer/counter được mang sang và advisor registry/feature dimension không đổi.

Learning curve được lấy mỗi 8.192 step; checkpoint selection là final-only. Không chọn điểm đẹp nhất trên curve rồi gọi đó là protocol đã chốt. Candidate được giữ theo ngưỡng khai báo trước trong protocol và kiểm tra forgetting, không theo kết quả test ngoài.

Nếu bootstrap không có model hợp lệ, dừng chuỗi thay vì lấy checkpoint sai contract. Nếu round sau bị loại, ghi retention với trọng số accepted và ngữ cảnh round đã thử, rồi tiếp tục đúng thứ tự.

## 9. Kế hoạch thực thi và kiểm tra

### Chạy web local sau train và test

```powershell
npm --prefix frontend run check
npm --prefix frontend run build
python -X utf8 scripts/serve_unimatch_local.py --semester-run outputs/semester_rl_20261101 --semester-inputs data/training_prepared_20261101 --port 8767
```

Mở `http://127.0.0.1:8767/login.html`, sau đó vào workspace hoặc dashboard. Launcher đọc `.env` để dùng cấu hình OAuth hiện có; biến đã có trong process được ưu tiên. Cấu hình callback phía nhà cung cấp OAuth vẫn phải khớp origin local, không được suy thành đã kiểm thử đăng nhập bên ngoài chỉ vì biến cấu hình có mặt.

Runtime, SQLite phiên đăng nhập và token API của lượt này nằm trong `outputs/semester_rl_20261101/runtime/`. Token không in ra terminal; chỉ in đường dẫn file riêng. Không đưa token vào URL hoặc commit.

API giữ các route `/api/rebuild/bootstrap`, `students/validate`, `quotas`, `recommend`, `compare`, export và training. PPO nạp từ checkpoint accepted đã đóng băng; DQN không có artifact trong lượt này thì báo unavailable. Encoder và thứ tự feature được giữ nguyên, upload không fit/train lại model. Chỉ tiêu chia đều dùng cùng hàm native lúc train và inference.

Build là bắt buộc: backend ưu tiên `frontend/dist` nếu tồn tại. Chỉ sửa source mà không build sẽ vẫn phục vụ dashboard cũ. Dashboard mới đọc telemetry của đúng run, phân biệt compute với bộ đếm trọng số, không dùng dữ liệu mock hoặc số liệu CI từ thí nghiệm cũ.

- [x] Hoàn tất crawl mọi URL trong danh bạ, kể cả trạng thái blocked.
- [x] Kiểm thử adapter CSV, cutoff bootstrap 2024, membership và encoder train-only.
- [x] Cập nhật engine để hỗ trợ lịch mới, giữ tương thích protocol cũ và kiểm tra hash.
- [x] Chuẩn bị suite, chỉ tiêu và feedback theo chế độ được xác nhận.
- [x] Cập nhật lệnh CLI tại mục 7; chạy preflight và kiểm tra reload/inference.
- [x] Train đủ ngân sách V1–V3, lưu retention và báo cáo từng round.
- [x] Đánh giá test ngoài sau freeze.
- [x] Sửa đường dẫn runtime/API và web để đọc artifact mới; kiểm tra frontend build và luồng API.

Không commit/push dữ liệu, checkpoint hoặc token truy cập. Đầu ra ML nằm local, được tách khỏi source frontend/backend.
