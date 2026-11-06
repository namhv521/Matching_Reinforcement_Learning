"""Private, named MOCK choices and advisor accept/reject responses; not real decisions."""
import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
import sys

import numpy as np
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_four_round_research import read, write, VERSIONS
from scripts.prepare_mock_round_feedback import digest
from src.rl.nested_learning import decode_problem
from src.domain.rebuild_matching import feasible
from src.evaluation.rebuild_benchmark import problem_payload
from src.data_pipeline.review_decisions import record_hash


def names(students, faculty):
    candidates = {}
    for line in Path(students).read_text(encoding='utf-8').splitlines():
        fields = json.loads(line)['fields']
        sid = fields.get('student_id', {}).get('value')
        name = fields.get('student_name', {}).get('value')
        if sid and (not name or not any(c.isalpha() for c in name)
                    or name.strip().casefold() in ('sinh viên', 'họ và tên', 'tên sinh viên')):
            # Recover identity only from a labeled name on pages 1-2. Never use
            # the thesis supervisor as a preference or an advisor response.
            import fitz
            row = json.loads(line)
            raw = Path(students).parent.parent / 'students/raw' / (row['source_sha256'] + '.pdf')
            name = None
            if raw.is_file():
                with fitz.open(raw) as doc:
                    text = '\n'.join(doc[i].get_text() for i in range(min(2, len(doc))))
                text = text.replace('\u200b', '')
                match = re.search(r'(?:Họ\s+và\s+tên\s+sinh\s+viên|Tên\s+sinh\s+viên)\s*:\s*([^\n]+)', text, re.I)
                if match:
                    name = match[1].strip()
        if sid and name:
            candidates.setdefault(str(sid), set()).add(name)
    student_names = {sid: next(iter(values)) for sid, values in candidates.items() if len(values) == 1}
    advisors = {r['advisor_id']: r['advisor_name'] for r in
                map(json.loads, Path(faculty).read_text(encoding='utf-8').splitlines())}
    return student_names, advisors


def choices(problem, version, student_names, advisor_names, choice_fraction=0.4):
    """Only a declared subset chooses; other train students have no preference."""
    result = []
    if not 0 <= choice_fraction <= 1:
        raise ValueError('choice_fraction_must_be_between_zero_and_one')
    ordered = sorted(problem['student_ids'], key=lambda sid: hashlib.sha256((version + sid).encode()).hexdigest())
    selected = set(ordered[:round(len(ordered) * choice_fraction)])
    for i, sid in enumerate(problem['student_ids']):
        if sid not in selected:
            result.append({'version': version, 'scope': 'MOCK_NOT_REAL_CHOICE_OR_RESPONSE',
                'student_id': sid, 'student_name': student_names.get(sid, ''), 'advisor_id': '', 'advisor_name': '',
                'choice_rank': None, 'preference': None, 'choice_status': 'not_chosen',
                'advisor_response': 'not_applicable_no_choice', 'response_reason': '',
                'response_is_simulated': True, 'final_assignment': False, 'student_excluded_from_cohort': False,
                'name_note': '' if sid in student_names else 'missing_name_needs_review'})
            continue
        valid = [j for j, _ in enumerate(problem['advisor_ids']) if problem['eligible'][i][j]
                 and problem['available'][i][j] and problem['present'][j] and problem['capacities'][j] > 0]
        if not valid:
            raise ValueError('each_mock_student_needs_an_eligible_advisor')
        j = max(valid, key=lambda j: problem['scores'][i][j])
        aid = problem['advisor_ids'][j]
        result.append({'version': version, 'scope': 'MOCK_NOT_REAL_CHOICE_OR_RESPONSE',
            'student_id': sid, 'student_name': student_names.get(sid, ''),
            'advisor_id': aid, 'advisor_name': advisor_names.get(aid, ''),
            'choice_rank': 1, 'preference': .8,
            'choice_status': 'chosen',
            'choice_reason': 'mock_top_text_similarity_among_eligible_advisors',
            'name_note': '' if sid in student_names and aid in advisor_names else 'missing_or_conflicting_name_needs_review'})
        problem['preferences'][i][j] = .8
        problem['preference_known'][i][j] = True
    return result


def respond(problem, records):
    """Simulated capacity-limited decisions; retain a feasible alternative matching.

    Accepted means the selected advisor permits the pair, not a locked allocation.
    Rejected removes only this requested pair, never the student from the cohort.
    """
    slots = [j for j, capacity in enumerate(problem['capacities'])
             if problem['present'][j] for _ in range(capacity)]
    valid = np.asarray(problem['eligible']) & np.asarray(problem['available'])
    cost = -np.asarray(problem['scores'])[:, slots]
    cost[~valid[:, slots]] = np.inf
    students, assigned = linear_sum_assignment(cost)
    if len(students) != len(records):
        raise ValueError('complete_feasible_backbone_required')
    backbone = {int(i): slots[int(k)] for i, k in zip(students, assigned)}
    student_index = {sid: i for i, sid in enumerate(problem['student_ids'])}
    changes = []
    for j, aid in enumerate(problem['advisor_ids']):
        applicants = [r for r in records if r['advisor_id'] == aid]
        # Preserve backbone edges, then use a reproducible mock lottery for spare
        # places. This is not a judgment about actual student merit or suitability.
        applicants.sort(key=lambda r: (backbone[student_index[r['student_id']]] != j,
            hashlib.sha256((r['version'] + r['student_id'] + aid).encode()).hexdigest()))
        capacity = problem['capacities'][j]
        for rank, row in enumerate(applicants):
            accepted = rank < capacity
            row.update(advisor_response='accepted' if accepted else 'rejected',
                       response_reason='mock_within_capacity' if accepted else 'mock_capacity_exceeded',
                       advisor_capacity=capacity, applicant_count=len(applicants),
                       response_is_simulated=True, final_assignment=False,
                       student_excluded_from_cohort=False)
            if not accepted:
                i = student_index[row['student_id']]
                problem['eligible'][i][j] = False
                changes.append({'student_id': row['student_id'], 'advisor_id': aid,
                                'field': 'eligible', 'old': True, 'new': False})
    if not feasible(decode_problem(problem)):
        raise ValueError('mock_rejections_must_preserve_alternative_allocation')
    return changes


def bind(data, output, version, index, kind, changes, records):
    signal_id = f'MOCK-EXPLICIT-{version}-R{index}'
    source = output / version / f'R{index}-source.json'
    write(source, {'scope': 'MOCK_NOT_REAL_CHOICE_OR_RESPONSE', 'signal_id': signal_id,
                   'available_at_is_simulated': True, 'records': records, 'changes': changes})
    spec = data['round']
    spec['signals'].append({'signal_id': signal_id, 'type': kind, 'source_path': str(source),
        'source_sha256': digest(source), 'available_at': spec['cutoff_timestamp'],
        'review_status': 'verified', 'provenance': 'simulated_not_human'})
    snapshot = read(spec['snapshot_path'])
    snapshot.update(training_problem_sha256=[record_hash(problem_payload(decode_problem(p))) for p in data['train']],
        validation_problem_sha256=record_hash(problem_payload(decode_problem(data['validation']))),
        signal_ids=[s['signal_id'] for s in spec['signals']],
        applied_signal_source_sha256={signal_id: digest(source)})
    path = output / version / f'R{index}-snapshot.json'
    write(path, snapshot)
    spec.update(snapshot_path=str(path), snapshot_sha256=digest(path), round_index=index,
                signal_state_sha256=record_hash([s['signal_id'] for s in spec['signals']]))
    data['experiment_scope'] = 'simulated_feedback_not_human'
    data['mock_recipe'] = 'explicit_choices_capacity_limited_advisor_responses'
    write(output / version / f'R{index}.json', data)


def prepare(suites, output, students, faculty):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('new_explicit_mock_namespace_required')
    student_names, advisor_names = names(students, faculty)
    summary, preview = [], []
    for version in VERSIONS:
        data = copy.deepcopy(read(Path(suites) / version / 'suite.json'))
        original = copy.deepcopy(data)
        records, groups = [], []
        for p in data['train']:
            rows = choices(p, version, student_names, advisor_names)
            records.extend(rows)
            groups.append(rows)
        changes = []
        for before, after in zip(original['train'], data['train']):
            for i, sid in enumerate(after['student_ids']):
                for j, aid in enumerate(after['advisor_ids']):
                    for field in ('preferences', 'preference_known'):
                        if before[field][i][j] != after[field][i][j]:
                            changes.append(dict(student_id=sid, advisor_id=aid, field=field,
                                old=before[field][i][j], new=after[field][i][j]))
        bind(data, output, version, 2, 'student_preference', changes, records)
        changes = []
        for problem, rows in zip(data['train'], groups):
            changes.extend(respond(problem, rows))
        if not changes:
            raise ValueError('no_rejection_delta_do_not_fake_a_changed_R3')
        assert data['validation'] == original['validation']
        bind(data, output, version, 3, 'advisor_feedback', changes, records)
        write(output / version / 'choices_and_responses.json', records)
        preview.extend([{**row, 'split': 'train'} for row in records])
        for split in ('validation', 'test'):
            p = original[split]
            for sid in p['student_ids']:
                preview.append({'version': version, 'split': split, 'student_id': sid,
                    'student_name': student_names.get(sid, ''), 'advisor_name': '',
                    'choice_status': 'not_mocked_holdout', 'advisor_response': 'not_mocked_holdout'})
        summary.append({'version': version, 'students': len(records),
            'chosen': sum(r['choice_status'] == 'chosen' for r in records),
            'not_chosen': sum(r['choice_status'] == 'not_chosen' for r in records),
            'accepted': sum(r['advisor_response'] == 'accepted' for r in records),
            'rejected_by_requested_advisor': sum(r['advisor_response'] == 'rejected' for r in records),
            'missing_names': sum(bool(r['name_note']) for r in records)})
    result = {'scope': 'MOCK_NOT_REAL_CHOICE_OR_RESPONSE', 'training_performed': False,
              'holdouts_modified': False, 'old_artifacts_modified': False,
              'choice_fraction_train': .4,
              'recipe': 'explicit_choices_capacity_limited_advisor_responses', 'versions': summary}
    write(output / 'manifest.json', result)
    write(output / 'data_preview.json', {'scope': result['scope'], 'rows': preview})
    lines = ['# Dữ liệu MOCK: lựa chọn sinh viên và phản hồi giảng viên', '',
        '**Không phải lựa chọn hoặc quyết định thật. Chưa train bộ này.**', '',
        'Chỉ khoảng 40% sinh viên train có lựa chọn; phần còn lại chưa chọn. Validation/test được liệt kê để đủ danh sách nhưng không tạo phản hồi mock cho các nhóm này.', '',
        '“Từ chối” chỉ áp dụng với giảng viên đã chọn, không loại sinh viên khỏi cohort. “Chấp nhận” là đồng ý xét cặp này, chưa khóa phân công cuối cùng.', '',
        '| Version | Tập | Mã sinh viên | Họ tên | R2: lựa chọn | Giảng viên được chọn | R3: phản hồi |',
        '|---|---|---|---|---|---|---|']
    labels = {'chosen': 'Đã chọn (mock)', 'not_chosen': 'Chưa chọn', 'accepted': 'Chấp nhận (mock)',
              'rejected': 'Từ chối: vượt chỉ tiêu (mock)', 'not_applicable_no_choice': 'Không áp dụng — chưa chọn',
              'not_mocked_holdout': 'Giữ nguyên — không tạo mock'}
    for row in preview:
        values = [row['version'], row['split'], row['student_id'], row['student_name'] or 'CHƯA CÓ TÊN',
                  labels[row['choice_status']], row['advisor_name'] or '—', labels[row['advisor_response']]]
        lines.append('| ' + ' | '.join(str(v).replace('|', '/') for v in values) + ' |')
    (output / 'data_preview.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('suites', 'output', 'students', 'faculty'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.suites, args.output, args.students, args.faculty), indent=2))
