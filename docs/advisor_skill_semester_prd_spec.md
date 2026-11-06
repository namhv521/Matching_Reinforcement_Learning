# PRD & Technical Specification: Hồ sơ kỹ năng giảng viên và RL hai cấp theo học kỳ

Ngày: 02/11/2026. Phiên bản: 1.3. Trạng thái: crawler đang được triển khai theo phạm vi cập nhật bên dưới; chưa thay mô hình. Bản 1.3 áp dụng profile=40% dự đoán+60% bằng chứng; GVHD=trung bình các KLTN hợp lệ có sử dụng skill đang xét; final=50% profile+50% GVHD.

> Cập nhật phạm vi triển khai 05/11/2026: đợt crawl hiện hành chỉ lấy dữ liệu giảng viên có **năm sự kiện đến hết 2024**, bao gồm 2024 và các năm trước. Ưu tiên kiểm tra riêng năm 2024 rồi mở rộng ngược về các năm cũ. Chưa xử lý các kỳ/năm từ 2025 trở đi. `data/2024` là pool V1 cũ có cả dữ liệu 2025, nên không được dùng tên thư mục làm bộ lọc thời gian. Artifact độc lập và tiến độ tại `outputs/advisor_history_through_2024/README.md`. Các công thức điểm và protocol RL bên dưới là đặc tả cho giai đoạn sau; chưa chấm điểm hay train từ đợt crawl này.

## 1. Mục tiêu và phạm vi tài liệu

Xây dựng pipeline từ danh bạ giảng viên đến hồ sơ kỹ năng có bằng chứng, bổ sung kinh nghiệm hướng dẫn từ KLTN sinh viên, rồi tạo snapshot theo học kỳ cho UniMatch. Cấp ngoài là continual RL qua học kỳ; cấp trong cập nhật learner theo phản hồi hợp lệ trong cùng học kỳ.

Đầu vào gốc: `data/2024/advisors/faculty_profiles/advisors_profile.csv`. Các cột hiện có: `advisor_id`, `name`, `university_url`, `scholar_url`, `researchgate_url`, `github_url`. Kiểm tra tại ngày lập tài liệu: 17 giảng viên. Đây là danh bạ khởi đầu, không phải bằng chứng đầy đủ về công bố, quyền sở hữu tài khoản hoặc năng lực.

“Tất cả thông tin” được hiểu là toàn bộ mục chuyên môn công khai tìm thấy trong phạm vi nguồn đã khai báo và ngân sách crawl. Không thể bảo đảm thu được toàn bộ hoạt động khoa học của một người. Phải báo coverage, nguồn bị chặn, nội dung thiếu và phần chưa xác minh.

Hai nghĩa của skill được tách rõ:

- **Skill chuyên môn:** Python, SQL, NLP, tối ưu hóa, phương pháp nghiên cứu… Đây là đối tượng trích xuất và chấm điểm.
- **Skill của agent:** Brainstorming, MLE Workflow, Ponytail… Đây là hướng dẫn thực hiện dự án; không phải kỹ năng hay điểm của giảng viên.

Tài liệu này là đặc tả bổ sung chuyên sâu cho `PRD.md` và `SPEC.md`. Không thay thế các file đó, không thay đổi frontend, API, dữ liệu nguồn hoặc checkpoint hiện có.

## 2. Bối cảnh đã kiểm tra trong repository

| Nguồn sở hữu | Nội dung cần tái sử dụng |
|---|---|
| `data/AGENTS.md` | Cấu trúc nguồn, phân kỳ, provenance, mẫu CSV sinh viên 40 cột, external test |
| `configs/data/taxonomy_v1.yaml` | Taxonomy chuyên môn và alias hiện có |
| `src/data_pipeline/normalization.py` | Đối sánh thuật ngữ và offset bằng chứng |
| `src/features/semester_suite.py` | V1/V2/V3, snapshot cohort, encoder train-only, phạm vi proxy |
| `src/data_pipeline/semester_snapshots.py` | Kiểm tra artifact, hash, assignment/outcome provenance |
| `src/rl/nested_learning.py` | Vòng học, lineage và retention |
| `src/rl/semester_learning.py` | Temporal split, kiểm tra forgetting, tiếp tục PPO |
| `docs/rl_2_cap_training_guide.md` | Protocol hiện hành và giới hạn thí nghiệm đã báo cáo |

Đã phát hiện `src/data_pipeline/semester_versions.py` còn ánh xạ V1–V4 khác lịch trong `data/AGENTS.md` và `semester_suite.py`. Implementation mới phải khai báo `protocol_id`, kiểm tra lịch của mọi caller, rồi hợp nhất theo protocol đã chọn. Không âm thầm thay lịch của artifact cũ.

Training guide hiện báo PPO chưa vượt Hungarian trong lần đánh giá proxy trước. Đặc tả này không khẳng định enrichment hoặc RL sẽ cải thiện chất lượng hướng dẫn thực tế. Cần thí nghiệm mới theo các gate bên dưới.

## 3. PRD: Bài toán và người dùng

### 3.1. Vấn đề cần giải quyết

Hồ sơ giới thiệu thường ngắn; bài báo và repo phân tán; từ khóa không thể hiện cách áp dụng. Đếm số bài hoặc số lần xuất hiện công nghệ tạo điểm thiếu tin cậy. KLTN có thể bổ sung bằng chứng kinh nghiệm hướng dẫn, nhưng dễ gán nhầm người và rò rỉ thông tin từ cuối kỳ về đầu kỳ.

Kết quả mong muốn là một vector điểm theo skill, kèm nguồn, cách dùng, thời điểm, phần điểm độc lập và phần điểm từ hướng dẫn. Vector được sử dụng trong matching có quota và eligibility, không thành bảng xếp hạng chất lượng con người.

### 3.2. Người dùng và trách nhiệm

| Vai trò | Nhu cầu | Quyền quyết định |
|---|---|---|
| Người quản trị dữ liệu | Crawl, rà định danh, xử lý trùng và ngày thiếu | Duyệt bằng chứng; không tự duyệt thay giảng viên |
| Giảng viên | Xem, bổ sung, phản biện liên kết và skill | Xác nhận hồ sơ, phản hồi cặp phân công |
| Điều phối viên | So sánh phương án, quota, nguồn giải thích | Duyệt phân công và sửa ràng buộc có audit |
| Sinh viên | Đối chiếu kỹ năng/nhu cầu đề tài với advisor | Cung cấp nguyện vọng và phản hồi |
| Người nghiên cứu | Tái lập experiment, kiểm tra leakage và forgetting | Khóa protocol, đánh giá candidate |

### 3.3. Luồng sản phẩm chính

1. Import danh bạ, giữ stable `advisor_id`, kiểm tra URL và định danh.
2. Thu thập hồ sơ, danh mục công bố, nội dung bài báo được phép truy cập, đề tài và repo liên quan.
3. Khi crawl trực tiếp thất bại, điều khiển Chrome để thu nội dung truy cập được. Nếu chỉ có tên đề tài, dự đoán tối giản skill/framework và gắn nhãn suy luận; nếu có toàn văn, đọc toàn bộ nội dung rồi trích claim kỹ năng với bằng chứng.
4. Tính điểm kỹ năng độc lập cho từng giảng viên trước khi sử dụng KLTN sinh viên.
5. Trích kỹ năng KLTN, xác minh liên kết hướng dẫn, tính điểm bổ sung theo từng skill.
6. Đóng snapshot theo cutoff; tạo ma trận tương thích sinh viên–giảng viên và baseline.
7. Train/evaluate vòng trong; chuyển học kỳ bằng checkpoint accepted gần nhất.
8. Cung cấp báo cáo nguồn, điểm, thiếu dữ liệu, retention và giới hạn kết luận.

### 3.4. Yêu cầu chức năng

| ID | Yêu cầu bắt buộc | Bằng chứng nghiệm thu |
|---|---|---|
| FR-01 | Giữ mọi advisor trong registry kể cả không crawl được | Registry đối soát đủ ID; status riêng |
| FR-02 | Crawl có phân trang, cache, retry hữu hạn và resume | Manifest request, cursor, trạng thái kết thúc |
| FR-03 | Mỗi liên kết người–tài khoản và người–công bố có trạng thái xác minh | Identity ledger và bằng chứng nguồn |
| FR-04 | Mỗi skill có vai trò, cách áp dụng và trích dẫn | Evidence có locator/hash; không chỉ keyword |
| FR-05 | Điểm độc lập tính trước, không chứa KLTN đang đánh giá | Input lineage tách nguồn |
| FR-06 | Cộng điểm hướng dẫn theo skill cho đúng advisor đã xác minh | Assignment và thesis evidence join được |
| FR-07 | Xuất riêng delta từng kỳ và snapshot tích lũy | Manifest liệt kê kỳ, cutoff, source IDs |
| FR-08 | Phân biệt skill đề tài, skill cá nhân và nhu cầu đề tài | Các trường/nhãn riêng, không tự suy mức thành thạo |
| FR-09 | Phản hồi vòng trong có người cung cấp, thời điểm và cặp liên quan | Event ledger; chống xử lý lặp |
| FR-10 | Candidate rejected không làm parent | Retention chain được kiểm tra |
| FR-11 | So sánh RL với Hungarian và Greedy cùng input và constraints | Evaluation report và artifact hash |
| FR-12 | Không dùng external test để fit, tune hoặc cộng điểm ngược | Kiểm tra split/source membership |
| FR-13 | Khi API/HTTP crawl lỗi, bị chặn hoặc trả nội dung rỗng/thiếu do JavaScript, bắt buộc thử điều khiển Chrome để mở trang, phân trang, mở rộng nội dung và lấy tài liệu có thể truy cập | Log cả lần crawl trực tiếp và Chrome; URL, thao tác, nội dung thu được, phương thức thu thập và lý do nếu vẫn thất bại |
| FR-14 | Khi sau các bước thu thập chỉ có tên đề tài/bài báo, dùng chính tên đó để dự đoán tập skill/framework nhỏ nhất có cơ sở | Giữ nguyên title; xuất predicted_skills/predicted_frameworks, lý do và nhãn inferred_from_title; không ghi thành đã xác minh sử dụng |
| FR-15 | Khi có toàn văn, đọc toàn bộ tài liệu để xác định skill/framework và cách sử dụng, thay vì chỉ dựa vào title/abstract | Có kiểm kê toàn bộ trang/section/file liên quan, lỗi đọc/OCR và evidence cho từng claim; chỉ gắn full_text_complete khi đã xử lý đủ |
| FR-16 | Tách điểm dự đoán P và bằng chứng E; profile=40% P+60% E; GVHD là trung bình các KLTN hợp lệ của advisor có sử dụng skill/framework đang xét; final=50% profile+50% GVHD cho từng skill/framework | Xuất đủ P/E/profile/GVHD/final, mẫu số, masks và ví dụ tái tính được; dedup trong mỗi kênh |

### 3.5. Ngoài phạm vi

Không thu thập tài khoản riêng tư, không vượt CAPTCHA/paywall, không suy danh tính chỉ bằng tên. Không chấm chất lượng giảng dạy bằng stars/citations. Không suy quota hoặc chấp nhận hướng dẫn từ hồ sơ web. Không chạy code từ repo tải về. Không tự động triển khai model lên production. Không xây UI mới trong giai đoạn đặc tả này.

### 3.6. Tiêu chí thành công

Các invariant bắt buộc: 100% điểm đã công bố truy được về evidence; 0 liên kết sai người đã biết; 0 nguồn tương lai/holdout trong train; 0 vi phạm quota/eligibility trong kết quả được duyệt. Khi bài toán không khả thi phải trả `infeasible`, không ép coverage bằng hành động sai.

Mục tiêu pilot đề xuất: precision claim skill >= 0,95; precision liên kết advisor >= 0,99; recall >= 0,85 trên tập nguồn thủ công đã xác định. Đây là mục tiêu chưa đo, không phải kết quả. Báo mẫu số và khoảng tin cậy; mẫu ít không đủ chứng minh đạt ngưỡng. Tập pilot chỉ dùng train/validation, không lấy 2025.3.

## 4. Quyết định thiết kế và phương án

| Phương án | Ưu điểm | Hạn chế | Quyết định |
|---|---|---|---|
| Đếm từ khóa/số bài | Rẻ và tái lập | Không phân biệt sử dụng, nhắc tên, copy và vai trò | Baseline extraction |
| Evidence có cấu trúc, rubric cố định, reviewer cho ca khó | Truy vết tốt, kiểm soát thời gian và chi phí | Cần annotation pilot | Chọn cho MVP |
| Agent tự duyệt web và tự cho điểm toàn bộ | Linh hoạt | Chi phí khó kiểm soát, khó tái lập, nguy cơ suy diễn | Không dùng làm nguồn quyết định tự động |

MVP là batch pipeline trong repo hiện có. Dùng CSV/JSONL và manifest immutable; chưa cần vector database, graph database hoặc hệ multi-agent. LLM chỉ là bộ trích xuất tùy chọn, không quyết định danh tính, ngày hoặc score cuối cùng.

## 5. Nguồn thu thập và thông tin sử dụng

| Nguồn | Lấy thông tin gì | Skill/cách áp dụng có thể chứng minh | Giới hạn |
|---|---|---|---|
| Trang khoa/trường | Chức danh, đơn vị, lĩnh vực, môn học, đề tài, URL tác giả | Lĩnh vực quan tâm/giảng dạy có khai báo | Tự khai không tương đương thực hành |
| Scholar/ResearchGate trong danh bạ | Danh mục bài, tiêu đề, tác giả, năm, DOI/link | Phát hiện công bố ứng viên | Chỉ truy cập hợp lệ; blocked là blocked |
| OpenAlex/Crossref | DOI, tác giả, affiliation, ngày, nguồn, metadata | Đối soát danh tính và công bố | Metadata có thể thiếu/sai; không mặc định có full text |
| Publisher, arXiv, kho trường, bản tác giả công khai | Abstract, phương pháp, dữ liệu, thí nghiệm, hạn chế | Phương pháp và công nghệ thực sự dùng | Chỉ tải bản được phép; ghi license/access |
| Trang đề tài khoa học | Chủ nhiệm/thành viên, mục tiêu, sản phẩm, thời gian | Vai trò nghiên cứu và ứng dụng | Phân biệt kế hoạch với kết quả hoàn tất |
| GitHub đã xác minh | README, source tree, dependency, notebook, tests, commit/ref, contributors, releases | Ngôn ngữ, framework, phương pháp, cách triển khai | Dependency không chứng minh dùng; owner không mặc định là tác giả mọi dòng |
| KLTN được cung cấp | Bìa, advisor, nội dung phương pháp, triển khai, đánh giá | Kỹ năng của đề tài và bằng chứng kinh nghiệm hướng dẫn | Không tự suy kỹ năng cá nhân advisor hoặc sinh viên |
| Khảo sát/phản hồi có nguồn | Nguyện vọng, xác nhận cặp, thay đổi nhu cầu, outcome | Reward/constraint theo event | Không biến trạng thái chung thành chấp nhận cặp |

Tìm bài từ DOI và danh mục đã xác minh trước khi mở rộng tìm kiếm theo tên. Nguồn khám phá và bằng chứng tính điểm là hai vai trò khác nhau. Một công bố xuất hiện ở ba website chỉ là một artifact chuyên môn.

Nguồn kỹ thuật tham khảo: [OpenAlex API](https://help.openalex.org/api/), [OpenAlex endpoints](https://help.openalex.org/api/endpoints/), [Crossref REST API](https://github.com/CrossRef/rest-api-doc), [GitHub repository API](https://docs.github.com/en/rest/repos). Khi triển khai phải kiểm tra lại auth, pagination, quyền truy cập và rate limit; không đóng cứng quota API trong đặc tả.

### 5.1. Quy trình crawl

1. Validate schema, unique ID, URL HTTP(S), registry hash. Chặn URL nội bộ, loopback, metadata service và redirect không hợp lệ khi fetch.
2. Tạo identity candidates. URL trong CSV là seed; liên kết mới cần cross-link đáng tin cậy hoặc reviewer xác nhận. Tên tương đồng chỉ tạo candidate.
3. Đọc profile, khám phá danh mục, phân trang đến khi hết hoặc hết ngân sách. Lưu lý do dừng: `exhausted`, `budget_exceeded`, `blocked`, `error`.
4. Ưu tiên API chính thức, sau đó HTML/PDF công khai. Khi crawl trực tiếp thất bại hoặc thiếu nội dung do cơ chế hiển thị, bắt buộc chuyển sang điều khiển Chrome theo mục 5.2. Không dừng ở trạng thái blocked của HTTP nếu chưa thử Chrome hoặc chưa ghi rõ lý do không thể thử.
5. Lưu response metadata, raw hash, fetch time, parser version; secret không xuất ra log.
6. Normalize DOI/URL và duplicate group. Không gộp hai người có tên giống nhau.
7. Trích nội dung và evidence; phân kỳ sau khi xác minh ngày; chưa rõ giữ unresolved.
8. Publish batch mới sau validation; không ghi đè raw hoặc sửa manifest đã đóng.

Retry đề xuất tối đa 3 lần/request, exponential backoff với jitter; tôn trọng `Retry-After` và cơ chế rate limit của nguồn. Ngân sách thời gian/request/bytes do cấu hình lần chạy khai báo trước. Có timeout, giới hạn kích thước và số redirect. Resume theo cursor/content hash, không crawl lại toàn bộ khi lỗi một nguồn.

Với GitHub, pin commit SHA hoặc immutable ref; loại vendor/generated code, archive/fork mirror và ví dụ sao chép khỏi bằng chứng thực hành độc lập. Fork có đóng góp riêng được xét phần đóng góp có bằng chứng. Không dùng repo languages, dependency hoặc stars như thước đo thành thạo.

### 5.2. Fallback bắt buộc bằng Chrome

Chrome là phương thức thu thập dự phòng, không phải một loại bằng chứng mạnh hơn API. Dùng công cụ điều khiển trình duyệt hiện có; khi cần thao tác Windows dùng skill `computer-use:computer-use`. Khi triển khai phải đọc hướng dẫn skill và runtime tương ứng trước khi thao tác. Phiên sửa PRD này chỉ mô tả yêu cầu, chưa mở Chrome hoặc crawl.

1. Mở URL thất bại trong Chrome, chờ trang render; kiểm tra trang thực tế thay vì coi response rỗng là không có nội dung.
2. Dùng các thao tác thông thường: cuộn, next page, load more, mở abstract/full text, tab công bố và liên kết tải PDF có quyền truy cập. Thu đủ các trang danh mục trong ngân sách đã khai báo.
3. Ghi `collection_method=chrome_ui`, URL cuối, thời gian, pagination/completeness, text và locator; lưu bản tải/snapshot có thể xuất hợp lệ và hash. Nếu chỉ chụp được ảnh thì lưu ảnh cùng bản OCR có kiểm tra, không tạo raw HTML giả.
4. Nếu gặp đăng nhập/CAPTCHA cần người dùng xử lý, ghi `requires_user_action`; không tự vượt cơ chế bảo vệ hoặc xuất cookie. Nếu vẫn không truy cập được, ghi Chrome attempt và lỗi thực tế; dùng phần thông tin đã thu được, không hứa luôn lấy được toàn văn.
5. Một nội dung thu qua HTTP và Chrome được dedup theo cùng artifact. Khi hết ngân sách phải ghi `budget_exceeded` và phần còn thiếu; không gắn hoàn tất.

### 5.3. Phân nhánh theo nội dung thực sự thu được

| content_scope | Cách xử lý bắt buộc | Đầu ra |
|---|---|---|
| `title_only` | Sau khi thử lấy thêm nội dung, chỉ dùng tên đề tài hiện có để dự đoán tối giản; không tạo abstract hoặc phương pháp giả | Claim `inferred_from_title`, lý do và skill/framework dự đoán riêng |
| `abstract_only` | Đọc toàn bộ abstract; trích điều abstract mô tả rõ; không suy chi tiết triển khai chưa thấy | Claim `extracted_from_abstract`, locator và giới hạn |
| `partial_full_text` | Đọc mọi phần đã lấy được; đánh dấu trang/section thiếu và thử bổ sung bằng Chrome khi phù hợp | Claim từ phần đã đọc; completeness chưa đạt |
| `full_text_complete` | Xử lý toàn bộ nội dung trước khi tổng hợp; dùng evidence trong nội dung để xác định sử dụng | Claim `extracted_from_full_text`, evidence và coverage đầy đủ |

Với PDF, đọc tất cả trang; dùng OCR cho trang ảnh và kiểm tra phần chưa đọc được. Với HTML, đọc mọi section và phần mở rộng có nội dung. Với repo, kiểm kê toàn bộ cây tại ref đã pin, đọc toàn bộ file văn bản first-party liên quan triển khai, cấu hình, notebook, tests và tài liệu; ghi rõ binary/vendor/generated bị loại. Repo lớn không xử lý hết phải báo partial, không gọi là đã đọc toàn bộ. Có thể chia chunk nhưng phải ghi coverage; không chỉ đọc top-k đoạn rồi gắn full_text_complete.

Đọc toàn bộ không đồng nghĩa cộng điểm mọi từ xuất hiện. Tài liệu tham khảo, related work, phủ định, công nghệ dự kiến và baseline chỉ để so sánh vẫn phải phân loại đúng vai trò.

## 6. Taxonomy và trích xuất skill

Tái sử dụng `configs/data/taxonomy_v1.yaml`. Các nhóm hiện có: research domain, topic, programming languages, frameworks/libraries, databases, ML/AI methods, data engineering, cloud/DevOps, security/network, software engineering, research methods, math/statistics.

Không trộn domain, phương pháp và công cụ thành một kỹ năng duy nhất. Ví dụ một nghiên cứu có thể có domain `healthcare`, task phân loại, method deep learning, tool PyTorch. Tên ví dụ phải được map sang ID thật trong taxonomy; thuật ngữ chưa có đi vào `taxonomy_candidates`, không tự thêm cột feature trong lúc chạy.

Một claim phải trả lời:

- Skill nào và thuộc nhóm nào?
- Tác giả dùng, đề xuất, triển khai, đánh giá, giảng dạy hay chỉ nhắc đến?
- Dùng cho bài toán nào, trên dữ liệu nào, trong bước nào?
- Sản phẩm/kết quả nào được nguồn mô tả? Có giới hạn gì?
- Đoạn nào, trang/file/dòng nào chứng minh? Ngày nào và vai trò tác giả ra sao?

### 6.1. Các mức evidence

Nhánh chỉ có title dùng tập dự đoán nhỏ nhất: ưu tiên thuật ngữ xuất hiện trực tiếp trong title và ánh xạ domain/task/method rõ ràng sang taxonomy. Không suy framework cụ thể chỉ vì framework đó phổ biến. Ví dụ “Phân tích cảm xúc tiếng Việt bằng học sâu” có thể dự đoán NLP, sentiment analysis và deep learning; chưa đủ để chọn PyTorch, TensorFlow, BERT hoặc Python. Title có “sử dụng TensorFlow” có thể tạo ứng viên TensorFlow nhưng vẫn gắn `inferred_from_title` cho đến khi đối chiếu nội dung. Cho phép danh sách framework rỗng nếu không có cơ sở.

Mỗi dự đoán lưu title gốc, skill_id, prediction_reason, inference_rule/model_version và evidence_status. Không tạo phần “cách đã áp dụng” từ title; trường này để unknown hoặc ghi rõ giả thuyết. Khi có toàn văn, ưu tiên claim từ toàn văn; dự đoán không được xác nhận giữ trong audit và loại khỏi điểm sử dụng đã xác minh.

| Mức | Điều kiện | Hệ số đề xuất |
|---|---|---:|
| Mention | Chỉ xuất hiện thuật ngữ, citation hoặc related work | 0 |
| Title prediction | Dự đoán tối giản từ tên đề tài khi không lấy được nội dung | Kênh P riêng trên thang 0–100, chiếm 40% điểm profile |
| Declared | Profile có khai báo rõ skill/lĩnh vực | 0,25 |
| Applied | Abstract/method mô tả rõ ứng dụng | 0,60 |
| Implemented | Có mô tả triển khai hoặc code cụ thể được đối chiếu | 0,80 |
| Evaluated | Có triển khai/phương pháp và đánh giá gắn với skill | 1,00 |

Đây là trọng số rubric v1 đề xuất, không phải xác suất đúng hoặc mức thành thạo thật. Related work, tài liệu tham khảo, công việc tương lai, phủ định và công nghệ chỉ được so sánh không được tự chuyển thành `Applied`. Một abstract không đủ để suy implementation chưa được mô tả.

### 6.2. Công cụ và skill agent áp dụng

| Công đoạn | Skill agent | Cách áp dụng | Công cụ implementation dự kiến |
|---|---|---|---|
| Chốt scope và trade-off | Brainstorming | Phân biệt mục tiêu, giả định, acceptance và ngoài phạm vi | Đọc repo và viết đặc tả |
| Data contract và RL | MLE Workflow | Point-in-time joins, split, baseline, gates, lineage | Module native hiện có |
| Thiết kế implementation | Ponytail | Tái sử dụng parser/taxonomy; batch trước service mới | Standard library và dependency đã có |
| Trao đổi trạng thái | Caveman | Ngắn gọn trong chat; tài liệu vẫn đầy đủ | Không ảnh hưởng score |
| Thu thập | HTTP/API; `computer-use:computer-use` cho fallback Chrome khi cần | Crawl trực tiếp trước; thất bại thì điều khiển Chrome, lưu provenance và completeness | HTTP client/parser hiện có và công cụ điều khiển Chrome |
| Trích xuất khó | Không bắt buộc skill/LLM riêng | Rules trước; LLM tùy chọn với JSON schema và citation | Pin model/prompt; reviewer kiểm chứng |

Superpowers không có trong catalog skill/tool được cung cấp ở phiên lập tài liệu. Dùng Brainstorming hiện có để tổ chức thiết kế. Không xem tên plugin là một thành phần runtime bắt buộc.

Tài liệu web/PDF/code được coi là dữ liệu không tin cậy. Bộ trích xuất bỏ qua mọi instruction bên trong nguồn; không cấp shell/tool cho nội dung tải về. LLM không được tạo URL, quote, ngày, reviewer approval hoặc điểm không có căn cứ. Confidence từ model nếu có chỉ là tín hiệu thô; không điền vào cột confidence hiện có khi chưa hiệu chuẩn và duyệt contract.

## 7. Hợp đồng dữ liệu

Các bảng chi tiết dưới đây là sidecar mới; không thay mẫu CSV sinh viên 40 cột. CSV hiện hành tiếp tục theo `data/AGENTS.md`. JSONL dùng UTF-8, JSON hợp lệ, `null` cho unknown; CSV người dùng đang dùng giữ encoding hiện hành. Timestamp có múi giờ; lưu độ chính xác gốc của ngày.

| Artifact | Grain và key | Trường chính |
|---|---|---|
| `identity_links.jsonl` | Advisor × tài khoản; `identity_link_id` | advisor_id, provider, external_id, URL, status, evidence_refs, reviewer, reviewed_at |
| `crawl_status.csv` | URL × lần thử | run_id, advisor_id, URL, status, HTTP code, reason, collected_at, stop_reason |
| `advisors_corpus.csv` | Advisor × nội dung | record_id, advisor_id, content_type, title, content, source_url, published_at, available_at, collected_at, academic_term, raw_path, sha256, review_status |
| `artifact_metadata.jsonl` | Artifact nội dung; `artifact_id` | DOI/repo/ref, duplicate_group_id, date_precision, event_interval, identity_link_ids, access/license, availability_evidence, training_eligibility |
| `skill_evidence.jsonl` | Claim skill × artifact × chủ thể; `evidence_id` | advisor_id/student_id, skill_id, group, relation, context, task, data, method, tool, result, level, contribution_status, quote, locator, raw_sha256, dates, review |
| `supervision_links.jsonl` | Advisor × KLTN; `supervision_id` | thesis_id, student_ids, advisor_id, role, credit_share, proof_refs, confirmed_at, review_status |
| `advisor_skill_scores.csv` | Advisor × skill × snapshot | prediction_score, evidence_score, profile_score, gvhd_score, final_score, component_masks, completeness_status, profile_work_count, thesis_count, known_mask, source_count, source_diversity, evidence_ids, cutoff, rubric_version |
| `student_skill_requirements.jsonl` | Student/project × skill × thời điểm | requirement_weight, mandatory, source_ref, available_at, evidence_scope |
| `feedback_events.jsonl` | Một event có phiên bản; `event_id` | semester_id, round_id, student_id, advisor_id, type, value, provider, event_time, available_at, source_ref, status, supersedes |
| `snapshot_manifest.json` | Snapshot immutable; `snapshot_id` | protocol_id, semester/pool, cutoff, split hash, registry/taxonomy/rubric/feature hash, source hashes, scope, exclusions |

Mỗi evidence ID được tạo từ nội dung canonical gồm artifact identity, chủ thể, skill, locator và claim version; các bản sao cùng claim không tạo điểm mới. Mỗi source phải có raw/text hash kiểm chứng. Claim được sửa tạo version mới và audit; không âm thầm thay lịch sử.

Review status dùng `pending`, `needs_review`, `approved`, `rejected`; tự động parse thành công không có nghĩa là `approved`. Reviewer và reviewed_at không được tự tạo. Eligibility dùng ít nhất `point_in_time_verified`, `retrospective_proxy`, `unresolved`, `excluded`.

Bổ sung vào sidecar metadata/evidence: `collection_method` (`api`, `http`, `chrome_ui`), `content_scope`, `content_completeness`, `processed_units`, `missing_units`, `evidence_status` (`inferred_from_title`, `extracted_from_abstract`, `extracted_from_full_text`), `prediction_reason`, `inference_version`, `supersedes_evidence_id`. Completeness đo số trang/section/file xử lý trên tổng số đã kiểm kê, không dùng làm confidence đúng skill. Ghi content_scope ở cấp artifact và evidence_status theo phần thực sự hỗ trợ từng claim.

### 7.1. Output theo cấu trúc hiện có

```text
data/<pool-or-semester>/advisors/
  faculty_profiles/advisors_profile.csv
  faculty_corpus/
    advisors_corpus.csv
    crawl_status.csv
    raw/...
    artifact_metadata.jsonl
    skill_evidence.jsonl
  faculty_processed/
    advisors_processed.csv
    advisor_skill_scores.csv
    supervision_links.jsonl
    snapshot_manifest.json
```

Các tên sidecar là giao diện đề xuất, chưa phải file đã tạo. Registry/identity ledger dùng chung được lưu một bản ở run staging và tham chiếu bằng hash khi publish. Nguồn thiếu ngày/ngoài kỳ ở staging của run với `unresolved.csv`; không tự mở học kỳ mới. Checkpoint/log/experiment nằm trong `outputs/<run_id>/`, không nằm trong corpus.

## 8. Chấm điểm từng skill của giảng viên

**Quy tắc hiện hành do người dùng chốt ngày 02/11/2026:** mục 8 này thay thế toàn bộ công thức điểm độc lập bão hòa và điểm GVHD cộng dồn của bản 1.1. Mọi điểm tính riêng theo `(advisor_id, skill_id, snapshot_id)` trên thang 0–100.

### 8.1. Các thành phần và công thức bắt buộc

```text
P_Ak = điểm dự đoán skill/framework k từ các title của giảng viên A
E_Ak = điểm có bằng chứng skill/framework k từ nội dung của giảng viên A
profile_Ak = 0.40 × P_Ak + 0.60 × E_Ak

J_Ak = các KLTN độc lập có giảng viên A hướng dẫn đã xác minh và có sử dụng skill k,
      thuộc split và thời điểm được phép của snapshot
gvhd_Ak = sum(thesis_score_jk for j in J_Ak) / count(J_Ak)

final_Ak = 0.50 × profile_Ak + 0.50 × gvhd_Ak
         = 0.20 × P_Ak + 0.30 × E_Ak + 0.50 × gvhd_Ak
```

Không gộp mọi skill thành một điểm chung cho giảng viên. Ví dụ Python và PyTorch có từng bộ P/E/profile/gvhd/final riêng. Dùng `final_score` làm điểm cuối cùng của skill trong matching; vẫn xuất mọi thành phần để giải thích và kiểm tra.

### 8.2. Chấm P và E trên cùng thang đo

Người dùng đã chốt trọng số tổng hợp; rubric chấm từng công trình dưới đây là mặc định đề xuất để các thành phần cùng đơn vị và có thể tái lập. Các hệ số này không phải confidence đã hiệu chuẩn hay mức thành thạo cá nhân.

| Thành phần | Rubric mỗi công trình–skill | Điểm |
|---|---|---:|
| P | Title nêu trực tiếp skill/framework như một phương pháp/công cụ được dùng | 100 |
| P | Title hỗ trợ suy luận đơn giản về domain/task/method, có rule và lý do rõ | 50 |
| P | Không có cơ sở suy luận skill cụ thể từ title đã đọc | 0 |
| E | Chỉ nhắc tên, related work, citation, phủ định hoặc dự kiến dùng | 0 |
| E | Hồ sơ tự khai trực tiếp chuyên môn | 25 |
| E | Nội dung mô tả rõ ứng dụng | 60 |
| E | Nội dung/code cho thấy triển khai cụ thể | 80 |
| E | Nội dung thể hiện phương pháp/triển khai và đánh giá tương ứng | 100 |

P_Ak là trung bình điểm title của các công trình profile độc lập có dự đoán hợp lệ về skill k và xác minh liên kết A. E_Ak là trung bình điểm evidence của các công trình profile độc lập có bằng chứng sử dụng skill k và nội dung đủ xử lý. Công trình không dự đoán hoặc không sử dụng skill k không được đánh giá cho k và không vào mẫu số tương ứng; không gán 0 để kéo giảm trung bình. Nguồn chỉ có title không vào mẫu số E. Một công trình–skill lấy mức phù hợp cao nhất; các bản mirror/preprint/publisher của cùng work group chỉ tính một lần. Không nhân điểm theo số lần xuất hiện hoặc số bản sao profile. Báo mẫu số và coverage của P/E riêng.

Nếu toàn văn thu được không xác nhận suy luận từ title, P vẫn là bản ghi dự đoán có thể đối chiếu, E phản ánh bằng chứng thực tế; không chuyển dự đoán thành evidence. Nếu toàn văn xác định title đang nói về baseline/related work, sửa prediction không còn hợp lệ bằng version mới và audit. Một công trình được phép góp một giá trị vào P và một giá trị vào E vì hai kênh có trọng số riêng do người dùng quy định; không được tạo thêm hàng cùng công trình trong một kênh.

Không suy framework phổ biến từ tên đề tài chung. Dùng taxonomy hiện có; chưa đủ cơ sở chọn framework thì không tạo prediction framework đó. Với nguồn đồng tác giả, giữ nhãn attribution và chỉ tính sau khi liên kết người–công trình được xác minh; score phản ánh mức bằng chứng của công trình liên quan, không chứng minh advisor tự thực hiện toàn bộ kỹ thuật.

### 8.3. Điểm GVHD là trung bình các KLTN có sử dụng skill đang xét

Trích skill từ toàn bộ nội dung KLTN, chỉ chấm các skill có sử dụng theo thang 60/80/100 cho Applied/Implemented/Evaluated ở trên để có `thesis_score_jk`. Chỉ mention hoặc không sử dụng không tạo điểm đánh giá cho skill đó. Không nhân với điểm bảo vệ, số sinh viên hay số file. Đây là điểm bằng chứng skill trong công trình đã hướng dẫn, không phải điểm học vụ hay nhận định giảng viên tự code.

Mẫu số là **số KLTN hợp lệ của A có sử dụng skill k**. KLTN không sử dụng skill k được loại khỏi cả tử số và mẫu số, không chấm 0. Ví dụ ba KLTN được biểu diễn là 80, 100, 0, trong đó 0 nghĩa là không sử dụng Python, thì gvhd_A,Python=(80+100)/2=90. Khi lưu dữ liệu, dùng usage_status=not_used và thesis_score=null cho bài không sử dụng, thay vì lưu 0 như một điểm đã đánh giá. Lọc theo trạng thái sử dụng, không dùng điều kiện score>0 thay thế kiểm tra bằng chứng.

KLTN chưa đọc đủ, không xác minh advisor hoặc không đủ thời điểm không được tự coi là 0. Ghi rõ bài thiếu và `gvhd_completeness`; nếu còn KLTN trong phạm vi bắt buộc mà chưa xử lý đầy đủ, điểm trên tập đã đọc chỉ là `partial`, chưa công bố là trung bình toàn bộ. Bài ngoài cutoff/split không thuộc J_Ak. Nếu không có KLTN nào sử dụng skill k thì gvhd_Ak=null, usage_count=0; không chia cho 0 hoặc kết luận giảng viên có điểm skill bằng 0.

Hai sinh viên cùng một KLTN hoặc PDF/DOCX cùng nội dung chỉ là một bài. Nếu nhiều advisor đã được xác minh hướng dẫn, bài được đưa một lần vào tập bài của mỗi advisor liên quan; lấy trung bình không trọng số đúng yêu cầu, không chia điểm theo credit_share. Vai trò advisor vẫn lưu để audit. Không dùng advisor do model dự đoán làm liên kết hướng dẫn thật.

### 8.4. Missing và ví dụ tính điểm

Thiếu hẳn dữ liệu của một thành phần: lưu null và mask tương ứng; không tự điền 0, không đổi trọng số hoặc chia lại trọng số trên phần đang có. `profile_score` chỉ tính khi P/E đều có; `final_score` chỉ tính khi profile/GVHD đều có và completeness đạt yêu cầu. Ca chưa đủ điều kiện có status `insufficient_data` hoặc `partial` và dùng fallback matching đã khai báo. Người dùng chưa yêu cầu một quy tắc thay thế cho advisor không có KLTN.

Ví dụ minh họa, không phải dữ liệu thật: Python của A có P=70 và E=90, nên profile=0,4×70+0,6×90=82. Hai KLTN sử dụng Python đạt 80 và 100; bài thứ ba không sử dụng Python nên không đánh giá. gvhd=(80+100)/2=90. Điểm cuối cùng Python của A là 0,5×82+0,5×90=86.

Chỉ làm tròn khi hiển thị, tối đa 2 chữ số thập phân; lưu độ chính xác đầy đủ trong artifact. Thêm bản sao công trình không đổi kết quả. Thêm KLTN mới có thể làm trung bình tăng hoặc giảm; không yêu cầu điểm chỉ tăng theo số lượng bài.

### 8.5. Hiệu chuẩn, thời gian và chống lệch điểm

Khóa rubric chấm từng công trình trên train/validation trước training và lưu hash. Các trọng số 40/60 và 50/50 là yêu cầu sản phẩm cố định; không tune lại theo validation/test. Không còn cap điểm GVHD, tau, công thức bão hòa hoặc cộng I+B của bản cũ.

Giữ riêng P/E/profile/GVHD/final, số công trình, số bài, coverage và evidence IDs. Khi nội dung mới khả dụng, tạo snapshot mới; không dùng nó sửa ngược snapshot lịch sử. Dự đoán không được dùng để tự xác nhận mandatory skill. Thiếu nguồn không đồng nghĩa thiếu năng lực. Tiếp tục áp dụng cutoff, leave-one-thesis-group-out, split và external-test boundary.

## 9. Skill sinh viên, skill đề tài và matching

Ba vector khác nhau:

- `student_preexisting_skills`: kỹ năng có nguồn trước thời điểm quyết định; không suy từ KLTN hoàn thành.
- `project_requirements`: kỹ năng đề tài cần, lấy từ đề cương/nhu cầu đã có ở thời điểm quyết định.
- `thesis_observed_skills`: kỹ năng xuất hiện có ứng dụng trong KLTN hoàn thành; dùng cho hậu kiểm/điểm GVHD hướng dẫn tương lai.

MVP tái sử dụng evidence trang/đoạn/offset hiện có; không sửa confidence/proficiency của CSV gốc. Trọng số yêu cầu do đề cương hoặc reviewer xác nhận; thiếu trọng số dùng đều giữa các skill đã xác minh và ghi `uniform_requirement_proxy`. Mandatory skill thiếu bằng chứng trả `needs_review`, không tự kết luận advisor không đủ điều kiện.

Định nghĩa tương thích dễ kiểm tra:

```text
w_k >= 0; sum_k w_k = 1 trên các requirement đã xác minh
C(student, advisor, t) = sum_k w_k × final_score(advisor,k,t)/100
coverage = sum_k w_k × known_mask(advisor,k,t)
```

Placeholder unknown bằng 0 làm C thành ước lượng bảo thủ về bằng chứng tương thích; phải xuất coverage cùng C. Không renormalize chỉ trên skill có điểm vì sẽ thưởng hồ sơ thiếu. Ca coverage thấp chuyển review hoặc fallback khai báo, không dùng ngưỡng ngầm. Ngưỡng coverage là cấu hình phải chốt trên pilot trước experiment.

Matching kết hợp C, nguyện vọng có nguồn, tải/quota và constraints. Quota/eligibility là ràng buộc có nguồn riêng, không học từ bài báo hoặc skill score. Hungarian/Greedy và RL nhận cùng feature, mask, quota. Với mục tiêu tĩnh cộng được theo cặp và constraints chuẩn, Hungarian là baseline rất mạnh; RL chỉ được giữ khi kiểm chứng lợi ích ở mục tiêu/feedback động.

### 9.1. Chặn self-leakage

Khi đánh giá khả năng ghép sinh viên s, loại KLTN của s và toàn bộ duplicate group khỏi điểm GVHD advisor dùng cho quyết định đó. Không được dùng thesis s để tăng skill của advisor hướng dẫn s rồi đo model tìm lại đúng advisor. Tập validation/test không được cộng vào hồ sơ advisor phục vụ train hoặc selection. Với đánh giá hồi cứu, dùng leave-one-thesis-group-out và ghi rõ đây vẫn là proxy nếu feature không có ở thời điểm phân công.

## 10. Tổng hợp theo học kỳ và thời gian

### 10.1. Lịch chuẩn của protocol này

Múi giờ Asia/Saigon. Tháng 9–12 năm Y thuộc Y.1; tháng 1–5 thuộc (Y−1).2; tháng 6–8 thuộc (Y−1).3.

| Pool/thư mục | Cửa sổ sự kiện | Vai trò |
|---|---|---|
| `2024` | Đến hết 31/08/2025 | Bootstrap V1; giữ academic_term thật của từng record |
| `2025.1` | 01/09/2025–31/12/2025 | V2 |
| `2025.2` | 01/01/2026–31/05/2026 | V3 |
| `2025.3` | 01/06/2026–31/08/2026 | External test, không train/tune |

Pool `2024` không phải một học kỳ giả và không giới hạn năm dương lịch 2024. Báo cáo điểm delta vẫn nhóm theo `academic_term` thực tế nếu có đủ ngày. Dữ liệu sau 31/08/2026 để staging/unresolved, không tự mở V4 hoặc dùng làm phần bổ sung của 2025.3.

### 10.2. Bốn mốc bắt buộc

- `event_time/published_at`: khi công bố/sự kiện xảy ra.
- `available_at`: khi nội dung cụ thể đã có thể được sử dụng, có bằng chứng.
- `collected_at`: khi crawler thu thập.
- `decision_time`: khi hệ thống ra quyết định cần đánh giá.

Cutoff cuối kỳ là giới hạn đóng gói, không tự thay cho decision_time đầu kỳ. Snapshot phục vụ quyết định chỉ chứa evidence khả dụng trước decision_time; event cũ nhưng trang hiện tại mới crawl chưa chứng minh khả dụng lịch sử. Git commit timestamp một mình cũng không chứng minh repo đã public ở thời điểm đó. Metadata hiện tại như citations/stars không được đưa lùi về lịch sử.

Ngày chỉ có năm giữ interval; chỉ xét historical eligibility khi cả interval và availability proof đáp ứng cutoff. Không bịa ngày 01/01. Kỳ chưa xác định giữ unresolved; không lấy tên file/ngày crawl để gán kỳ. Với KLTN, dùng tháng/năm trên bìa đúng hướng dẫn `data/AGENTS.md`.

### 10.3. Snapshot và điểm GVHD qua kỳ

Mỗi kỳ xuất (1) evidence mới thuộc kỳ, (2) P/E/profile/GVHD/final tính riêng trên công trình đủ điều kiện của kỳ, (3) snapshot tích lũy nếu dùng và ledger correction. Trung bình tích lũy phải tính từ tổng điểm và số công trình unique, không lấy trung bình không trọng số của các trung bình học kỳ có số bài khác nhau. Không cộng điểm snapshot cũ với điểm delta.

KLTN hoàn thành kỳ t xuất hiện trong báo cáo hậu kiểm t; điểm GVHD chỉ được dùng cho quyết định sau available_at. Phân công đầu kỳ t không sử dụng KLTN hoàn thành cuối kỳ t. Trong vòng giữa kỳ, chỉ feature thực sự có trước vòng đó được xét, và từng vòng phải pin snapshot riêng.

Hồ sơ crawl hiện nay thiếu proof lịch sử có thể dùng cho phân tích `retrospective_proxy`, không trộn với `point_in_time_verified`. Báo cáo chất lượng phải tách hai phạm vi. Không gọi snapshot cuối kỳ là dữ liệu có sẵn đầu kỳ.

## 11. RL hai cấp

### 11.1. Cấp ngoài: continual RL giữa các học kỳ

```text
V1: bootstrap pool 2024, nhiều round trên cohort nền V1
V2: cohort 2025.1, khởi tạo từ checkpoint accepted gần nhất
V3: cohort 2025.2, khởi tạo từ checkpoint accepted gần nhất
Freeze selection, sau đó evaluate external test 2025.3
```

Hai cấp là hai thang cập nhật theo thời gian; không bắt buộc manager–worker hay meta-RL. PPO/DQN nếu dùng là hai learner độc lập, không phải hai cấp. PPO là nhánh ưu tiên tái sử dụng; chỉ thêm DQN nếu có mục tiêu nghiên cứu và đủ ngân sách.

Giữ weight/optimizer/counter tương thích theo implementation đã xác minh; lưu init hash và parent hash. Registry, thứ tự skill, dimension, normalization, reward và action semantics phải có contract. Thay taxonomy/feature dimension cần bridge được kiểm chứng hoặc experiment mới; không nhét feature mới vào checkpoint cũ.

Chống forgetting bắt đầu bằng warm start và đánh giá holdout các kỳ cũ. Có thể trộn episode train cũ nếu hợp lệ; với PPO phải tạo rollout mới theo policy hiện tại, không coi rollout cũ là on-policy. DQN chỉ tái dùng replay khi state/action/reward/mask/provenance tương thích. Replay train không được chứa holdout/test. [Experience Replay for Continual Learning](https://arxiv.org/abs/1811.11682) là tài liệu tham khảo nghiên cứu; hiệu quả trong UniMatch cần ablation riêng.

### 11.2. Cấp trong: RL nhận phản hồi trong cùng kỳ

State gồm requirement/skill vector và mask, advisor score channels prediction/evidence/profile/GVHD/final, quota còn lại, eligibility, preference hợp lệ, trạng thái phân công và feedback đã khả dụng. Không đưa tên/MSSV/raw personal text vào feature chỉ để model ghi nhớ cặp lịch sử.

Action là chọn advisor hợp lệ cho sinh viên đang xét; action mask chặn full quota và ineligible. Nếu không có action hợp lệ, xử lý trạng thái infeasible/unmatched đúng contract; không gọi fallback ngầm. Action space cụ thể phải khớp environment native khi triển khai.

Các round là cấu hình, không cố định một loại phản hồi vào số vòng. Mỗi round giữ cohort/membership nền và snapshot riêng; feedback không tạo bản sao sinh viên thành người mới. Phân biệt:

| Feedback | Tác động được phép | Không suy ra |
|---|---|---|
| Nguyện vọng có timestamp | Feature/reward preference | Advisor đồng ý |
| Xác nhận nhận/từ chối đúng cặp | Constraint hoặc reward theo contract | Trạng thái của mọi cặp khác |
| “Đã đăng ký thành công” chung | Receipt trạng thái | Nhận ưu tiên 1 hoặc khóa advisor |
| Cập nhật nhu cầu đề tài | Feature requirement mới từ vòng kế tiếp | Kỹ năng trước đây đã có |
| Đánh giá tiến độ/hài lòng | Delayed reward có nguồn, coverage và bias report | Ground truth chất lượng hướng dẫn |
| Kết quả KLTN hoàn thành | Outcome hậu kỳ, điểm GVHD tương lai đủ điều kiện | Feature đầu kỳ hoặc điểm cá nhân advisor |

Không có event mới: nếu protocol tiếp tục train, gắn `optimization_only` và ghi số event mới bằng 0. Không gọi đó là học từ phản hồi mới. Survey chỉ join theo MSSV đã xác minh; không có câu trả lời không có nghĩa từ chối hay bị loại cohort. Không lấy khảo sát tương lai làm phản hồi lịch sử.

### 11.3. Reward

```text
r = alpha * compatibility_delta
  + beta * verified_preference_satisfaction
  + gamma * verified_pair_feedback
  + eta * normalized_delayed_outcome
  - lambda * declared_load_penalty
```

Đây là template; từng term phải có định nghĩa, đơn vị, range và tính trên bước hay cuối episode để tránh cộng lặp. Delayed outcome chỉ hoạt động khi có timestamp, nhãn và episode linkage; không có thì disable, không điền 0 như nhãn âm. Chuẩn hóa fit trên train; weights khóa bằng validation trước final test. Ràng buộc cứng đi qua mask/validator, không chỉ dùng penalty.

Để tránh đếm đôi, không cộng cả compatibility chứa điểm GVHD và một reward điểm GVHD KLTN tương tự. Outcome hiện tại không được đồng thời cập nhật feature cho quyết định trước outcome. Báo cáo tương thích là proxy objective; cải thiện reward không tự chứng minh kết quả giáo dục tốt hơn.

Mỗi feedback event có idempotency key; event sửa đổi dùng supersedes. Phản hồi thiếu nguồn hoặc đến sau cutoff bị cách ly. Người dùng phản hồi chỉ quan sát advisor đã được phân công tạo selection bias; không gán outcome cho cặp chưa quan sát. Offline policy evaluation bằng IPS/DR chỉ xem xét khi có propensity log đáng tin cậy và đủ support; nếu thiếu, không tuyên bố causal uplift.

### 11.4. Retention và phát hành

Candidate phải được so với parent và baseline trên cùng snapshot validation và holdout cũ. Candidate thất bại bị rejected; checkpoint accepted gần nhất tiếp tục làm parent. Acceptance nghiên cứu, checkpoint retention và production promotion là ba quyết định riêng.

Manifest vòng gồm protocol/run/term/round, algorithm, cohort/split, parent, source/evidence/feature/taxonomy/rubric/reward hashes, feedback IDs, config, seed, code SHA, model/optimizer/counter hashes, metrics và decision. Không sửa parent hoặc dùng candidate chưa hoàn tất manifest.

## 12. Đánh giá và cổng nghiệm thu

### 12.1. Đánh giá dữ liệu và điểm

Tạo tập gold từ train/validation, stratify theo advisor, loại nguồn, skill và ngôn ngữ. Pilot đề xuất ít nhất 200 claim và 50 identity/supervision link nếu có đủ dữ liệu thật; nếu ít hơn thì review toàn bộ và báo giới hạn mẫu. Hai reviewer độc lập trên phần giao ít nhất 20%; bất đồng cần adjudication. Không tạo claim giả để đủ số mẫu.

Đo precision/recall extraction, identity linkage, supervision linkage, application relation, date classification, duplicate detection, evidence traceability và coverage. Gold recall chỉ có nghĩa trên tập nguồn đã rà thủ công; không tuyên bố recall toàn bộ Internet. Đo độ ổn định score khi thêm mirror, duplicate, đổi parser hoặc thay rubric.

### 12.2. Đánh giá matching và RL

Baseline bắt buộc: Random có seed để tham chiếu; Greedy và Hungarian trên cùng utility/constraints; parent accepted; warm-start không feedback. Ablation tối thiểu: không skill enrichment, chỉ profile, profile kết hợp GVHD theo 50/50, bỏ feedback, continual so với train lại từng kỳ. Giữ cùng ngân sách và split; không mở rộng toàn bộ ma trận thí nghiệm nếu không trả lời giả thuyết cụ thể.

Metric: feasibility, coverage/unmatched, mean compatibility, preference satisfaction, quota utilization, load imbalance, nguồn/skill coverage, thời gian và chi phí. Tách metric từ outcome thật với proxy. Historical-advisor recovery chỉ là diagnostic có bias, không là ground truth phân công tối ưu.

Forgetting trên kỳ cũ j: `max(0, metric(parent,j) - metric(candidate,j))`, đo trên cùng holdout bất biến. Theo dõi trung bình và kỳ tệ nhất. Không train trên holdout forgetting. Chạy nhiều seed, đề xuất tối thiểu 3 nếu ngân sách cho phép; nếu chỉ 1 seed phải báo rõ. Khoảng tin cậy nên bootstrap theo cohort/student group phù hợp, không coi từng bước rollout là quan sát độc lập.

### 12.3. Gate trước training

Trước khi train phải có config định nghĩa primary metric, improvement margin, forgetting tolerance, coverage floor, cost budget, seed và split. Thiếu cấu hình hoặc dữ liệu đánh giá thì `not_evaluable`, không tự điền ngưỡng. Margin và tolerance được chốt bằng train/validation, không lấy từ kết quả final test.

Gate cứng: không leakage, provenance/hash hợp lệ, không constraint violation, không tự tạo approval, contract tương thích. Gate retention: metric và forgetting đạt ngưỡng đã khóa. Gate promote: bằng chứng vận hành và review riêng; tài liệu này không cấp quyền promote.

`2025.3` đã được training guide báo cáo là từng mở test. Vì vậy không dùng lại nó như một test hoàn toàn chưa nhìn thấy để chứng minh thiết kế mới. Giữ nó là benchmark lịch sử bị ảnh hưởng bởi việc đã quan sát; cần holdout mới chưa mở hoặc đánh giá prospective để có kết luận xác nhận. Không tự thu thập/mở kỳ mới trong phạm vi viết tài liệu này.

## 13. Kịch bản kiểm thử implementation bắt buộc

| Tình huống | Kết quả đúng |
|---|---|
| Scholar bị chặn, GitHub trống | Giữ advisor; ghi blocked/unknown, không gán không có kỹ năng |
| HTTP lỗi hoặc HTML rỗng do JavaScript | Thử Chrome; lưu phương thức, nội dung và kết quả thực tế |
| Chrome vẫn bị chặn hoặc yêu cầu CAPTCHA | Ghi blocked/requires_user_action; không giả đã thu toàn văn |
| Chỉ có title “học sâu cho phân tích cảm xúc” | Dự đoán tối giản NLP/sentiment/deep learning; không tự chọn framework |
| Có toàn văn 30 trang nhưng chỉ đọc 3 trang | Không gắn full_text_complete; xử lý phần còn lại hoặc báo partial |
| Full text không xác nhận dự đoán title | E theo nội dung thực tế; P vẫn là dự đoán riêng; sửa P nếu phát hiện rule/title bị diễn giải sai |
| P=70, E=90; hai KLTN dùng skill đạt 80/100, bài thứ ba không dùng (ký hiệu 0) | profile=82; GVHD=90; final=86; mẫu số GVHD=2 |
| Thiếu P, E hoặc GVHD | Null/partial đúng thành phần; không tự chia lại trọng số |
| Hai tác giả cùng tên, affiliation khác | Không tự merge; needs_review |
| Paper chỉ nhắc BERT trong related work | Không cộng điểm ứng dụng BERT |
| Dependency có TensorFlow nhưng không có dùng cụ thể | Không tự cho Implemented |
| Paper/preprint/Scholar cùng DOI | Một work group, không ba lần điểm |
| Fork mirror không có đóng góp riêng | Không có điểm thực hành độc lập |
| PDF KLTN và DOCX chuyển đổi cùng nội dung | Một thesis group; không cộng hai lần |
| Hai sinh viên cùng một KLTN | Một đơn vị điểm GVHD thesis–skill |
| Advisor trên bìa chưa rõ định danh | Không cộng điểm GVHD đến khi duyệt |
| KLTN hoàn thành sau quyết định đầu kỳ | Loại khỏi feature đầu kỳ |
| KLTN của sinh viên đang được evaluate | Loại khỏi điểm GVHD của mọi advisor trong phép đánh giá đó |
| Khảo sát không có MSSV tương ứng | Audit missing; không loại sinh viên hoặc tạo phản hồi |
| Event lặp hoặc event sửa | Idempotent; bản thay thế được audit |
| Chỉ biết năm, interval cắt qua cutoff | Unresolved/không đủ point-in-time |
| Thêm skill làm đổi dimension | Chặn checkpoint load nếu chưa có bridge |
| Candidate bị loại | Parent tiếp theo vẫn là accepted gần nhất |
| Không có feedback mới | Optimization-only hoặc skipped theo config, không gắn learned_from_feedback |
| Không đủ quota | Infeasible rõ ràng, không vượt quota |
| Điểm GVHD có nguồn 2025.3 đi vào V3 | Preflight thất bại |

## 14. Lộ trình triển khai đề xuất

| Giai đoạn | Công việc | Điều kiện kết thúc |
|---|---|---|
| P0: Contract | Chốt rubric, taxonomy, thời điểm quyết định, lịch/protocol và split | Config review được; calendar mismatch có phương án xử lý |
| P1: Pilot crawl | Kiểm tra toàn bộ 17 seed, chọn mẫu ít nguồn/nhiều nguồn, lưu raw/status | Identity và source coverage report; chưa crawl đại trà thiếu kiểm soát |
| P2: Extraction | Tái sử dụng normalization, thêm relation/context, dựng gold | Đạt gate precision và traceability hoặc báo failure |
| P3: Independent score | Dedup, attribution, score I và known mask | Reviewer tái tính được ví dụ từ nguồn |
| P4: Supervision | Link KLTN, trích skill, tính B/T, chặn self-leakage | Supervision ledger và test thời gian/duplicate đạt |
| P5: Snapshot/baseline | Delta và cumulative từng kỳ; temporal split; Hungarian/Greedy | Baseline tái lập; strict/proxy tách biệt |
| P6: Nested RL | Round feedback, retention, forgetting, ablation | Report và artifact đầy đủ; không tự promote |
| P7: Review | Đánh giá giới hạn, bias, chi phí và holdout mới | Quyết định giữ baseline hoặc đi tiếp có bằng chứng |

Không ước lượng thời gian/GPU khi chưa benchmark pilot. Báo theo run: requests, bytes, token, model/API cost, thời gian crawl/extract/train và số ca cần review. Cache theo hash, chỉ gọi LLM cho ca rules không giải quyết được; không tạo nhiều agent/model cho cùng nhiệm vụ khi chưa chứng minh lợi ích.

## 15. Quyết định cần khóa trước implementation

Các mặc định trong tài liệu đã đủ để xây pilot, nhưng chưa phải quyền triển khai toàn pipeline. Khi chuyển sang implementation cần khóa:

1. Rubric v2: thang điểm từng công trình và completeness; giữ cố định profile=40% P+60% E, GVHD=trung bình KLTN có sử dụng skill đang xét và final=50% profile+50% GVHD.
2. Người có quyền duyệt identity, supervision và evidence; cách xử lý bất đồng.
3. Nguồn/quyền truy cập, ngân sách crawl và LLM; mô hình nếu thực sự dùng.
4. Decision_time từng cohort, availability proof được chấp nhận, strict hay proxy cho từng experiment.
5. Cấu hình metric/gate và thiết kế holdout mới nếu cần kết luận xác nhận.
6. Tích hợp feature score mới vào adapter nào, migration contract và cách bảo toàn checkpoint cũ.

Trong phạm vi hiện tại chỉ tạo tài liệu này. Chưa crawl thêm, chưa chấm điểm người thật, chưa thay CSV, chưa train RL và chưa thay trạng thái phục vụ.

## 16. Checklist rà soát tài liệu

- [x] Phân biệt skill agent, skill chuyên môn, skill đề tài và năng lực cá nhân.
- [x] Tính điểm độc lập trước; điểm GVHD hướng dẫn riêng theo từng skill.
- [x] Có công thức 40/60 và 50/50, trung bình các KLTN hợp lệ có sử dụng skill đang xét, unknown mask, dedup và attribution.
- [x] Có delta học kỳ, snapshot tích lũy và thời điểm khả dụng.
- [x] Có chặn self-leakage và rò rỉ outcome cuối kỳ.
- [x] Cấp ngoài continual RL; cấp trong feedback RL; thiếu feedback được ghi đúng.
- [x] Có baseline, forgetting, retention, external-test boundary và giới hạn kết luận.
- [x] Tái sử dụng repo; chưa thêm dependency hoặc hạ tầng không cần thiết.
