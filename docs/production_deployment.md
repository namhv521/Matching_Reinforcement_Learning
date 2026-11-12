# UniMatch production: PostgreSQL + Render

## Kiến trúc

Repo deploy: `https://github.com/namhv521/UniMatch`, branch `main`.

- Render chạy Docker CPU gồm FastAPI và toàn bộ frontend; có thể truy cập cùng một origin để giữ cookie đơn giản.
- Neon PostgreSQL lưu trong schema riêng `unimatch_portal`: users, sessions, OAuth state, cohorts/runs, catalog giảng viên, metadata mô hình và gói model riêng.
- Nếu tách frontend sang Vercel, mọi `/api/*` phải proxy về **đúng Render service mới**, còn `UNIMATCH_PUBLIC_ORIGIN` phải là origin Vercel chính thức.
- Model PPO/DQN giữ nguyên bytes và contract đã kiểm chứng. Đưa ứng dụng lên production không đồng nghĩa các checkpoint nghiên cứu đã được xác nhận chất lượng phân công thực tế.

Schema additive nằm ở `database/portal.sql`; không thay đổi hoặc xóa bảng legacy trong `public`. PostgreSQL được dùng bắt buộc ở public entrypoint. Không dùng filesystem Render để lưu phiên/hồ sơ/kết quả, vì storage local có thể mất sau redeploy.

## Xuất và đưa gói riêng vào Neon

Trên máy có private artifact đã kiểm chứng:

```powershell
$env:DATABASE_URL = '<Neon PostgreSQL connection string, giữ TLS>'
python scripts/publish_unimatch_release.py --bundle data_rebuild/github_rebuild/20261022T205450Z-5ddcb75a/training_bundle.json --selection data_rebuild/github_training/github_retraining_runs/20261022T205827Z-16010d68/selection_manifest.json --publish-key github-20261023-v1
```

Lệnh kiểm tra bundle/checkpoint qua loader cũ, xuất archive tương đối dưới `data_rebuild/deployment/`, rồi lưu archive trong PostgreSQL. Ghi lại SHA-256 được in; không in/lưu connection string vào log hoặc Git. Mỗi key là immutable: cùng key mà bytes khác sẽ bị từ chối. Không sửa native checkpoint metadata để di chuyển máy; release riêng chứa các path tương đối và checksum gốc.

Gói xuất hiện tại có 370 file, khoảng 6,22 MB nén. Có dữ liệu riêng cho redaction/serving nên không commit archive lên GitHub và không phục vụ archive qua static route. Production tải từ SQL, kiểm tra SHA được pin ở environment, kiểm tra inventory/path/size, rồi nạp weights theo đúng model contract.

Để tạo gói sáu checkpoint PPO/DQN V1–V3 từ các lần chạy Strict GitHub:

```powershell
python scripts/publish_unimatch_release.py --semester-outputs outputs --release-name strict-github-20261112-v1 --output data_rebuild/deployment/strict-github-20261112-v1.tar.gz
python scripts/publish_unimatch_release.py --archive data_rebuild/deployment/strict-github-20261112-v1.tar.gz --publish-key strict-github-20261112-v1 --expected-sha256 '<SHA-256 của archive đã kiểm thử>'
```

Gói Strict chứa trọng số suy luận, bộ mã hóa, hồ sơ giảng viên và số liệu tổng hợp. Sau khi Neon có gói, đặt `UNIMATCH_MODEL_BUNDLE` và `UNIMATCH_MODEL_BUNDLE_SHA256` trên Render, rồi deploy commit hỗ trợ định dạng này. `/health` phải báo `checkpoint_count=6` cùng `checkpoint_versions=["V1","V2","V3"]`. Nếu cần quay lại model trước, khôi phục cặp biến key/SHA của bản cũ và deploy lại.

## Cấu hình Render

Dùng repo và branch trên, Dockerfile ở root, health `/health`; có thể dùng Blueprint `render.yaml`. Chọn tài nguyên sau khi đo bộ nhớ thực tế; tài liệu này không xác nhận một plan miễn phí đủ RAM cho torch.

Các biến bắt buộc:

```text
UNIMATCH_DEPLOYMENT=production
DATABASE_URL=<Neon TLS connection string>
UNIMATCH_PUBLIC_ORIGIN=<origin HTTPS thực tế>
UNIMATCH_MODEL_BUNDLE=github-20261023-v1
UNIMATCH_MODEL_BUNDLE_SHA256=<SHA-256 từ publish>
```

Thêm OAuth và giới hạn đăng nhập theo `docs/portal_setup.md`. Khi dùng origin Render trực tiếp, callback là `<render-origin>/api/auth/callback/{google|github|facebook}`. Khi dùng Vercel, callback OAuth chuyển sang origin Vercel. Không dùng tùy ý header proxy để quyết định origin OAuth.

Start command đã nằm trong Dockerfile: `uvicorn backend.app.production:create_app --factory`, bind `0.0.0.0`, port theo `PORT`, một worker. Production từ chối public bearer token cũ; chỉ chấp nhận cookie phiên, kiểm tra Origin cho POST. SQLite chỉ còn cho local/test.

## Nếu dùng Vercel

1. Root directory `frontend`, build `npm run build`, output `dist`.
2. Lấy URL Render từ kết quả deploy thật; cập nhật destination `/api/:path*` trong `frontend/vercel.json` thành `<render-origin>/api/:path*`.
3. Đặt `UNIMATCH_API_ORIGIN=<render-origin>` trên Vercel. Build kiểm tra origin HTTPS và rewrite khớp; thiếu/mismatch thì không phát hành frontend mới vào API cũ.
4. Đặt `UNIMATCH_PUBLIC_ORIGIN` trên Render bằng origin Vercel và cập nhật callback OAuth. Sau đó kiểm tra cookie, đăng xuất, import, compare/export và chat qua Vercel.

Rewrite cũ trong repository là dữ liệu lịch sử; không coi URL đó là backend mới đã được kiểm chứng.

## Kiểm chứng và rollback

- `/health` chỉ ready khi model đã tải và truy vấn PostgreSQL thành công; trả `storage=postgresql`, số giảng viên và checksum release.
- SQL kiểm tra trong schema `unimatch_portal`; không truy vấn hoặc in provider secrets.
- Đăng nhập OAuth thật; xác minh phiên còn hoạt động sau restart backend.
- Nhập CSV thực thuộc tài khoản được phép, chạy ba thuật toán; reload/redeploy rồi đọc lại run bằng đúng user scope. Tài khoản khác không truy cập cohort/run đó.
- Dashboard phải khớp selection run của model. Báo cáo là snapshot, chưa phải live training.
- Rollback dùng commit/image cũ và key/SHA release cũ; không xóa dữ liệu SQL, không thay checkpoint đằng sau cùng key.

CI chạy fixture PostgreSQL 16, suite hợp đồng, frontend check/build và build Docker CPU. Integration CI dùng database disposable riêng, không sử dụng Neon production. Local đã qua 484 tests, 3 skipped (gồm hai bài PostgreSQL cần database test riêng). Docker daemon local hiện không hoạt động; build Linux và PostgreSQL được giao cho CI để kiểm chứng độc lập.

## Trạng thái đã kiểm chứng ngày 23/10/2026

- Website: https://unimatch-portal.onrender.com, Render service `srv-dbdalafavr4c739d2gu0`, Docker Free tại Singapore; frontend và API cùng origin.
- Deployment `dep-dbdalanavr4c739d2in0` của commit `ff4f2ccaf5f3d79b91f72508fe69c435646f6a0b` đã báo Live. Chrome mở được trang đăng nhập, không ghi nhận lỗi console.
- `/health` trả `status=ready`, `storage=postgresql`, `data_loaded=true`, 35 giảng viên, mô hình `dqn` và `ppo`.
- Neon project `unimatch` (`patient-tree-18935199`), branch `production`, database `neondb`, schema `unimatch_portal`: 35 advisors, 1 catalog, 1 model bundle. Các bảng `public` cũ được giữ nguyên.
- Release `github-20261023-v1`: 6.220.361 bytes, SHA-256 `db88f3b2ebee91efdc4129699384b97657911a48379f9cba70aa57a9e0040ff5`; SQL và public health khớp nhau.
- [CI 39877003357](https://github.com/namhv521/UniMatch/actions/runs/39877003357) thành công: 486 tests passed, 1 skipped; gồm PostgreSQL 16 và Docker Linux.
- Google/GitHub/Facebook OAuth đang cấu hình, chưa có bằng chứng đăng nhập nhà cung cấp thật. Chưa xác nhận phiên/hồ sơ qua redeploy hoặc luồng so sánh trên production. Vercel chưa chuyển sang backend mới.
- Đã tạo GitHub OAuth app `3956407` (callback `/api/auth/callback/github`), Google Cloud project UniMatch `fit-visitor-512500-p9`, và Meta app UniMatch `1135265135823111` (miền production, hạng mục Giáo dục). GitHub/Meta yêu cầu chủ tài khoản tự xác minh để lấy secret; Google còn chấp nhận User Data Policy. Meta còn yêu cầu chính sách riêng tư, hướng dẫn xóa dữ liệu, icon, xác minh doanh nghiệp và xét duyệt trước khi phát hành.

Đưa ứng dụng lên public không phải chứng nhận chất lượng checkpoint: health vẫn ghi `research_models=true`, `production_promoted=false`.

Nguồn: [Render Docker](https://render.com/docs/docker), [Render filesystem/persistent storage](https://render.com/docs/free), [Vercel external rewrites](https://vercel.com/docs/routing/rewrites), [Neon Python connection](https://neon.com/docs/guides/python).
