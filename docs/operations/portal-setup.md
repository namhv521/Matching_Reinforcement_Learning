# Thiết lập portal UniMatch

## Giao diện

`landing.html` là trang giới thiệu. Nút đăng nhập mở `login.html` và đưa người dùng trở về portal sau khi xác thực. `rebuild.html` chứa hồ sơ, lựa chọn giảng viên, so sánh, phát lại 3D và chatbot. `dashboard.html` đọc báo cáo huấn luyện đã lưu, chỉ hiện khi mã lần chạy khớp mô hình đang phục vụ.

Portal hỗ trợ nhập hồ sơ sinh viên bằng CSV hoặc Excel. Khi nạp danh mục Strict GitHub, màn hình phân công cho phép chọn V1–V3. Catalog hiện vẫn đọc từ bộ dữ liệu đã duyệt của backend; thay đổi database/catalog cần quy trình cập nhật dữ liệu và kiểm chứng mô hình hiện có. API intake giảng viên cũ được giữ cho công cụ vận hành, không xuất hiện trong luồng người dùng.

## Build và chạy local

Cần Python 3.12, Node.js 22 và bộ artifact Strict GitHub riêng. Từ thư mục gốc, cài phụ thuộc, build frontend và mở portal:

```powershell
python -m pip install -r requirements-rebuild-web.txt
npm --prefix frontend ci
npm --prefix frontend run build
python scripts/serve_unimatch_local.py --checkpoint-catalog
```

Mở `http://127.0.0.1:8767/landing.html`. Launcher đọc cấu hình OAuth từ `.env` nếu có, nạp các artifact đã kiểm tra trong `outputs/` và lưu dữ liệu thử tại `data_rebuild/runtime/strict_catalog/`. Callback OAuth local phải khớp origin của launcher. Danh mục chạy trên loopback với phạm vi nghiên cứu hồi cứu.

### Chạy bundle GitHub tháng 10

Lệnh sau dành cho trường hợp còn giữ đúng bundle và manifest lịch sử.

```powershell
npm --prefix frontend run build
$env:UNIMATCH_PUBLIC_ORIGIN = 'http://127.0.0.1:8768'
python scripts/serve_github_unimatch_local.py --bundle data_rebuild/github_rebuild/20261022T205450Z-5ddcb75a/training_bundle.json --selection data_rebuild/github_training/github_retraining_runs/20261022T205827Z-16010d68/selection_manifest.json --runtime data_rebuild/runtime/portal --port 8768
```

Mở `http://127.0.0.1:8768/login.html`. Entrypoint này vẫn chỉ bind loopback. Thay đổi giao diện không đồng nghĩa đã triển khai public.

## OAuth và giới hạn đăng nhập

Khai báo biến môi trường trước khi chạy Python hoặc dùng `.env` với launcher `--checkpoint-catalog`. Tên biến có trong `.env.example`.

- `UNIMATCH_PUBLIC_ORIGIN`: origin chính xác, gồm scheme và port nếu có.
- `UNIMATCH_GOOGLE_CLIENT_ID`, `UNIMATCH_GOOGLE_CLIENT_SECRET`.
- `UNIMATCH_GITHUB_CLIENT_ID`, `UNIMATCH_GITHUB_CLIENT_SECRET`.
- `UNIMATCH_FACEBOOK_CLIENT_ID`, `UNIMATCH_FACEBOOK_CLIENT_SECRET`.
- `UNIMATCH_AUTH_START_RATE_LIMIT` (mặc định `10`) và `UNIMATCH_AUTH_START_RATE_WINDOW_SECONDS` (mặc định `60`) giới hạn số lần bắt đầu OAuth theo IP kết nối trực tiếp.

Đăng ký callback tại từng provider: `<origin>/api/auth/callback/google`, `<origin>/api/auth/callback/github`, `<origin>/api/auth/callback/facebook`. Không đưa client secret vào frontend. Endpoint bắt đầu OAuth được giới hạn theo IP và bảo vệ bởi kiểm tra same-origin; limiter trong tiến trình phù hợp cho một instance/worker. Khi chạy nhiều instance hoặc worker, thay bằng Redis hay rate limit tại reverse proxy. Với Facebook, implementation sử dụng Graph API v23.0; cần kiểm tra cấu hình/quyền ứng dụng thực tế khi kích hoạt.

Đăng ký và đăng nhập cùng dùng danh tính provider; lần đầu tạo user trong SQLite, các lần sau dùng lại đúng provider/subject. Không tự nối tài khoản theo email. OAuth state có thời hạn năm phút, dùng một lần và được ràng buộc với cookie trình duyệt. Google/GitHub dùng PKCE. Provider access token chỉ dùng phía backend để lấy danh tính, không gửi tới browser hoặc lưu vào SQLite.

Phiên UniMatch dùng cookie HttpOnly, SameSite=Lax, thời hạn tám giờ; Secure khi origin là HTTPS. SQLite mặc định ở `data_rebuild/runtime/portal.sqlite3`, ngoài thư mục frontend. Có thể đổi bằng `UNIMATCH_AUTH_DB`. Phiên được băm trong DB; scope hồ sơ/kết quả gắn với user. Bearer token cũ chỉ còn dành cho script vận hành. Khi thiếu cấu hình, nút provider bị khóa và giao diện nói rõ lý do; không có đăng nhập giả.

Tham khảo: [Google server OAuth](https://developers.google.com/identity/protocols/oauth2/web-server), [GitHub OAuth](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps), [Facebook manual login](https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow/).

## Báo cáo và trợ lý

Production đọc báo cáo đã lưu từ gói mô hình đang phục vụ. Trợ lý tra cứu hồ sơ giảng viên và các đoạn tài liệu có nguồn.

### Ghi chú về bundle tháng 10

Dashboard đọc `docs/validation/github_retraining_numeric_20261023.json`. Đây là snapshot của experiment, không phải live worker; nút cập nhật đọc lại snapshot. Báo cáo hiện có năm seed, 131.072 bước mỗi thuật toán/seed; mốc chọn PPO 131.072 và DQN 98.304. Cả hai chưa đạt tiêu chí plateau trong ba lần đánh giá cuối. Chưa đánh giá test hoặc promote production. Không hiển thị phần trăm “độ hoàn thiện”.

Chatbot là hội thoại tra cứu theo quy tắc và nguồn đã duyệt, không gọi LLM. Tra cứu toàn danh mục độc lập với roster phân bổ. `CV` được mở rộng thành `computer vision` chỉ ở truy vấn, không đổi taxonomy/encoder đã train. Nguồn GitHub khớp concept nhưng chưa có điểm encoder vẫn xuất hiện, với điểm chưa biết thay vì điểm giả. Truy vấn CV hiện tìm được cả Nguyễn Hùng Việt và Nguyễn Hùng Thắng; NLP tìm được Nguyễn Hùng Thắng theo nguồn đã duyệt. Không gán NLP cho Nguyễn Hùng Việt khi nguồn đã duyệt chưa chứng minh concept đó. Chủ đề ngoài phạm vi bị từ chối.

### Kiểm chứng của bundle tháng 10

Kiểm tra API, security, assistant, OAuth giả lập và launcher: 65 passed, 1 skipped ở lượt kiểm tra cuối. Browser dùng danh tính QA tổng hợp tạo trực tiếp trong kho phiên để kiểm tra UI; không phải bằng chứng đăng nhập Google/GitHub/Facebook thật. OAuth cần client ID/secret thực và kiểm chứng nhà cung cấp trước khi sử dụng.

Smoke browser: nhập ba hồ sơ kiểm thử có đề tài tiếng Việt, chọn một giảng viên có dữ liệu phù hợp, chạy đủ ba thuật toán, xem trace ba bước, hỏi CV/NLP/câu ngoài phạm vi và xuất CSV. Kết quả trên ba hồ sơ này không phải benchmark chất lượng mô hình. Mẫu hoàn toàn ngoài vocabulary có thể không phân bổ được; UI giữ kết quả không khả thi.

Các asset 3D là hình học native được viết trong code, không cần tài khoản asset ngoài.

## Kiểm tra mã

```powershell
npm --prefix frontend run check
python -m pytest tests/rebuild -q
```
