# PRD & SPEC — UniMatch v2: Dữ liệu bằng chứng sạch, đánh giá skill giảng viên, Continual RL (PPO vs DQN) không gate

Ngày: 06/11/2026 · Phiên bản: 2.0 (đề xuất) · Trạng thái: chờ duyệt, chưa sửa code.

Tài liệu liên quan:
- `PRD.md` và `SPEC.md` (30/10/2026) là nền tảng. Tài liệu này **thay thế riêng quy tắc** "candidate bị loại không được trở thành parent" (PRD §4, SPEC §3) cho dòng thí nghiệm v2.
- `docs/advisor_skill_semester_prd_spec.md` (v1.3) chứa công thức điểm skill giảng viên. Tài liệu này dùng lại công thức đó.
- `outputs/semester_rl_20261105/bao_cao_chi_tiet_rebuild.md` là báo cáo làm cơ sở: tag nhiễu, biến thể strict/topic, kết quả 12 round.

---

# PHẦN A — PRD

## 1. Bối cảnh và vấn đề

| # | Vấn đề quan sát được | Bằng chứng | Hệ quả |
|---|---|---|---|
| P1 | Bộ trích PDF cũ bật tag theo từ khóa, không xét ngữ cảnh: bảng viết tắt, liệt kê công cụ, hướng phát triển | Báo cáo §1, §3. Tỷ lệ tag ở 2025.1: AI từ 95.6% xuống 75.0%, C++ từ 30.9% xuống 4.4%, ML từ 76.5% xuống 30.9% | Cosine với GV AI bị đẩy cao, PPO học thiên lệch gán SV cho GV AI |
| P2 | 2024 (V1) là kỳ nhiễu nhất nhưng lại là nơi fit encoder và train trước tiên | Báo cáo §4.1. 2024 OLD: ML 66.9%, strict còn 22.8% | Model ban đầu học từ tín hiệu sai |
| P3 | Gate non-regression đặt ngưỡng 0 tuyệt đối (`max_old_drop = max_new_drop = 0`) | `src/features/semester_suite.py` L161 | Toàn bộ 8 round V2/V3 bị reject, checkpoint chốt vẫn là V1-R4 |
| P4 | V2/V3 chỉ train trên cohort của kỳ đó (`training_semester_ids: [term]`) | `semester_suite.py` L140–146 | Catastrophic forgetting: V3 tăng ở 2025.2 nhưng giảm 0.007–0.019/SV ở 2025.1 |
| P5 | Chưa có đánh giá skill chuyên môn giảng viên bằng cùng chuẩn bằng chứng | 13/17 GV không có domain label (báo cáo §10) | Không đo được thiên lệch, ma trận tương thích chỉ dựa vào text TF-IDF |

## 2. Mục tiêu

- **G1. Làm sạch dữ liệu:** dùng lại pipeline strict/topic (`evidence_context.py`) cho toàn bộ dữ liệu sinh viên 2024–2025.3. Áp cùng nguyên tắc DIRECT/TOPIC/BACKGROUND/LISTED/TOC_REF/FUTURE cho bằng chứng giảng viên.
- **G2. Đánh giá skill giảng viên:** tạo vector điểm skill có bằng chứng cho từng GV theo taxonomy 12 nhóm. Vector này được dùng làm đặc trưng matching và để đo thiên lệch.
- **G3. Continual RL hai cấp:**
  - Cấp ngoài là continual learning qua các học kỳ V1 → V2 → V3.
  - Cấp trong là các round RL trong từng học kỳ.
  - Chạy **PPO và DQN song song** như hai learner độc lập để đối chứng.
- **G4. Không từ chối model:** model của mỗi round luôn trở thành parent của round sau, kể cả khi điểm thấp hơn. Mọi mức tăng/giảm vẫn được đo và báo cáo, nhưng không chặn việc kế thừa.
- **G5. Ngân sách step:** mỗi round 128 × 1024 = **131,072 step**. Mỗi version có ít nhất 3 round. Chỉ train thêm round khi quy tắc gia hạn (§9) xác nhận model còn tăng.

## 3. Ngoài phạm vi

- Không đổi frontend, route API hoặc checkpoint đang phục vụ (serving).
- Không promote model v2 lên production. "Promote" trong tài liệu này chỉ có nghĩa là **làm parent cho nghiên cứu**.
- Không mở external test 2025.3 trước khi chốt cấu hình (§11.4).
- Không tạo nguyện vọng hoặc phản hồi giả rồi gọi là dữ liệu thật. Mock phải gắn nhãn `simulated_not_human`.
- Không tuyên bố RL tốt hơn Hungarian khi chưa có số đo mới.

## 4. Người dùng

| Vai trò | Nhu cầu trong v2 |
|---|---|
| Người nghiên cứu | Chạy strict/topic × PPO/DQN, xem đường cong học và forgetting, tái lập bằng hash |
| Người quản trị dữ liệu | Rà bằng chứng tag SV/GV, duyệt mẫu audit, sửa quy tắc ngữ cảnh |
| Điều phối viên | So sánh phương án RL với Hungarian/Greedy trên cùng quota |
| Giảng viên | Xem skill được suy ra kèm bằng chứng, phản biện nếu sai |

## 5. Yêu cầu chức năng

| ID | Yêu cầu | Nghiệm thu |
|---|---|---|
| FR-01 | Rebuild CSV sinh viên ở hai biến thể strict/topic cho 4 kỳ, mỗi tag có `evidence_refs` (trang, đoạn, loại ngữ cảnh) | 288 hồ sơ; `evidence_audit.json` đủ cho mọi tag; 0 tag thiếu bằng chứng |
| FR-02 | Bộ test hồi quy cho các ca nhiễu đã biết (bảng viết tắt, VS Code liệt kê C++, chatbot trong hướng phát triển, tên ngành KHMT) | Tất cả ca trong §6.3 cho kết quả "không bật tag" |
| FR-03 | Vector skill GV theo taxonomy, mỗi điểm có nguồn và phân rã (độc lập / hướng dẫn) | 17/17 GV có bản ghi; GV thiếu nguồn có `status = insufficient_evidence`, không gán 0 ngầm |
| FR-04 | Encoder và feature contract fit trên **V1-train sạch**, sau đó đóng băng cho V2/V3/test | Hash contract giống nhau ở mọi version |
| FR-05 | Cấp ngoài kế thừa checkpoint cuối cùng của version trước, không qua gate | `parent` của V(k+1)-R1 là round cuối của V(k) |
| FR-06 | Cấp trong: R1 → R2 → R3 bắt buộc, R4+ theo quy tắc gia hạn; mỗi round 131,072 step | `steps_added = 131,072` cho mỗi round; số round ≥ 3 |
| FR-07 | PPO và DQN dùng chung suite, seed, quota và đánh giá; không chia sẻ trọng số hoặc replay giữa hai thuật toán | Một lineage riêng cho mỗi thuật toán |
| FR-08 | Replay chống quên: V2 train trên 2025.1 + mẫu 2024; V3 train trên 2025.2 + mẫu 2024 và 2025.1 | `training_semester_ids` ghi đủ các kỳ; tỷ lệ replay nằm trong protocol |
| FR-09 | Mỗi round ghi điểm trên validation của **mọi kỳ đã gặp** (ma trận forgetting) dưới dạng chẩn đoán | `diagnostics.forgetting` có trong `report.json` |
| FR-10 | Baseline Hungarian, Greedy và Cosine-ranker chạy trên cùng problem với mọi round | Bảng so sánh có cả 3 baseline |
| FR-11 | Đánh giá theo nguyện vọng 2025.1 (Mẫu A/B) cho checkpoint cuối mỗi version | Top-1/Top-3/khi gán cả nhóm cho PPO và DQN |
| FR-12 | Báo cáo thiên lệch AI: tỷ lệ SV không-AI bị gán cho GV AI, trước và sau rebuild | Bảng OLD/strict/topic × PPO/DQN |

### 5.1 Yêu cầu phi chức năng

- **Tái lập:** mỗi round ghi seed, hash của suite/contract/parent/code, config và số step thực tế.
- **Bất biến:** không ghi đè round đã xong. Resume phải khớp protocol đã đóng băng.
- **Tài nguyên:** chạy trên CPU. Số đo thực tế của run 20261105 là khoảng 5.5 phút cho mỗi round PPO 131k step.
- **Minh bạch:** mọi số trong báo cáo phải có nguồn file. Số ước lượng phải ghi "~" và lý do.

---

# PHẦN B — SPEC KỸ THUẬT

## 6. Pipeline làm sạch dữ liệu

### 6.1 Sinh viên (dùng lại pipeline đã có)

```
PDF ─► hash/cache ─► extract (pdfplumber, OCR fallback)
    ─► evidence_context.py: DIRECT | TOPIC | BACKGROUND | LISTED | TOC_REF | FUTURE
    ─► taxonomy_v1.yaml (12 nhóm)
    ─► strict: DIRECT    | topic: DIRECT + TOPIC
    ─► data/student_evidence_20261106/{strict,topic}/{kỳ}/students_processed.csv
    ─► evidence_audit.json
```

Quy tắc bắt buộc mới:
1. Văn bản đưa vào TF-IDF (`student_text`) chỉ ghép **tag đã qua lọc**, không ghép danh sách từ khóa thô. Như vậy nhiễu bị loại khỏi cả hai đường: cờ concept và cosine (báo cáo §3.1).
2. Tiêu đề, tóm tắt và từ khóa luận văn vẫn được giữ, vì đó là văn bản do sinh viên viết về đề tài của mình.
3. Kỹ năng tự khai trong Excel (Mẫu B) được đưa vào **kênh riêng** `self_reported_*`. Kênh này không trộn với tag PDF và chỉ được dùng khi protocol khai báo `use_self_reported: true`.

### 6.2 Giảng viên — cùng chuẩn bằng chứng

| Nguồn | Ngữ cảnh được tính | Không tính |
|---|---|---|
| Bài báo (tiêu đề, abstract, toàn văn) | Phương pháp, thí nghiệm, đóng góp | Phần tham khảo, related work chỉ liệt kê |
| Repo GitHub | Ngôn ngữ/framework có code thật | README chỉ nhắc tên công nghệ |
| Hồ sơ trường | Hướng nghiên cứu khai báo (gắn nhãn `declared`) | Danh sách môn dạy chung chung |
| KLTN đã hướng dẫn | Tag **strict** của SV mà GV được xác minh là người hướng dẫn | KLTN của kỳ đang được đánh giá (tránh rò rỉ) |

Công thức điểm (theo `advisor_skill_semester_prd_spec.md` v1.3):
- `profile = 0.4 × predicted + 0.6 × evidence`
- `supervision = trung bình trên các KLTN hợp lệ có dùng skill đang xét`
- `final = 0.5 × profile + 0.5 × supervision`

Thiếu nguồn thì đặt `known = false`. Giá trị unknown được che bằng mask, không coi là 0.

Đầu ra là `advisor_skill_vector.json`, kích thước 17 GV × (12 nhóm × tag). Mỗi ô gồm `{score, known, evidence_ids[], independent_part, supervision_part}`.

### 6.3 Bộ test hồi quy cho dữ liệu (bắt buộc pass trước khi train)

| Ca | Đầu vào mẫu | Kỳ vọng |
|---|---|---|
| Bảng viết tắt | "AI — Artificial Intelligence" | không bật AI |
| Liệt kê IDE | "VS Code hỗ trợ JavaScript, Python, C/C++, Java" | không bật C++ |
| Hướng phát triển | "Hướng phát triển: tích hợp AI chatbot" | không bật AI |
| Tên ngành | "Ngành: Khoa học máy tính" | không bật ML |
| So sánh lý thuyết | "Python chậm hơn C++" | không bật C++ |
| Triển khai thật | "Huấn luyện CNN, accuracy 92.3% trên test" | bật ML, deep_learning (strict) |
| Chủ đề | "Nghiên cứu ứng dụng học máy trong y tế" | bật ở topic, không bật ở strict |

### 6.4 Ma trận tương thích SV–GV

```
compat[s, a] = w_text × cosine_tfidf(s, a) + w_skill × skill_overlap(s, a)
skill_overlap = Σ_t flag_s[t] · score_a[t] · known_a[t]  /  Σ_t flag_s[t]   (chia 0 → unknown)
```

- Bản đầu dùng `w_text = 1.0, w_skill = 0.0` để giữ khả năng so sánh với run 20261105. Biến thể B dùng `w_text = 0.5, w_skill = 0.5`. Hai giá trị này chốt trong protocol trước khi train và **không tune theo test**.
- Encoder chỉ fit trên V1-train (strict hoặc topic), rồi đóng băng.

## 7. Continual RL hai cấp — không gate

### 7.1 Cấu trúc

```
Cấp ngoài (continual, qua học kỳ)
  V1 (2024) ──────────► V2 (2025.1) ──────────► V3 (2025.2) ──► [freeze] ──► test 2025.3
   │                     │                        │
Cấp trong (round RL trong kỳ, cùng cohort + replay)
   R1→R2→R3[→R4…]        R1→R2→R3[→R4…]           R1→R2→R3[→R4…]
   mỗi round 131,072 step, khởi tạo từ round ngay trước (luôn luôn)

Hai lineage độc lập, chạy song song:  PPO ═══  và  DQN ═══
```

### 7.2 Quy tắc kế thừa (thay cho gate cũ)

| Trước (run 20261105) | Sau (v2) |
|---|---|
| `decision ∈ {accepted, rejected, inconclusive}` | `decision = "promoted_unconditional"` cho mọi round hoàn thành an toàn |
| Round bị rejected thì parent giữ checkpoint accepted cũ, ghi ledger retention | Parent của round k+1 **luôn** là checkpoint cuối của round k |
| `max_old_drop = max_new_drop = 0` dùng để chặn | Delta và forgetting chỉ là **chẩn đoán**, ghi vào `report.json` |

Ngoại lệ duy nhất là round **hỏng kỹ thuật**: NaN trong trọng số, vi phạm action mask hoặc quota, phương án không khả thi, hoặc hash không khớp. Khi đó round được đánh dấu `failed_technical` và chạy lại với seed giữ nguyên. Không được bỏ qua lặng lẽ. Một model tệ hơn về điểm **không** được tính là hỏng kỹ thuật.

Ngoài lineage chính, có thể ghi thêm `best_validation_checkpoint` cho mỗi version để làm tham chiếu so sánh. Checkpoint này **không** được dùng làm parent.

### 7.3 Ngân sách step

| Đơn vị | Công thức | Tối thiểu |
|---|---|---|
| 1 round | 128 × 1024 | **131,072** |
| 1 version (≥ 3 round) | 3 × 131,072 | **393,216** |
| 1 lineage (V1+V2+V3) | 3 × 393,216 | **1,179,648** |
| 1 biến thể dữ liệu (PPO + DQN) | 2 × 1,179,648 | 2,359,296 |
| Toàn bộ thí nghiệm (strict + topic) | 2 × 2,359,296 | 4,718,592 |

Trả lời câu hỏi: **đúng, mỗi version có ít nhất 3 × 128 × 1024 = 393,216 step cho mỗi thuật toán.** Nếu gia hạn thì cộng thêm 131,072 step cho mỗi round thêm, tối đa theo §9.

Lưu ý so với run cũ: các round bị rejected **không** cộng step vào trọng số (`added_to_weight_steps: False`), nên V2 và V3 cũ thực chất vẫn dừng ở 655,360 step. Trong v2, mọi step đều được cộng dồn vào lineage.

### 7.4 Dữ liệu train mỗi version (replay chống quên)

| Version | Cohort chính | Replay | Validation chính | Validation chẩn đoán |
|---|---|---|---|---|
| V1 | 2024 train (87) | — | 2024 val (19) | — |
| V2 | 2025.1 train (46) | 2024 train | 2025.1 val (16) | 2024 val |
| V3 | 2025.2 train (45) | 2024 + 2025.1 train | 2025.2 val (11) | 2024 val, 2025.1 val |

- Tỷ lệ chọn episode được cố định là 50% cohort chính và 50% replay, chia đều giữa các kỳ cũ. Thực hiện bằng cách truyền nhiều problem vào `MatchingEnv([...])` kèm trọng số chọn episode. Nếu env chưa hỗ trợ trọng số thì nhân bản problem theo tỷ lệ.
- **PPO:** rollout mới trên env có replay. Không cần replay buffer.
- **DQN:** dùng `StratifiedReplay` trong `src/rl/continual_dqn.py` (nửa batch từ nguồn cũ, nửa từ nguồn hiện tại). Chỉ dùng khi contract trùng khớp (`validate_continual_contracts`).
- Gọi R1 của V2 là "tiếp tục train" vì trọng số kế thừa từ V1-R_last.

### 7.5 Siêu tham số (đóng băng trong protocol)

| | PPO (`src/rl/rebuild_ppo.py`) | DQN (`src/rl/rebuild_dqn.py`) |
|---|---|---|
| Mạng | MLP [128, 128] | MLP [128, 128], Double DQN có mask |
| LR | 3e-4 ở V1; **1e-4 ở V2/V3** (fine-tune) | 1e-3 ở V1; **3e-4 ở V2/V3** |
| Rollout / buffer | n_steps 256, batch 64, 5 epoch | buffer 10,000, batch 64, learning_starts 128 |
| Khác | gamma 0.99 | gamma 0.99, target_update 200, train_freq 4 |
| Seed | 42 (chính); 43–46 nếu đủ thời gian (§11.3) | như PPO |
| Eval interval | 8,192 step | 8,192 step |

Giảm LR ở V2/V3 nhằm hạn chế trôi trọng số. Phải ghi rõ đây là thay đổi so với run 20261105.

Reward giữ như báo cáo §6.3 (cosine + 0.10·pref + 0.15·Δload + 1.0 khi xong cohort), với preference = 0 khi inference. Thay `cosine` bằng `compat` (§6.4) khi chạy biến thể B.

## 8. Thay đổi code dự kiến (chưa thực hiện)

| File | Thay đổi | Ghi chú |
|---|---|---|
| `src/features/semester_suite.py` L140–146, L161 | Thêm replay vào `train` và `training_semester_ids`. Thay `decision_thresholds` bằng `{'mode': 'unconditional', ...}`. Thêm `lr_schedule` theo version | Giữ đường cũ khi `mode = 'gated'` để tái lập run 20261105 |
| `src/rl/nested_learning.py` ~L560–566 | Khi `mode == 'unconditional'`: `decision = 'promoted_unconditional'` nếu an toàn kỹ thuật, ngược lại `failed_technical`. Vẫn tính `delta` và `forgetting` | Không xóa nhánh gated |
| `scripts/run_semester_rl.py` | Thêm `--algorithm {ppo,dqn}`, `--min-rounds 3`, `--max-rounds 6`, `--extend-rule` (§9). Bỏ ràng buộc `rounds in (3,4)`. Parent luôn là `folder` khi unconditional | `validate_budget` giữ ngưỡng ≥ 100,000 |
| `src/rl/model_retention.py` | Không gọi khi unconditional | — |
| `src/environment/rebuild_env.py` | (Nếu cần) thêm `episode_weights` cho replay | Có test riêng |
| `src/features/advisor_skill_scores.py` | Xuất `advisor_skill_vector.json` theo §6.2 | Dùng lại code đã có |
| `scripts/measure_evidence_rebuild.py` | Thêm bảng thiên lệch AI, ma trận forgetting, PPO và DQN | — |
| `tests/` | Test: parent luôn là round trước; round tệ hơn vẫn được promote; `failed_technical` thì chạy lại; tổng step ≥ 3 × 131,072 mỗi version; replay có đủ kỳ cũ; các ca hồi quy §6.3 | Bắt buộc pass |

## 9. Quy tắc gia hạn round ("nếu còn tăng thì train tiếp")

Sau mỗi round k ≥ 3 của một version, kiểm tra trên **validation chính** của version đó:

```
gain_k   = score(R_k) − score(R_{k−1})
slope_k  = hệ số góc hồi quy tuyến tính trên các điểm eval (mỗi 8,192 step) trong round k
EXTEND nếu (gain_k > ε  HOẶC  slope_k > 0 với p < 0.1)  VÀ  k < MAX_ROUNDS
ε = 0.002 / SV,   MAX_ROUNDS = 6   (tối đa 6 × 131,072 = 786,432 step / version)
```

- Quy tắc này **chỉ** quyết định có train thêm hay không. Nó không quyết định giữ hay bỏ model.
- ε và MAX_ROUNDS được chốt trong `protocol.json` trước khi chạy và không đổi giữa chừng.
- Validation chỉ có 11–19 SV nên điểm dao động lớn. Nếu chạy nhiều seed, dùng trung bình các seed để quyết định gia hạn, và mọi seed phải dùng cùng số round.
- PPO và DQN gia hạn độc lập. Báo cáo phải ghi số round thực tế của từng bên để so sánh ở cùng tổng step khi cần (§10.2).

## 10. Đánh giá

### 10.1 Metric

| Nhóm | Metric | Nguồn |
|---|---|---|
| Chất lượng ghép | objective/SV, cosine/compat trung bình, unmatched, tỷ lệ dùng quota | validation mỗi kỳ |
| Continual | Ma trận R[i, j] = điểm sau version i trên validation của kỳ j; **BWT** = trung bình (R[3, j] − R[j, j]) với j < 3; **FWT** = R[i−1, i] − điểm Cosine-ranker trên kỳ i | §7.4 |
| Hội tụ | Đường cong theo step (mỗi 8,192), số round đã dùng | report.json |
| Nguyện vọng | Top-1, Top-3, khi gán cả nhóm (Mẫu A 19 SV, Mẫu B 10 SV, 2025.1) | §9 báo cáo cũ |
| Thiên lệch AI | % SV không có tag AI (strict) bị gán cho 4 GV AI; so với tỷ lệ của Hungarian | §10 báo cáo cũ |
| Skill GV | Coverage (`known` / tổng), số bằng chứng mỗi GV, độ khớp với domain khai báo | FR-03 |

### 10.2 Ma trận thí nghiệm

| Trục | Giá trị |
|---|---|
| Dữ liệu | OLD (tham chiếu, chỉ đọc số cũ) · **strict** · **topic** |
| Thuật toán | **PPO** · **DQN** · Hungarian · Greedy · Cosine-ranker |
| Compat | A: text only · B: text + skill GV (chỉ chạy sau khi A xong) |
| Seed | 42 bắt buộc; 43–46 tùy chọn |

So sánh PPO với DQN ở **cùng tổng step** (cắt tại cùng mốc nếu số round khác nhau) **và** ở checkpoint cuối của mỗi bên.

### 10.3 Thứ tự quyết định

1. Strict hay topic: so trên validation V1–V3 (PPO và DQN, seed 42) và trên Mẫu A/B. Chênh không rõ thì chọn **strict** (precision cao hơn).
2. Compat A hay B: so trên cùng biến thể đã chọn.
3. Đóng băng cấu hình, rồi mở **external test 2025.3 một lần** cho PPO-final, DQN-final, Hungarian và Greedy.

## 11. Tiêu chí nghiệm thu

- [ ] Các ca hồi quy §6.3 pass. `evidence_audit.json` đủ 288 hồ sơ.
- [ ] `advisor_skill_vector.json` có 17/17 GV, unknown được đánh dấu rõ.
- [ ] Mỗi lineage (2 biến thể × 2 thuật toán) có ≥ 3 round/version, mỗi round đúng 131,072 step, tổng ≥ 1,179,648 step.
- [ ] Không có round nào có `decision = rejected`. Parent của mọi round là round ngay trước. Có test chứng minh.
- [ ] Ma trận forgetting, BWT/FWT, đường cong, nguyện vọng và thiên lệch AI có đủ cho PPO và DQN.
- [ ] External test chỉ mở sau khi cấu hình đã đóng băng, có hash protocol trước thời điểm mở.
- [ ] Báo cáo ghi rõ số đo thật và số ước lượng (~); không tuyên bố RL > Hungarian nếu số liệu không cho thấy.

## 12. Rủi ro

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Không gate thì model cuối có thể tệ hơn model giữa | Cao | Ghi `best_validation_checkpoint` để tham chiếu; báo cáo đường cong và BWT; giải thích đây là lựa chọn có chủ đích của protocol |
| Validation nhỏ (11–19 SV) gây nhiễu | Cao | Đa seed; khoảng tin cậy bootstrap; ε trong quy tắc gia hạn |
| DQN kém ổn định với action có mask 17 lựa chọn | Trung bình | Double DQN có mask sẵn; theo dõi loss/Q; không tune theo test |
| Replay làm chậm việc thích nghi với kỳ mới | Thấp | Tỷ lệ 50/50 cố định; báo cáo FWT |
| Skill GV thiếu nguồn (13/17 không có domain) | Trung bình | Mask unknown; compat B chỉ là biến thể phụ |
| Thời gian chạy (≥ 36 round × ~5.5 phút, seed 42) | Thấp | Khoảng 3.3 giờ cho 4 lineage; chạy PPO và DQN song song |

## 13. Kế hoạch thực hiện

| Bước | Việc | Đầu ra |
|---|---|---|
| 1 | Chạy test hồi quy §6.3, chốt snapshot strict/topic | `evidence_audit.json`, manifest hash |
| 2 | Xuất vector skill GV | `advisor_skill_vector.json` |
| 3 | Sửa code theo §8, viết test | Thay đổi code + test pass |
| 4 | Dựng suite strict/topic có replay | `outputs/semester_rl_v2_{strict,topic}/suites` |
| 5 | Train 4 lineage (strict/topic × PPO/DQN), seed 42 | `training/{ppo,dqn}/V*/R*` |
| 6 | Đo, chọn strict/topic, rồi compat A/B | `measure_report.json` |
| 7 | Đóng băng, mở test 2025.3, viết báo cáo | `bao_cao_v2.md` |

Lệnh dự kiến (PowerShell; các cờ `--algorithm`, `--min-rounds`, `--max-rounds`, `--decision-mode` **chưa tồn tại**, sẽ thêm ở bước 3):

```powershell
python scripts/run_semester_rl.py `
  --suites outputs/semester_rl_v2_strict/suites `
  --output outputs/semester_rl_v2_strict/training/ppo `
  --algorithm ppo --steps 131072 --min-rounds 3 --max-rounds 6 --decision-mode unconditional
```

---

*Tài liệu đề xuất, chưa áp dụng. Các ngưỡng ε = 0.002, MAX_ROUNDS = 6, tỷ lệ replay 50/50 và LR fine-tune là giá trị đề xuất; cần chốt trong `protocol.json` trước khi chạy.*
