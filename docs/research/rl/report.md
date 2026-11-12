# Báo cáo RL hai cấp

**Cập nhật thí nghiệm 4R:** completed · 24/24 fit. Bộ phản hồi mô phỏng được người dùng cho phép; phần cuối báo cáo có bảng R1–R4 và biểu đồ mới. Các phần thí nghiệm 131.072 bước/fit phía trước là kết quả cũ, được giữ để đối chiếu.


## Kết quả chính

**Đã hoàn tất 10 lượt fit, mỗi lượt 131.072 bước, tổng 1.310.720 bước thực tế; 170 mốc đo và 10 biểu đồ PNG/SVG. 101 tests đạt.**

V1 của PPO/DQN được chấp nhận làm checkpoint nghiên cứu. Candidate V2 và V3 của cả hai learner bị từ chối theo tiêu chí đã chốt; hệ thống giữ đúng trọng số V1 và vẫn cho kỳ sau học tiếp qua sổ kế thừa. Không dùng trọng số đã bị từ chối và không train lại lineage từ đầu.

Kết quả chưa chứng minh RL hai cấp tốt hơn Hungarian hoặc train từ đầu. Điểm lên/xuống theo step, và thêm bước có thể làm giảm chất lượng trên cohort mới hoặc cũ. DQN được giữ có điểm test cao hơn PPO được giữ trên cả ba cohort, nhưng cả hai vẫn thấp hơn Hungarian. Một seed và holdout nhỏ chưa đủ kết luận tổng quát.

Code hỗ trợ vòng preference/eligibility/score trong kỳ và kế thừa/rollback liên kỳ; cơ chế này đã kiểm tra bằng fixture tổng hợp. **Dữ liệu nghiên cứu hiện chỉ có nguồn ban đầu mỗi kỳ, chưa có phản hồi người thật trong kỳ; không biến các mốc step thành vòng feedback giả.** Model phục vụ hiện tại chưa được thay.


## Thiết kế thí nghiệm và mốc chốt protocol

Mục tiêu: chạy mô hình thật trên dữ liệu mới, đo khả năng kế thừa giữa các kỳ và so sánh diễn biến theo số bước. Dùng một báo cáo này xuyên suốt quá trình; các JSON/checkpoint/biểu đồ là artifact máy đọc.

- Branch `susois/nested-rl`; nguồn mới trong `data_rebuild/nested_rl_20261028/20261027T190955Z`.
- Giữ nguyên raw/gold/model cũ và đợt smoke 1.024 bước. Dùng lại đúng suite đã đóng băng của nguồn mới để so sánh cùng dữ liệu/encoder/split.
- Ngân sách cố định **131.072 bước cho mỗi lần fit**, seed 42; đo validation mỗi **8.192 bước**, cộng mốc ban đầu và cuối.
- PPO và DQN chạy trong hai process độc lập; mỗi process một CPU thread để không chia sẻ RNG.
- Kế thừa checkpoint được chấp nhận gần nhất. Khi candidate bị từ chối, sổ kế thừa ghi phiên bản dữ liệu hiện hành trỏ về trọng số cũ; kỳ sau tiếp tục từ trọng số đó, không dùng candidate bị từ chối hoặc khởi tạo lại model.
- Chọn checkpoint cuối ngân sách, không chọn mốc có validation đẹp nhất. Cho phép chấp nhận không suy giảm; chỉ gọi cải thiện khi delta > 0. Không cho giảm mục tiêu mới hoặc holdout cũ.
- Đối chứng cùng ngân sách: train từ đầu V2 và V3, dùng cùng input/seed; ghi rõ đây là đối chứng, không phải continual RL.
- Vòng phản hồi trong cùng kỳ chỉ mở khi có feedback thật đã được áp dụng vào preference/ràng buộc. Hiện chưa có; các mốc step là tối ưu tiếp, không phải bốn tín hiệu giả.
- Curve chỉ dùng train/validation. Final test mở một lần sau khi hoàn tất training và đóng băng lựa chọn; không retune dựa vào test.
- Kết quả một seed là điểm đo, không có khoảng tin cậy nhiều seed. Nhiều step là lặp lại cohort nhỏ, không phải thêm 131 nghìn sinh viên.

## Dữ liệu và phạm vi kết luận

Học kỳ lấy ngày ở trang 1–2: tháng 1–5 là kỳ `.2` của năm học trước; 6–8 là `.3`; 9–12 là `.1` của năm đó. Hè `2024.3` gộp vào training `2025.1`. Nguồn mới gồm 38 hồ sơ giảng viên, 413 mục công bố theo hồ sơ và 218 tài liệu sinh viên đọc lại từ bytes gốc; không ghi đè dữ liệu cũ.

Train/validation/test lần lượt V1=24/4/4, V2=56/9/14, V3=43/7/11. V4 chỉ một hồ sơ nên chưa đủ chia split. Encoder chỉ fit train V1 và đóng băng qua kỳ; thông tin năng lực đầu kỳ, nguyện vọng và outcome thật chưa có.

Đây là mô phỏng hồi cứu bằng tiêu đề khóa luận và trích dẫn công bố, chưa chứng minh thông tin có sẵn ở thời điểm phân công trong lịch sử. Quota được dựng riêng theo split; validation nhỏ chỉ có quota dương cho 4/9/7 giảng viên đầu registry, không kiểm chứng tổng quát hóa trên mọi giảng viên. Mask/ràng buộc cứng bảo đảm phần lớn tính hợp lệ; zero violations không tự chứng minh model học fairness.

Hungarian giải tối ưu chính objective tuyến tính tĩnh đang dùng. RL có thể thu hẹp khoảng cách hoặc học policy suy luận nhanh, không thể vượt nghiệm tối ưu trên cùng bài toán nếu mọi phép đo đúng. Không gọi điểm proxy là accuracy học vụ.

## Mô hình và hai cấp cập nhật

State có 343 chiều, gồm 9 nhóm thông tin cho registry 38 giảng viên và một tỷ lệ sinh viên còn lại; action là chọn giảng viên còn khả thi. Model dùng MLP 128×128. PPO: rollout 256, batch 64, 5 epochs/update, learning rate 0,0003; DQN: replay 10.000, batch 64, cập nhật mỗi 4 bước, target mỗi 200 bước, learning rate 0,001. Gamma 0,99. DQN dùng epsilon 0,2 xuống 0,05 trong mỗi lần fit. Không đổi cấu hình sau khi nhìn điểm test.

Cấp ngoài kế thừa policy, optimizer và counter giữa các kỳ; PPO lấy rollout mới, DQN loại replay khi ngữ nghĩa snapshot thay đổi. Cấp trong hỗ trợ dữ liệu preference/eligibility/score có nguồn thật, hash và thay đổi `old/new` khớp input. Không chấp nhận chỉ thêm một file “feedback” mà input không đổi.

Sổ giữ model phân biệt **nguồn trọng số** với **bối cảnh logic hiện hành**: nếu V2 bị từ chối và vẫn dùng V1 thì V3 nhận đúng trọng số/optimizer/counter V1, còn lịch chuyển kỳ là V2→V3. Số bước đã chi cho candidate V2 thất bại được đếm vào chi phí thí nghiệm, không cộng giả vào tuổi của checkpoint được giữ. Luồng này được chốt trước kết quả cuối V2; không thay learning rate, ngân sách hoặc gate sau khi xem kết quả. Pha train đầu và pha tiếp tục có manifest riêng, chưa mở test ở giữa.

Đã chạy test tích hợp **bốn vòng trong kỳ rồi chuyển kỳ** trên fixture tổng hợp: khởi tạo → preference → giảng viên sửa eligibility → điều phối sửa score → kỳ tiếp theo kế thừa vòng 4. Test kiểm tra trọng số, counter, replay, hash, holdout và parity. Đây là bằng chứng kiểm tra phần mềm, không phải dữ liệu phản hồi thật và không nằm trong các đường cong nghiên cứu.

Mỗi điểm return lấy trung bình tối đa 100 episode train vừa hoàn tất, chia theo số sinh viên; loss PPO/DQN có thang riêng. Return có completion bonus và shaping, không đồng nhất objective validation. Các biểu đồ dùng điểm thực, không nội suy điểm thiếu hoặc tự thêm confidence interval.

## Kết quả validation cuối ngân sách

Mỗi parent được chấm lại trên **cùng bối cảnh mới** với candidate. Không lấy điểm V1 trên cohort V1 trừ điểm V2 trên cohort V2. Đối chứng khởi tạo policy từ đầu nhưng dùng cùng encoder/suite đóng băng; V1 là bootstrap dùng chung, không có một lượt đối chứng V1 thứ hai.

| Learner | Phiên bản | Parent trên kỳ mới | Candidate 131k | Từ đầu 131k | Hungarian | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| PPO | V1 | — | 0.108544 | 0.108544 | 0.119531 | accepted |
| PPO | V2 | 0.119388 | 0.112900 | 0.117858 | 0.133791 | rejected |
| PPO | V3 | 0.118495 | 0.122640 | 0.135579 | 0.146125 | rejected |
| DQN | V1 | — | 0.118531 | 0.118531 | 0.119531 | accepted |
| DQN | V2 | 0.110605 | 0.106005 | 0.114151 | 0.133791 | rejected |
| DQN | V3 | 0.139567 | 0.131340 | 0.133837 | 0.146125 | rejected |

Lý do từ chối cụ thể:

- **PPO V2:** giảm 0,006488 trên bối cảnh mới, dù điểm V1 cũ tăng.
- **DQN V2:** giảm 0,004600 trên bối cảnh mới; không đạt điều kiện nhận model mới.
- **PPO V3:** tăng 0,004145 trên bối cảnh V3, nhưng giảm 0,008966 trên holdout V2; bị từ chối để giữ mục tiêu cũ.
- **DQN V3:** giảm 0,008227 trên bối cảnh mới và giảm 0,022441 trên holdout V1.

V3 thực sự đã được train từ trọng số V1 được giữ qua logical V2. Đó là tiếp tục policy được chấp nhận gần nhất, không phải dùng candidate V2 thất bại hoặc reset ngẫu nhiên. Sổ giữ model cũng hỗ trợ trường hợp vòng trong kỳ bị từ chối: bối cảnh/tín hiệu vẫn cập nhật, trọng số chỉ lấy từ bản đã chấp nhận.

## Bước training và chi phí bị loại

| Lượt | Counter trước fit | Bước thêm | Counter candidate cuối | Checkpoint được giữ |
| --- | --- | --- | --- | --- |
| V1, mỗi learner | 0 | 131.072 | 131.072 | V1 |
| V2 kế thừa, mỗi learner | 131.072 | 131.072 | 262.144 | V1: vẫn 131.072 bước |
| V3 qua sổ giữ model, mỗi learner | 131.072 | 131.072 | 262.144 | V1: vẫn 131.072 bước |
| V2/V3 từ đầu, mỗi learner | 0 | 131.072 | 131.072 | Đối chứng độc lập |

6 lượt kế thừa/bootstrap dùng 786.432 bước; 4 đối chứng độc lập dùng 524.288 bước. Tổng 1.310.720. Trong nhánh kế thừa, 524.288 bước đã chi cho bốn candidate không được nhận; chi phí này không được cộng giả vào tuổi checkpoint V1.

Đối chứng bằng nhau về **ngân sách bổ sung**, không bằng tổng chi phí lịch sử: warm start đã có 131.072 bước pretrain; scratch policy chưa có. Cả hai dùng chung encoder đã fit ở train V1. Số bước là số transition mô phỏng, không phải số sinh viên mới.

## Final test mở một lần sau khi đóng băng lựa chọn

Test có 4/14/11 hồ sơ ở V1/V2/V3. Điểm là objective tài liệu hồi cứu trên mỗi sinh viên, **không phải accuracy, điểm khóa luận hoặc mức hài lòng**. Bảng sau là model được chọn theo validation trước khi mở test.

| Test | n | PPO được giữ | DQN được giữ | Hungarian | Greedy | Random seed42 |
| --- | --- | --- | --- | --- | --- | --- |
| V1 | 4 | 0.105690 | 0.109519 | 0.113652 | 0.081137 | 0.056308 |
| V2 | 14 | 0.130587 | 0.148416 | 0.191483 | 0.144405 | 0.111890 |
| V3 | 11 | 0.134744 | 0.137924 | 0.193676 | 0.169539 | 0.122965 |

Cả hai learner đều dùng checkpoint V1 tại ba bối cảnh test vì candidate V2/V3 không qua gate. DQN được giữ hơn Greedy ở V1/V2 nhưng thấp hơn Greedy ở V3; không có chiến thắng đồng đều trước các baseline.

| Learner | Test | Warm candidate | Scratch candidate | Warm − scratch |
| --- | --- | --- | --- | --- |
| PPO | V2 | 0.147060 | 0.148835 | -0.001775 |
| PPO | V3 | 0.145719 | 0.136273 | +0.009446 |
| DQN | V2 | 0.145319 | 0.139065 | +0.006255 |
| DQN | V3 | 0.124945 | 0.122175 | +0.002769 |

Ba trong bốn cặp warm/scratch có điểm test nghiêng về warm, một cặp nghiêng về scratch. Đây là điểm đo một seed, chưa chứng minh ưu thế thống kê. Candidate PPO V2/V3 có thể cao hơn model được giữ trên test; **không đổi lựa chọn sau khi thấy điều này**. Nếu chọn lại dựa trên test thì test không còn độc lập.

Lượt mở test ghi `selection_changed=false`, `learning_performed=false`, 14 cặp checkpoint–holdout duy nhất. Một checkpoint có thể xuất hiện dưới nhiều vai trò trên biểu đồ, nhưng dùng lại kết quả cache; không coi các cột trùng checkpoint là các mẫu độc lập.

## Biểu đồ

Đường liền: nhánh bootstrap/kế thừa; đường đứt: policy train từ đầu; đường chấm: parent cố định. Mỗi mốc validation cách 8.192 bước, điểm cuối sau update cuối ngân sách. Không chọn checkpoint tốt nhất giữa chừng. Các panel V4 trống có chủ ý vì không đủ dữ liệu, không phải đã train rồi bị mất hình.

### Quy ước đọc chung

- **Step:** một quyết định gán một sinh viên cho một giảng viên trong môi trường mô phỏng. Một episode hoàn thành cả cohort. Cùng các sinh viên được dùng qua nhiều episode; 131.072 step không phải 131.072 sinh viên mới.
- **Objective / student:** tổng utility của các cặp được phân công, chia số sinh viên. Utility hiện tại là `similarity + 0,1 × preference`; vì preference thật chưa có nên điểm thực nghiệm này chủ yếu là độ tương đồng văn bản. Giá trị 0,12 không có nghĩa đúng 12% hoặc được 1,2/10 điểm khóa luận.
- **Validation:** dữ liệu ngoài train, được dùng theo dõi và quyết định nhận model. **Final test:** tập độc lập chỉ chấm sau khi đóng băng lựa chọn, không xuất hiện trong curve training.
- **Màu của đường:** xanh dương là PPO; tím là DQN; xanh lá là Hungarian; cam là Greedy; xám là Random. Kiểu đường phân biệt kế thừa, train từ đầu và parent cố định; màu không biểu thị accepted/rejected.
- **Parent:** model được chấp nhận đang giữ trước lượt fit, được chấm lại trên đúng cohort mới. So candidate với parent trong cùng panel, không lấy điểm khác năm để tính mức cải thiện.
- **V1/V2/V3:** các snapshot training, không phải các mốc step hoặc bốn vòng feedback. V1 gom lịch sử đến hết 2024; V2 là nhóm 01–05/2025; V3 gom 06–12/2025. V4 chưa đủ dữ liệu.
- **Accepted/rejected:** quyết định theo gate đã chốt. Candidate có thể tăng trên kỳ mới nhưng vẫn bị từ chối nếu làm giảm một holdout cũ. `Accepted` ở bootstrap/đối chứng từ đầu không có phép so với parent và không chứng minh đã vượt Hungarian.

Mỗi panel có cohort, quota và tập giảng viên khả dụng riêng. Trục dọc cũng có thể khác nhau; chỉ so các phương pháp trong cùng panel. Các đường nối các mốc đo thật, không bổ sung quan sát giữa hai mốc. Không có dải tin cậy vì hiện chỉ chạy một seed.

### Điểm validation theo bước thêm

**Trục X** là số bước thêm trong riêng lượt fit hiện tại, từ 0 đến 131.072. **Trục Y** là objective trung bình trên validation; càng cao càng tốt. Chấm trên đường là mốc đo thật, không phải một lần nhận feedback mới. Đường chấm ngang là parent giữ nguyên trọng số, được chấm trên cùng dữ liệu với đường đang train.

Cách đọc: lấy một panel, so đường learner với parent và các baseline ở cùng mốc. Cao hơn parent cho thấy điểm kỳ mới tốt hơn tại mốc đó; cao hơn ở giữa quá trình chưa đủ để nhận model vì protocol chọn checkpoint cuối và còn kiểm tra holdout cũ.

Ở V1, DQN kết thúc khoảng 0,118531, PPO khoảng 0,108544, còn Hungarian khoảng 0,119531. DQN gần nghiệm tối ưu hơn PPO trên validation V1. Các đường đổi lên/xuống cho thấy train thêm không bảo đảm tăng đều. Validation chỉ 4/9/7 sinh viên nên thay đổi vài lựa chọn có thể tạo bước nhảy lớn; đường phẳng cũng chưa chứng minh hội tụ.

![Điểm validation theo bước thêm](../../assets/rl_2_cap/validation_steps.png)

[Bản SVG để phóng lớn](../../assets/rl_2_cap/validation_steps.svg)

### Bộ đếm bước của lineage

Trục Y giống hình trước, nhưng **trục X cộng cả số bước đang nằm trong checkpoint parent**. Đây là tuổi training của nhánh trọng số, không phải tổng chi phí mọi thí nghiệm.

V1 chạy từ 0 đến 131.072. Candidate V2 chạy từ 131.072 đến 262.144 rồi bị từ chối. Vì vậy candidate V3 lại bắt đầu ở 131.072 của V1 được giữ, sau đó tới 262.144. Điều này không phải train V3 từ đầu; nó là bỏ trọng số V2 thất bại và tiếp tục đúng checkpoint đã chấp nhận.

Các đối chứng từ đầu bắt đầu ở 0. Tổng 1.310.720 bước của cả thí nghiệm không có nghĩa một model đã học liên tục 1.310.720 bước.

![Bộ đếm bước của lineage](../../assets/rl_2_cap/validation_cumulative_steps.png)

[Bản SVG để phóng lớn](../../assets/rl_2_cap/validation_cumulative_steps.svg)

### Khoảng cách tới Hungarian

Trục X là bước thêm; **trục Y = điểm Hungarian − điểm model** trên cùng validation và ràng buộc. Càng gần 0 càng tốt; 0 nghĩa là model đạt cùng objective tối ưu trong bối cảnh đó.

Ví dụ cuối V1: regret DQN xấp xỉ 0,001000; regret PPO xấp xỉ 0,010987. DQN mất ít điểm hơn so với Hungarian ở case này. Một đường regret đi lên nghĩa là model đang rời xa mức tối ưu, dù loss train có thể đang giảm.

Hungarian giải tối ưu objective tuyến tính hiện dùng với toàn bộ ma trận điểm; policy RL không thấy đầy đủ điểm tương lai. Vì vậy đường này đo khoảng cách đến oracle của bài toán mô phỏng, không đo sai số điểm khóa luận hoặc độ hài lòng. Với đúng cùng objective/ràng buộc, không kỳ vọng RL vượt nghiệm tối ưu này.

![Khoảng cách tới Hungarian](../../assets/rl_2_cap/hungarian_regret.png)

[Bản SVG để phóng lớn](../../assets/rl_2_cap/hungarian_regret.svg)

### Return trên train

**Trục X** là bước thêm. **Trục Y** là trung bình tổng reward của tối đa 100 episode vừa hoàn tất, chia số sinh viên trong cohort train. Đây là đường đã lấy trung bình cửa sổ, không phải từng episode riêng.

Các đường tăng khá rõ cho thấy policy đang nhận nhiều reward hơn trong môi trường train. Ở V2/V3, nhiều đường kế thừa bắt đầu cao hơn đối chứng từ đầu; điều này phù hợp với việc đã có trọng số cũ, nhưng chưa chứng minh ưu thế trên dữ liệu ngoài train.

Reward có completion bonus và shaping, còn objective validation là utility không chiết khấu. Train cũng có exploration và thứ tự sinh viên được xáo trộn. Bởi vậy return tăng trong khi validation dao động không mâu thuẫn. Không so raw return giữa hai panel khác cohort để kết luận model năm sau tốt hơn.

![Return trên train](../../assets/rl_2_cap/training_return.png)

[Bản SVG để phóng lớn](../../assets/rl_2_cap/training_return.svg)

### Loss của PPO và DQN

**Trục X** là bước thêm; **trục Y** là loss được learner ghi sau cập nhật. Màu trong hình này phân biệt phiên bản V1/V2/V3; hai panel đã tách PPO và DQN. Đường đứt vẫn là đối chứng từ đầu. Dữ liệu dày được lấy mẫu hiển thị tối đa 2.000 điểm mỗi fit; log gốc vẫn giữ các update.

Loss PPO là tổng các thành phần policy/value của thuật toán; có thể âm và không bắt buộc tiến về 0. Dao động quanh một vùng không tự động là lỗi. Loss DQN ở đây là Smooth L1 giữa Q dự đoán và target; giá trị nhỏ nghĩa là sai lệch nhỏ trên các batch đang đo. Target và batch cũng thay đổi khi học, nên đây không phải sai số trên một tập đích cố định.

Không so 0,01 của DQN với −0,02 của PPO để chọn learner tốt hơn. Cũng không dùng loss thấp để kết luận phân công tốt: cần đối chiếu validation, holdout cũ và test. Ví dụ DQN có loss nhỏ về cuối nhưng candidate V3 vẫn làm giảm điểm V1 cũ.

![Loss của PPO và DQN](../../assets/rl_2_cap/training_loss.png)

[Bản SVG để phóng lớn](../../assets/rl_2_cap/training_loss.svg)

### So sánh cuối 131.072 bước trên validation

Đây là ảnh chụp kết quả **chỉ ở checkpoint cuối ngân sách**, không phải điểm tốt nhất từng đạt. Trục X là các phương pháp/candidate; trục Y là objective trung bình, càng cao càng tốt. Màu xanh dương/tím phân biệt PPO/DQN; cột gạch chéo là policy từ đầu. Các nhãn accepted/rejected ghi quyết định của lượt đó.

Ở V3, PPO kế thừa đạt 0,122640, PPO từ đầu đạt 0,135579 và Hungarian đạt 0,146125. Trên validation V3, train từ đầu cao hơn warm candidate trong cấu hình này. Nhưng không suy ra kết luận chung vì chỉ có một seed và thứ hạng có thể khác trên test.

Accepted của đối chứng từ đầu chỉ là qua kiểm tra bootstrap/an toàn, không có phép so parent hoặc holdout lịch sử như nhánh kế thừa. Một candidate có điểm mới tăng vẫn có thể rejected: PPO V3 tăng 0,004145 so với parent trên V3 nhưng làm giảm V2 cũ 0,008966.

![So sánh cuối 131.072 bước trên validation](../../assets/rl_2_cap/final_comparison.png)

[Bản SVG để phóng lớn](../../assets/rl_2_cap/final_comparison.svg)

### Giữ chất lượng trên bối cảnh cũ

**Cột** là phiên bản đang train; **hàng** là holdout cũ được chấm lại. Giá trị ô bằng `điểm parent trên holdout cũ − điểm candidate trên holdout cũ`. Đỏ/dương là giảm chất lượng; xanh/âm là tăng chất lượng. Ô trắng thiếu dữ liệu là không áp dụng, không phải điểm bằng 0.

Ví dụ ô PPO, cột V3/hàng V2 là +0,0090: cập nhật V3 làm mất khoảng 0,009 điểm trên holdout V2. Đây là lý do từ chối PPO V3 dù điểm kỳ mới tăng. Ô DQN, cột V3/hàng V1 là +0,0224: giảm khá mạnh trên V1. Ngược lại, ô PPO trên V1 khoảng −0,0110 là cải thiện.

Các ô trong V3 đều so với policy thực sự được giữ là V1, không so với trọng số V2 đã bị loại. V2 là bối cảnh lịch sử cần bảo toàn hiệu năng, không phải một bản học V2 đã được chấp nhận thành công. Hình này cho biết trade-off của cập nhật, chưa xác định riêng nguyên nhân gây quên.

![Giữ chất lượng trên bối cảnh cũ](../../assets/rl_2_cap/forgetting_heatmap.png)

[Bản SVG để phóng lớn](../../assets/rl_2_cap/forgetting_heatmap.svg)

### Thời gian và tính khả thi

Ba panel lần lượt là **thời gian thực đo bằng giây**, **coverage phần trăm sinh viên được phân công**, và **số vi phạm ràng buộc**. Mỗi vị trí X là một lượt fit; màu phân biệt learner.

Các fit ở khoảng 500–700 giây. Vì chạy hai process trên máy đang dùng, không dùng vài chục giây chênh lệch để kết luận thuật toán nào luôn nhanh hơn. Đây không phải benchmark tốc độ cô lập hoặc thời gian phục vụ thực tế.

Coverage 100% nghĩa là tất cả sinh viên trong case đánh giá có một phân công hợp lệ; không có nghĩa phù hợp học thuật 100%. Panel vi phạm nhìn trống vì tất cả giá trị bằng 0, không phải mất dữ liệu. Hard mask/quota đóng vai trò lớn trong hai kết quả khả thi này.

![Thời gian và tính khả thi](../../assets/rl_2_cap/runtime_constraints.png)

[Bản SVG để phóng lớn](../../assets/rl_2_cap/runtime_constraints.svg)

### Lượt smoke 1.024 bước và lượt 131.072 bước

Mỗi cặp cột so một learner/phiên bản trên cùng validation: xám là lần smoke ngắn, xanh là lần ngân sách dài. Trục Y vẫn là objective, càng cao càng tốt.

PPO V1 tăng từ khoảng 0,071804 lên 0,108544; DQN V1 gần như giữ nguyên 0,118531. PPO V2 tăng so với smoke từ 0,081187 lên 0,112900, nhưng vẫn thấp hơn parent hiện tại trên cùng V2 là 0,119388 nên bị từ chối. Tăng so với lần thử cũ và vượt parent hiện tại là hai điều kiện khác nhau.

V2/V3 ở hai thí nghiệm có thể kế thừa các parent khác nhau. Do đó đây là so sánh hai ngân sách/quỹ đạo, không cô lập tác động nhân quả của chỉ số step. Không có cặp DQN V3 vì lần smoke trước không hoàn tất case đó; không đọc phần thiếu thành điểm 0.

![Lượt smoke 1.024 bước và lượt 131.072 bước](../../assets/rl_2_cap/smoke_vs_long.png)

[Bản SVG để phóng lớn](../../assets/rl_2_cap/smoke_vs_long.svg)

### Kết quả final test sau lựa chọn đóng băng

Hàng trên là objective test, càng cao càng tốt. Hàng dưới là regret so với Hungarian trên test, càng thấp càng tốt. Mỗi cột panel là một cohort test với n=4/14/11, không phải các mốc training.

`Selected/retained` là checkpoint đã được chọn theo validation; `candidate` là bản cuối đã train, kể cả bị từ chối; `scratch` là policy từ đầu. Checkpoint V1 xuất hiện dưới nhiều vai trò ở V1 vì bootstrap được dùng chung, không phải ba lần train độc lập.

Ví dụ test V2: DQN được giữ đạt 0,148416; PPO được giữ đạt 0,130587; Hungarian đạt 0,191483. DQN được giữ cao hơn PPO trong điểm đo này, nhưng vẫn còn khoảng cách tới nghiệm tối ưu. Ở test V3, cả hai model được giữ còn thấp hơn Greedy.

Một số candidate PPO bị từ chối lại có test cao hơn model được giữ. Không chọn lại theo các cột test: lựa chọn đã đóng băng trước khi mở test; đổi lựa chọn lúc này sẽ làm test trở thành dữ liệu chọn model. Không có confidence interval nhiều seed, nên chưa kết luận ưu thế thống kê hoặc hiệu quả học vụ.

![Kết quả final test sau lựa chọn đóng băng](../../assets/rl_2_cap/final_test_comparison.png)

[Bản SVG để phóng lớn](../../assets/rl_2_cap/final_test_comparison.svg)

## Kết luận thực nghiệm và phần còn thiếu

- Đã chứng minh phần mềm kế thừa được trọng số/optimizer/counter, giữ policy cũ qua candidate thất bại, tách holdout và tạo được kết quả >100k bước có kiểm chứng.
- Chưa chứng minh continual RL cải thiện đều theo kỳ. Tăng step không bảo đảm tăng validation/test; loss/return train không thay thế đánh giá ngoài train.
- Dữ liệu ít, validation rất nhỏ, quota dựng theo split và policy không thấy toàn bộ ma trận điểm tương lai như Hungarian. Các yếu tố này hạn chế khả năng tổng quát hóa; chưa có ablation đủ để quy nguyên nhân cho riêng yếu tố nào.
- Gamma 0,99 và shaping nằm trong reward học; objective báo cáo là điểm không chiết khấu. Hai đại lượng không đồng nhất. Một đoạn validation phẳng trên vài sinh viên không chứng minh hội tụ tham số.
- Chưa có feedback sinh viên/giảng viên/điều phối hoặc outcome có timestamp để chạy R2–R4 thật. V4 chỉ một hồ sơ; không tạo split hay feedback giả. Năm/tháng thiếu, DOCX chưa render trang và bìa scan vẫn có trạng thái thiếu riêng.
- Muốn kết luận tác dụng của RL trong kỳ cần dữ liệu phản hồi thật; muốn đánh giá mạnh hơn cần cohort/holdout lớn hơn, nhiều seed và protocol mới chốt trước test. Không retune trên final test vừa mở.

## Kiểm chứng và artifact

| Kiểm tra | Kết quả |
| --- | --- |
| Lượt fit / số bước | 10 / 1.310.720; mỗi lượt đủ 131.072 |
| Điểm đo validation | 170; 17 mốc/lượt |
| Warm start / lưu-nạp-inference | 4/4 trọng số khởi đầu trùng parent; 10/10 reload/inference parity đạt |
| Sổ giữ model | 4 ledger đã verify; không đổi native checkpoint cũ |
| Source native PPO/DQN/environment | Hash giống nhau qua cả hai pha; chỉ engine/orchestration thêm retention |
| Regression tests | 101 passed; cảnh báo deprecation Gym wrapper có sẵn |
| Dữ liệu cũ | 225 file không đổi size/mtime; hash hai CSV gold khớp |
| Model phục vụ | Không promote; trạng thái nghiên cứu |
| Báo cáo người đọc | Một file này; JSON/checkpoint/PNG/SVG là artifact hỗ trợ |

Thư mục thí nghiệm: `data_rebuild/nested_rl_20261028/20261027T190955Z/long_research/`.

- `index.base.json`, `manifest.base.json`: pha đầu giữ nguyên.
- `retention_protocol.json`: chốt trước terminal V2, được kiểm tra timestamp; cùng budget/gate ở cả hai pha.
- `index.json`, `manifest.json`, `continuation/`: kết quả tổng hợp sau luồng retention.
- `rounds/{ppo,dqn}/{V1,V2,V3}/`: sáu candidate kế thừa/bootstrap, gồm training/inference checkpoint, input, curve, quyết định và manifest.
- `controls/from_scratch/{ppo,dqn}/{V2,V3}/`: bốn đối chứng độc lập.
- `retention/`: liên kết phiên bản logic với checkpoint thực sự được giữ; không copy hoặc đổi nhãn trọng số thành accepted giả.
- `final_test.json`: kết quả test mở một lần, selection không đổi. `index.test_evaluated=false` là cờ của training index đã đóng băng; trạng thái mở test nằm trong file riêng này.
- `experiment_audit.json`: tổng kiểm chứng nguồn, step, parity, ảnh và tính nguyên vẹn dữ liệu cũ.
- `docs/assets/rl_2_cap/`: 10 PNG + 10 SVG và chỉ mục hình, chỉ chứa số liệu tổng hợp.

Các entrypoint đã thực thi: `scripts/run_fresh_research.py`, `scripts/continue_retained_research.py`, `scripts/evaluate_nested_final.py`, `scripts/plot_nested_training.py`. Khi lặp thí nghiệm phải dùng output mới, ghi protocol trước terminal V2 và giữ test đóng đến sau cả hai pha. Lệnh mở test từ chối chạy lại trên cùng output.

Có thể kiểm tra/replot mà không train hoặc mở test lại:

```powershell
python -X utf8 scripts/train_nested_rl.py --verify data_rebuild/nested_rl_20261028/20261027T190955Z/long_research/rounds/ppo/V1
python -X utf8 scripts/plot_nested_training.py --run data_rebuild/nested_rl_20261028/20261027T190955Z/long_research --output docs/assets/rl_2_cap --reference data_rebuild/nested_rl_20261028/20261027T190955Z/research
```

Chốt báo cáo: 28/10/2026 03:51 (Asia/Saigon). Dữ liệu cá nhân và checkpoint nằm trong thư mục private bị Git ignore.

## Thí nghiệm bốn round với phản hồi mô phỏng

Người dùng cho phép tạo dữ liệu ảo để kiểm tra đầy đủ chuỗi hai cấp, sau đó thay bằng dữ liệu thật và train lại trong namespace mới. Đây là thí nghiệm mới, giữ nguyên các artifact/test cũ.

- V1: 2024.1, lịch sử đến 12/2024; V2: 2024.2, 01–05/2025; V3: 2025.1, 06–12/2025.
- R1 dùng hồ sơ ban đầu. R2 tạo một nguyện vọng 0,8 cho giảng viên có similarity cao nhất trong nhóm đủ điều kiện, cho mỗi sinh viên train; đánh dấu preference_known. Đây là tín hiệu tương quan trực tiếp với similarity, không phải nhãn độc lập.
- R3 tăng một chỗ nhận sinh viên cho một giảng viên đang tham gia trong mỗi cohort train. Không suy diễn đây là chỉ tiêu lịch sử thật. R4 giữ nguyên toàn bộ dữ liệu R3 và chạy thêm bước, được ghi `extra_steps_no_new_signal`.
- Mỗi round thêm 32.768 bước, 4 round = 131.072 bước/version/thuật toán; 24 fit = 786.432 bước tính toán. Bộ đếm của model được giữ có thể thấp hơn tổng đã tính toán khi candidate bị từ chối.
- Hai tiến trình độc lập PPO/DQN, seed 42, đo mỗi 8.192 bước. Giữ thuật toán/kiến trúc native. Mỗi round lưu input, report, curve, manifest, checkpoint trong `<experiment>/<algorithm>/Vx/Ry/<algorithm>/`.
- Kế thừa bản được chấp nhận gần nhất qua round và qua kỳ; candidate bị từ chối vẫn được lưu nhưng không được dùng làm nguồn trọng số. Gate không cho giảm điểm kỳ hiện tại/holdout kỳ cũ. R4 không được gọi là cải thiện nhờ tín hiệu mới.
- Validation giữ nguyên để so sánh parent/candidate trên cùng cohort; chỉ train thay đổi theo mock. Điểm này đo khả năng chuyển sang validation hồ sơ ban đầu, không đo mức đáp ứng nguyện vọng thật. Validation đã dùng trong nghiên cứu trước; không xem đây là một đánh giá độc lập mới. Không mở lại final test cũ, không tự chọn model phục vụ từ mock.

### Bảng so sánh từng round

Trạng thái: **completed**. Điểm là objective/student trên validation, không phải accuracy. `Δ` là candidate trừ parent trên cùng tập. Các dòng bị từ chối dùng model được giữ cho round tiếp theo.

| Model | Version | Round | Bước thêm | Bước candidate | Parent | Candidate | Δ | Gate |
|---|---|---|---:|---:|---:|---:|---:|---|
| PPO | V1 | R1 | 32768 | 32768 | — | 0.071804 | — | accepted |
| PPO | V1 | R2 | 32768 | 65536 | 0.071804 | 0.118651 | 0.046848 | accepted |
| PPO | V1 | R3 | 32768 | 98304 | 0.118651 | 0.113548 | -0.005104 | rejected |
| PPO | V1 | R4 | 32768 | 98304 | 0.118651 | 0.113548 | -0.005104 | rejected |
| PPO | V2 | R1 | 32768 | 98304 | 0.095442 | 0.107204 | 0.011762 | accepted |
| PPO | V2 | R2 | 32768 | 131072 | 0.107204 | 0.102171 | -0.005033 | rejected |
| PPO | V2 | R3 | 32768 | 131072 | 0.107204 | 0.102171 | -0.005033 | rejected |
| PPO | V2 | R4 | 32768 | 131072 | 0.107204 | 0.102171 | -0.005033 | rejected |
| PPO | V3 | R1 | 32768 | 131072 | 0.136034 | 0.125771 | -0.010263 | rejected |
| PPO | V3 | R2 | 32768 | 131072 | 0.136034 | 0.128436 | -0.007598 | rejected |
| PPO | V3 | R3 | 32768 | 131072 | 0.136034 | 0.132024 | -0.004010 | rejected |
| PPO | V3 | R4 | 32768 | 131072 | 0.136034 | 0.132024 | -0.004010 | rejected |
| DQN | V1 | R1 | 32768 | 32768 | — | 0.118651 | — | accepted |
| DQN | V1 | R2 | 32768 | 65536 | 0.118651 | 0.114647 | -0.004004 | rejected |
| DQN | V1 | R3 | 32768 | 65536 | 0.118651 | 0.114647 | -0.004004 | rejected |
| DQN | V1 | R4 | 32768 | 65536 | 0.118651 | 0.114647 | -0.004004 | rejected |
| DQN | V2 | R1 | 32768 | 65536 | 0.105867 | 0.102505 | -0.003362 | rejected |
| DQN | V2 | R2 | 32768 | 65536 | 0.105867 | 0.108293 | 0.002426 | rejected |
| DQN | V2 | R3 | 32768 | 65536 | 0.105867 | 0.115652 | 0.009785 | rejected |
| DQN | V2 | R4 | 32768 | 65536 | 0.105867 | 0.115652 | 0.009785 | rejected |
| DQN | V3 | R1 | 32768 | 65536 | 0.115450 | 0.119453 | 0.004004 | rejected |
| DQN | V3 | R2 | 32768 | 65536 | 0.115450 | 0.123816 | 0.008367 | accepted |
| DQN | V3 | R3 | 32768 | 98304 | 0.123816 | 0.136298 | 0.012482 | rejected |
| DQN | V3 | R4 | 32768 | 98304 | 0.123816 | 0.136298 | 0.012482 | rejected |

### Tổng hợp từng version

| Model | Version | Số fit | Tổng bước tính toán | Điểm R1 | Candidate R4 | Điểm model được giữ cuối kỳ | Số round accepted |
|---|---|---:|---:|---:|---:|---:|---:|
| PPO | V1 | 4 | 131072 | 0.071804 | 0.113548 | 0.118651 | 2 |
| PPO | V2 | 4 | 131072 | 0.107204 | 0.102171 | 0.107204 | 1 |
| PPO | V3 | 4 | 131072 | 0.125771 | 0.132024 | 0.136034 | 0 |
| DQN | V1 | 4 | 131072 | 0.118651 | 0.114647 | 0.118651 | 1 |
| DQN | V2 | 4 | 131072 | 0.102505 | 0.115652 | 0.105867 | 0 |
| DQN | V3 | 4 | 131072 | 0.119453 | 0.136298 | 0.123816 | 1 |

### Phân tích kết quả 4R

- R2: 2/6 candidate được giữ theo gate; không đồng nghĩa có hiệu quả thống kê hoặc tác dụng nhân quả của tín hiệu.
- R3: 0/6 candidate được giữ theo gate; không đồng nghĩa có hiệu quả thống kê hoặc tác dụng nhân quả của tín hiệu.
- R4: 0/6 candidate được giữ theo gate; không đồng nghĩa có hiệu quả thống kê hoặc tác dụng nhân quả của tín hiệu.
- DQN V2/R2: điểm kỳ hiện tại tăng 0.002426, nhưng holdout cũ giảm tối đa 0.000120; vì vậy không kế thừa candidate này.
- DQN V2/R3: điểm kỳ hiện tại tăng 0.009785, nhưng holdout cũ giảm tối đa 0.010108; vì vậy không kế thừa candidate này.
- DQN V2/R4: điểm kỳ hiện tại tăng 0.009785, nhưng holdout cũ giảm tối đa 0.010108; vì vậy không kế thừa candidate này.
- DQN V3/R1: điểm kỳ hiện tại tăng 0.004004, nhưng holdout cũ giảm tối đa 0.004004; vì vậy không kế thừa candidate này.
- DQN V3/R3: điểm kỳ hiện tại tăng 0.012482, nhưng holdout cũ giảm tối đa 0.005983; vì vậy không kế thừa candidate này.
- DQN V3/R4: điểm kỳ hiện tại tăng 0.012482, nhưng holdout cũ giảm tối đa 0.005983; vì vậy không kế thừa candidate này.
- R4 không bổ sung phản hồi điều phối; nếu R3 bị từ chối và R4 dùng lại cùng nguồn trọng số, cùng seed và cùng ngân sách, hai candidate có thể cho kết quả giống nhau. Không cộng bước candidate bị loại vào bộ đếm của model được giữ.

### Đọc các biểu đồ mới

![So sánh điểm cuối từng round](../../../frontend/assets/nested-rl/round-comparison.png)

![So sánh các mốc step từng round](../../../frontend/assets/nested-rl/step-curves.png)

- Biểu đồ điểm cuối theo round đặt các candidate cạnh nhau. Nhìn riêng từng version; giá trị cuối không đồng nghĩa model đã được gate chấp nhận.
- Biểu đồ step gồm 12 panel V1–V3 × R1–R4. Đường chấm là parent cố định trên cùng validation; đường liền là candidate tại các mốc đo thật. Không có dải tin cậy vì chỉ một seed.
- Tăng từ R3 sang R4 chỉ cho thấy tác động của train tiếp cùng dữ liệu; không chứng minh phản hồi điều phối có ích.
- So R2 với R1 chưa cô lập tác dụng preference vì cả dữ liệu và số bước cùng thay đổi. Cần đối chứng ngân sách tương đương khi nghiên cứu nhân quả.

### Chạy lại với dữ liệu thật

Thay hai suite `<feedback>/Vx/R2.json`, `R3.json` bằng input có nguồn phản hồi thật và đã áp dụng đúng thay đổi; giữ tín hiệu `student_preference`/`advisor_feedback` cùng hash/snapshot. Chạy `run_four_round_research.py --preflight` rồi tạo output mới. Không sửa mock hoặc checkpoint cũ, không biến tên người hướng dẫn trong luận văn thành nguyện vọng.

Các script: `prepare_mock_round_feedback.py` tạo mock tách biệt; `run_four_round_research.py` điều phối; `export_four_round_results.py` xuất aggregate cho web. JSON public chỉ chứa metric, không xuất mã/tên sinh viên hoặc nội dung phản hồi. Website hiển thị riêng nghiên cứu mock; model phân bổ phục vụ không bị thay ngầm.

Exporter hiện dành riêng cho protocol mock seed 42, 32.768 bước/round; nó từ chối scope dữ liệu thật hoặc ngân sách khác để tránh gắn nhãn sai. Khi có phản hồi thật, cần cập nhật protocol xuất bản và nhãn web cùng với thí nghiệm mới.

### Artifact và kiểm chứng

- Root: `data_rebuild/nested_rl_20261028/20261027T190955Z/mock_four_round_long/`; feedback riêng: `mock_four_round_feedback/` trong cùng fresh run. Không đưa dữ liệu sinh viên/checkpoint vào Git.
- `ppo/V1/R1/ppo/checkpoint/` là ví dụ thư mục model; tương tự cho V1–V3, R1–R4 và DQN. `comparison.json` mỗi thuật toán ghi artifact, parent, nguồn trọng số được giữ và bộ đếm; ledger retained giữ riêng các candidate bị loại.
- Kiểm tra cuối: 24 bundle native hợp lệ, 786.432 bước tính toán; 22 warm start khớp trọng số parent; cả 24 reload/inference parity đúng; R4 giống R3 về train/validation/contract ở cả sáu cặp. Chi tiết lưu `audit.json` tại root thí nghiệm.
- Regression hiện có: 595 passed, 3 skipped; bộ kiểm tra điều phối/xuất bản mới nhất: 4 passed. Frontend check/build thành công. Không chấm lại final test cũ.

Ví dụ chạy một thuật toán; đổi output sang thư mục chưa tồn tại nếu muốn chạy lại:

```powershell
python -X utf8 scripts/run_four_round_research.py --suites data_rebuild/nested_rl_20261028/20261027T190955Z/research/suites --feedback data_rebuild/nested_rl_20261028/20261027T190955Z/mock_four_round_feedback --output data_rebuild/nested_rl_20261028/20261027T190955Z/mock_four_round_long/ppo --algorithms ppo --timesteps 32768 --eval-interval 8192
```
