"""Write a source-bound human and JSON report for a completed semester RL run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_report(run: Path) -> dict:
    run = run.resolve()
    prepared = read(run.parent.parent / 'data/training_prepared_20261105/manifest.json')
    suite = read(run / 'suites/readiness.json')
    audit = read(run / 'source_audit.json')
    feedback = read(run / 'feedback/readiness.json')
    status = read(run / 'training/status.json')
    if status.get('status') != 'completed' or not status.get('training_finished'):
        raise ValueError('completed_training_required_for_final_report')
    result = {
        'schema_version': 'semester-rl-final-report/1',
        'run': str(run), 'prepared_inputs': prepared, 'suite': suite, 'source_audit': audit,
        'feedback': feedback, 'training': status,
        'model': {'algorithm': read(run / 'training/protocol.json')['algorithm'],
                  'architecture': 'nested constrained reinforcement learning with PPO checkpoints and retention',
                  'output': 'A constrained discrete advisor-assignment action for each student; model policy/value outputs and compatibility scores are continuous numeric values, not supervised class labels.'},
        'r3_semantics': 'Historical thesis supervisor outcome proxy only; it is not independent advisor acceptance and does not modify eligibility, capacity, or presence.',
        'skill_score_layer': {'status': 'not_included', 'reason': 'No review-approved advisor skill claims or complete advisor_skill_scores snapshot exists; no score was fabricated.'},
    }
    (run / 'final_report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    counts = suite['versions']
    lines = ['# Báo cáo tái tạo Nested RL theo học kỳ', '', '## Dữ liệu cuối cùng',
             f"- Taxonomy freeze SHA-256: `{prepared['taxonomy_sha256']}`.",
             f"- V1/2024: {counts['V1']['train']} train, {counts['V1']['validation']} validation; corpus GV: {', '.join(counts['V1']['advisor_source_pools'])}.",
             f"- V2/2025.1: {counts['V2']['train']} train, {counts['V2']['validation']} validation; corpus GV: {', '.join(counts['V2']['advisor_source_pools'])}.",
             f"- V3/2025.2: {counts['V3']['train']} train, {counts['V3']['validation']} validation; chỉ dùng KLTN sinh viên, representation GV kế thừa từ {counts['V3']['advisor_representation_origin']}.",
             f"- SV loại do GVHD không map exact: {prepared['excluded_students']}.", '', '## Model',
             '- PPO nested constrained RL; 4 round/version, 131072 steps/round.',
             '- Output quyết định là action gán giảng viên bị ràng buộc; score/policy/value là số liên tục, không phải nhãn phân loại.',
             '- R2 dùng preference survey thực; R3 dùng proxy outcome GVHD trong KLTN, không phải approval độc lập.', '', '## Kiểm chứng',
             f"- Source parity: `{audit['score_parity_verified']}`.",
             f"- Feedback ready: `{feedback['ready']}`.",
             f"- Training completed rounds: {len(status['completed_rounds'])}.", '', '## Giới hạn',
             '- Chưa có advisor_skill_scores review-gated; skill score không được fabricated và chưa được đưa vào model này.',
             '- Scope là retrospective document proxy; prediction-time availability không được xác minh.']
    (run / 'final_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(write_report(args.run), ensure_ascii=False))