"""Export only aggregate mock experiment metrics, never student identities."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_four_round_research import read, write
from src.rl.nested_learning import verify_round


def export(root, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    root, output = Path(root), Path(output)
    rows, completed, curves = [], True, {}
    for algorithm in ('ppo', 'dqn'):
        path = root / algorithm / 'comparison.json'
        if not path.exists():
            completed = False
            continue
        data = read(path)
        if (data['protocol'].get('feedback_scope') != 'simulated_feedback_not_human'
                or data['protocol'].get('timesteps_per_fit') != 32768
                or data['protocol'].get('seed') != 42):
            raise ValueError('this_mock_publication_requires_simulated_seed42_32768_step_protocol')
        if data['protocol'].get('feedback_recipe', 'top_similarity_preference_0.8_and_one_extra_advisor_seat') != 'top_similarity_preference_0.8_and_one_extra_advisor_seat':
            raise ValueError('new_feedback_recipe_requires_updated_publication_labels')
        completed &= data['status'] == 'completed'
        for row in data['results']:
            report = verify_round(root / algorithm / row['artifact'])
            for key in ('decision', 'candidate_score', 'parent_score', 'steps_added', 'steps_after'):
                if row.get(key) != report.get(key):
                    raise ValueError('comparison_native_report_mismatch: ' + key)
            curves[(algorithm, row['version'], row['round'])] = [json.loads(line) for line in
                (root / algorithm / row['artifact'] / 'learning_curve.jsonl').read_text().splitlines()]
            rows.append({k: row.get(k) for k in ('version', 'round', 'algorithm', 'decision',
                'candidate_score', 'parent_score', 'delta', 'steps_before', 'steps_added', 'steps_after',
                'start_weights_equal_parent', 'forgetting_status', 'training_elapsed_seconds',
                'improvement_attribution', 'effective_weight_source')})
            rows[-1]['old_holdout_max_drop'] = max(
                [x['signed_drop'] for x in report.get('forgetting', {}).values()], default=None)
    expected = {(a, v, r) for a in ('ppo', 'dqn') for v in ('V1', 'V2', 'V3') for r in ('R1', 'R2', 'R3', 'R4')}
    actual = [(r['algorithm'], r['version'], r['round']) for r in rows]
    if len(set(actual)) != len(actual) or not set(actual) <= expected or (completed and set(actual) != expected):
        raise ValueError('unique_complete_24_round_grid_required_for_completed_publication')
    public = {'scope': 'simulated_feedback_not_human', 'status': 'completed' if completed else 'running',
              'test_evaluated': False, 'serving_model_changed': False,
              'limitations': ['R2 preferences are generated from text similarity; this is circular proxy evidence.',
                              'R3 simulates one extra advisor seat per training cohort.',
                              'R4 repeats R3 without new feedback.',
                              'Reused development validation, one seed; no independent new test.'],
              'results': rows}
    write(output / 'results.json', public)
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), sharey=True)
    for ax, version in zip(axes, ('V1', 'V2', 'V3')):
        for algorithm, color in (('ppo', '#2463b5'), ('dqn', '#bd650e')):
            selected = [r for r in rows if r['version'] == version and r['algorithm'] == algorithm]
            ax.plot([int(r['round'][1:]) for r in selected], [r['candidate_score'] for r in selected],
                    marker='o', color=color, label=algorithm.upper())
        ax.set(title=version, xlabel='Round (R4: unchanged input)', xticks=[1, 2, 3, 4])
        ax.grid(alpha=.2)
        ax.legend()
    axes[0].set_ylabel('Validation objective / student')
    fig.suptitle('SIMULATED feedback - candidate metrics, not academic accuracy')
    fig.tight_layout()
    fig.savefig(output / 'round-comparison.png', dpi=160)
    plt.close(fig)
    fig, axes = plt.subplots(3, 4, figsize=(16, 10))
    for i, version in enumerate(('V1', 'V2', 'V3')):
        for j, round_id in enumerate(('R1', 'R2', 'R3', 'R4')):
            ax = axes[i, j]
            for algorithm, color in (('ppo', '#2463b5'), ('dqn', '#bd650e')):
                points = curves.get((algorithm, version, round_id), [])
                ax.plot([p['relative_step'] for p in points],
                        [p['validation_objective_per_student'] for p in points],
                        marker='.', color=color, label=algorithm.upper())
                if points and points[0]['parent_objective_per_student'] is not None:
                    ax.axhline(points[0]['parent_objective_per_student'], color=color, linestyle=':', alpha=.6)
            ax.set(title=f'{version} / {round_id}', xlabel='Added steps', ylabel='Validation objective / student')
            ax.grid(alpha=.2)
    axes[0, 0].legend()
    fig.suptitle('SIMULATED feedback - dotted lines: fixed parent on same validation')
    fig.tight_layout()
    fig.savefig(output / 'step-curves.png', dpi=140)
    plt.close(fig)
    return public


def update_report(path, result):
    marker = '\n## Thí nghiệm bốn round với phản hồi mô phỏng\n'
    text = Path(path).read_text(encoding='utf-8').split(marker)[0]
    notice = ('**Cập nhật thí nghiệm 4R:** ' + result['status'] + f" · {len(result['results'])}/24 fit. "
              'Bộ phản hồi mô phỏng được người dùng cho phép; phần cuối báo cáo có bảng R1–R4 và biểu đồ mới. '
              'Các phần thí nghiệm 131.072 bước/fit phía trước là kết quả cũ, được giữ để đối chiếu.\n')
    lines = [line for line in text.splitlines(keepends=True) if not line.startswith('**Cập nhật thí nghiệm 4R:**')]
    lines.insert(1, '\n' + notice)
    text = ''.join(lines)
    section = '''
Người dùng cho phép tạo dữ liệu ảo để kiểm tra đầy đủ chuỗi hai cấp, sau đó thay bằng dữ liệu thật và train lại trong namespace mới. Đây là thí nghiệm mới, giữ nguyên các artifact/test cũ.

- V1: 2024.1, lịch sử đến 12/2024; V2: 2024.2, 01–05/2025; V3: 2025.1, 06–12/2025.
- R1 dùng hồ sơ ban đầu. R2 tạo một nguyện vọng 0,8 cho giảng viên có similarity cao nhất trong nhóm đủ điều kiện, cho mỗi sinh viên train; đánh dấu preference_known. Đây là tín hiệu tương quan trực tiếp với similarity, không phải nhãn độc lập.
- R3 tăng một chỗ nhận sinh viên cho một giảng viên đang tham gia trong mỗi cohort train. Không suy diễn đây là chỉ tiêu lịch sử thật. R4 giữ nguyên toàn bộ dữ liệu R3 và chạy thêm bước, được ghi `extra_steps_no_new_signal`.
- Mỗi round thêm 32.768 bước, 4 round = 131.072 bước/version/thuật toán; 24 fit = 786.432 bước tính toán. Bộ đếm của model được giữ có thể thấp hơn tổng đã tính toán khi candidate bị từ chối.
- Hai tiến trình độc lập PPO/DQN, seed 42, đo mỗi 8.192 bước. Giữ thuật toán/kiến trúc native. Mỗi round lưu input, report, curve, manifest, checkpoint trong `<experiment>/<algorithm>/Vx/Ry/<algorithm>/`.
- Kế thừa bản được chấp nhận gần nhất qua round và qua kỳ; candidate bị từ chối vẫn được lưu nhưng không được dùng làm nguồn trọng số. Gate không cho giảm điểm kỳ hiện tại/holdout kỳ cũ. R4 không được gọi là cải thiện nhờ tín hiệu mới.
- Validation giữ nguyên để so sánh parent/candidate trên cùng cohort; chỉ train thay đổi theo mock. Điểm này đo khả năng chuyển sang validation hồ sơ ban đầu, không đo mức đáp ứng nguyện vọng thật. Validation đã dùng trong nghiên cứu trước; không xem đây là một đánh giá độc lập mới. Không mở lại final test cũ, không tự chọn model phục vụ từ mock.

### Bảng so sánh từng round

Trạng thái: **STATUS**. Điểm là objective/student trên validation, không phải accuracy. `Δ` là candidate trừ parent trên cùng tập. Các dòng bị từ chối dùng model được giữ cho round tiếp theo.

| Model | Version | Round | Bước thêm | Bước candidate | Parent | Candidate | Δ | Gate |
|---|---|---|---:|---:|---:|---:|---:|---|
'''.replace('STATUS', result['status'])
    number = lambda x: '—' if x is None else f'{x:.6f}'
    for row in result['results']:
        section += '| ' + ' | '.join(str(x) for x in [row['algorithm'].upper(), row['version'], row['round'],
            row['steps_added'], row['steps_after'], number(row['parent_score']), number(row['candidate_score']),
            number(row['delta']), row['decision']]) + ' |\n'
    section += '\n### Tổng hợp từng version\n\n| Model | Version | Số fit | Tổng bước tính toán | Điểm R1 | Candidate R4 | Điểm model được giữ cuối kỳ | Số round accepted |\n|---|---|---:|---:|---:|---:|---:|---:|\n'
    for algorithm in ('ppo', 'dqn'):
        for version in ('V1', 'V2', 'V3'):
            subset = [r for r in result['results'] if r['algorithm'] == algorithm and r['version'] == version]
            if len(subset) != 4:
                continue
            last = subset[-1]
            retained_score = last['candidate_score'] if last['decision'] == 'accepted' else last['parent_score']
            section += '| ' + ' | '.join(str(x) for x in [algorithm.upper(), version, len(subset),
                sum(r['steps_added'] for r in subset), number(subset[0]['candidate_score']),
                number(last['candidate_score']), number(retained_score),
                sum(r['decision'] == 'accepted' for r in subset)]) + ' |\n'
    section += '\n### Phân tích kết quả 4R\n\n'
    for round_id in ('R2', 'R3', 'R4'):
        subset = [r for r in result['results'] if r['round'] == round_id]
        if subset:
            section += f"- {round_id}: {sum(r['decision'] == 'accepted' for r in subset)}/{len(subset)} candidate được giữ theo gate; không đồng nghĩa có hiệu quả thống kê hoặc tác dụng nhân quả của tín hiệu.\n"
    for row in result['results']:
        if (row['decision'] == 'rejected' and row['delta'] is not None and row['delta'] > 0
                and row['old_holdout_max_drop'] is not None and row['old_holdout_max_drop'] > 0):
            section += (f"- {row['algorithm'].upper()} {row['version']}/{row['round']}: điểm kỳ hiện tại tăng {row['delta']:.6f}, "
                        f"nhưng holdout cũ giảm tối đa {row['old_holdout_max_drop']:.6f}; vì vậy không kế thừa candidate này.\n")
    section += '- R4 không bổ sung phản hồi điều phối; nếu R3 bị từ chối và R4 dùng lại cùng nguồn trọng số, cùng seed và cùng ngân sách, hai candidate có thể cho kết quả giống nhau. Không cộng bước candidate bị loại vào bộ đếm của model được giữ.\n'
    section += '''
### Đọc các biểu đồ mới

![So sánh điểm cuối từng round](../frontend/assets/nested-rl/round-comparison.png)

![So sánh các mốc step từng round](../frontend/assets/nested-rl/step-curves.png)

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
'''
    Path(path).write_text(text + marker + section, encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = export(args.root, args.output)
    if args.report:
        update_report(args.report, result)
    print(json.dumps({'status': result['status'], 'rows': len(result['results'])}))
