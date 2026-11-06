import unittest


class AdvisorSkillSnapshotTests(unittest.TestCase):
    def test_calendar_partition_uses_event_date_and_keeps_real_academic_term(self):
        from src.data_pipeline.advisor_skill_snapshot import partition_advisor_candidates

        partition = partition_advisor_candidates([
            {'artifact_id': 'paper-1', 'advisor_id': 'a', 'event_date': '2025-10-04',
             'available_at': None},
            {'artifact_id': 'paper-2', 'advisor_id': 'a', 'event_date': '2025-03-04',
             'available_at': None},
        ])

        self.assertEqual(partition['2025.1'][0]['academic_term'], '2025.1')
        self.assertEqual(partition['2025.1'][0]['storage_pool'], '2025.1')
        self.assertEqual(partition['2025.1'][1]['academic_term'], '2024.2')
        self.assertEqual(partition['2025.1'][1]['storage_pool'], '2025.1')

    def test_split_keeps_each_thesis_together_and_external_term_out(self):
        from src.data_pipeline.advisor_skill_snapshot import grouped_thesis_split

        result = grouped_thesis_split([
            {'student_id': 's1', 'thesis_id': 't1'},
            {'student_id': 's2', 'thesis_id': 't1'},
            {'student_id': 's3', 'thesis_id': 't2'},
            {'student_id': 's4', 'thesis_id': 't3'},
        ], seed=7)

        self.assertEqual(result['assignments']['s1'], result['assignments']['s2'])
        self.assertEqual(result['groups']['s1'], result['groups']['s2'])
        self.assertEqual(set(result['assignments'].values()), {'train', 'validation', 'test'})

        with self.assertRaisesRegex(ValueError, 'external_test_student_forbidden'):
            grouped_thesis_split([
                {'student_id': 's1', 'thesis_id': 't1', 'source_pool': '2025.3'},
                {'student_id': 's2', 'thesis_id': 't2'},
                {'student_id': 's3', 'thesis_id': 't3'},
            ])

    def test_pending_claims_close_as_not_evaluable_without_baseline(self):
        from src.data_pipeline.advisor_skill_snapshot import close_snapshot

        result = close_snapshot(
            profile_claims=[{'advisor_id': 'a', 'skill_id': 'python', 'artifact_id': 'p1',
                             'channel': 'prediction', 'score': 80, 'usage_status': 'used',
                             'review_status': 'pending', 'available_at': None,
                             'split': None, 'training_eligibility': 'unresolved'}],
            thesis_claims=[], registry=['a'], semester='2025.1',
            cutoff='2025-12-01T00:00:00+07:00', scope='point_in_time_verified',
        )

        self.assertEqual(result['status'], 'not_evaluable')
        self.assertEqual(result['baseline']['status'], 'not_run')
        self.assertIn('no_approved_point_in_time_claims', result['blocking_reasons'])

    def test_review_decision_requires_reviewer_timestamp_and_reason(self):
        from src.data_pipeline.advisor_skill_snapshot import apply_review_decisions

        claims = [{'evidence_id': 'e1', 'review_status': 'pending'}]
        approved = apply_review_decisions(claims, [{
            'evidence_id': 'e1', 'review_status': 'approved', 'reviewer': 'reviewer-1',
            'reviewed_at': '2025-11-02T10:00:00+07:00', 'reason': 'linked to source evidence',
        }])
        self.assertEqual(approved[0]['review_status'], 'approved')
        self.assertEqual(approved[0]['reviewer'], 'reviewer-1')

        with self.assertRaisesRegex(ValueError, 'review_decision_provenance_required'):
            apply_review_decisions(claims, [{'evidence_id': 'e1', 'review_status': 'approved'}])

    def test_review_decision_cannot_invent_availability_or_training_scope(self):
        from src.data_pipeline.advisor_skill_snapshot import apply_review_decisions

        claim = {'evidence_id': 'e1', 'review_status': 'pending', 'available_at': None,
                 'training_eligibility': 'unresolved'}
        reviewed = apply_review_decisions([claim], [{
            'evidence_id': 'e1', 'review_status': 'approved', 'reviewer': 'reviewer-1',
            'reviewed_at': '2025-11-02T10:00:00+07:00', 'reason': 'identity reviewed',
            'available_at': '2025-01-01T00:00:00+07:00',
            'training_eligibility': 'point_in_time_verified',
        }])

        self.assertEqual(reviewed[0]['review_status'], 'approved')
        self.assertIsNone(reviewed[0]['available_at'])
        self.assertEqual(reviewed[0]['training_eligibility'], 'unresolved')

    def test_approved_complete_claims_can_score_and_run_hungarian(self):
        from src.data_pipeline.advisor_skill_snapshot import close_snapshot

        def claim(channel, artifact, score):
            return {'advisor_id': 'a', 'skill_id': 'python', 'artifact_id': artifact,
                    'channel': channel, 'score': score, 'usage_status': 'used',
                    'review_status': 'approved', 'available_at': '2025-11-01T00:00:00+07:00',
                    'split': 'train', 'training_eligibility': 'point_in_time_verified',
                    'content_completeness': 'complete', 'evidence_id': artifact,
                    'supervision_review_status': 'approved'}

        result = close_snapshot(
            profile_claims=[claim('prediction', 'p1', 80), claim('evidence', 'p1', 90)],
            thesis_claims=[claim('thesis', 't1', 100)], registry=['a'], semester='2025.1',
            cutoff='2025-12-01T00:00:00+07:00', scope='point_in_time_verified',
            requirements=[{'student_id': 's1', 'skill_id': 'python', 'requirement_weight': 1,
                           'mandatory': True, 'review_status': 'approved',
                           'training_eligibility': 'point_in_time_verified',
                           'available_at': '2025-11-01T00:00:00+07:00',
                           'evidence_scope': 'predecision_requirement'}],
            student_ids=['s1'], capacities=[1], eligible=[[True]], present=[True],
        )

        self.assertEqual(result['status'], 'ready_for_training')
        self.assertEqual(result['score_rows'][0]['final_score'], 93)
        self.assertEqual(result['baseline']['status'], 'feasible')
        self.assertEqual(result['baseline']['assignments'][0]['advisor_id'], 'a')

    def test_unresolved_raw_claim_does_not_break_eligible_closed_snapshot(self):
        from src.data_pipeline.advisor_skill_snapshot import close_snapshot

        base = {'advisor_id': 'a', 'skill_id': 'python', 'usage_status': 'used',
                'review_status': 'approved', 'available_at': '2025-11-01T00:00:00+07:00',
                'split': 'train', 'training_eligibility': 'point_in_time_verified',
                'content_completeness': 'complete', 'supervision_review_status': 'approved'}
        result = close_snapshot(
            profile_claims=[base | {'artifact_id': 'p', 'evidence_id': 'p', 'channel': 'prediction', 'score': 80},
                            base | {'artifact_id': 'p', 'evidence_id': 'e', 'channel': 'evidence', 'score': 90},
                            {'advisor_id': 'a', 'skill_id': 'sql', 'artifact_id': 'raw', 'channel': 'evidence',
                             'score': 80, 'usage_status': 'used', 'review_status': 'pending',
                             'available_at': None, 'split': None, 'training_eligibility': 'unresolved'}],
            thesis_claims=[base | {'artifact_id': 't', 'evidence_id': 't', 'channel': 'thesis', 'score': 100}],
            registry=['a'], semester='2025.1', cutoff='2025-12-01T00:00:00+07:00',
            scope='point_in_time_verified',
        )

        self.assertEqual(result['status'], 'not_evaluable')
        self.assertEqual(result['score_rows'][0]['final_score'], 93)
        self.assertIn('matching_requirements_or_operator_constraints_missing', result['blocking_reasons'])

    def test_split_uses_proportional_thesis_groups(self):
        from src.data_pipeline.advisor_skill_snapshot import grouped_thesis_split

        rows = [{'student_id': f's{i}', 'thesis_id': f't{i}'} for i in range(20)]
        counts = {}
        for split in grouped_thesis_split(rows)['assignments'].values():
            counts[split] = counts.get(split, 0) + 1

        self.assertEqual(counts, {'train': 14, 'validation': 3, 'test': 3})

    def test_dedup_groups_doi_and_title_variants_without_merging(self):
        from src.data_pipeline.advisor_skill_snapshot import mark_duplicate_candidates

        rows = mark_duplicate_candidates([
            {'artifact_id': 'a1', 'advisor_id': 'x', 'title': 'Học Máy cho Dữ liệu!', 'doi': None},
            {'artifact_id': 'a2', 'advisor_id': 'x', 'title': 'hoc may cho du lieu', 'doi': None},
            {'artifact_id': 'a3', 'advisor_id': 'x', 'title': 'Other', 'doi': '10.1/ABC'},
            {'artifact_id': 'a4', 'advisor_id': 'x', 'title': 'Other mirror', 'doi': '10.1/abc'},
            {'artifact_id': 'a5', 'advisor_id': 'y', 'title': 'hoc may cho du lieu', 'doi': None},
        ])
        by_id = {row['artifact_id']: row for row in rows}

        self.assertEqual(len(rows), 5)
        self.assertEqual(by_id['a1']['duplicate_group_id'], by_id['a2']['duplicate_group_id'])
        self.assertEqual(by_id['a3']['duplicate_group_id'], by_id['a4']['duplicate_group_id'])
        self.assertNotEqual(by_id['a1']['duplicate_group_id'], by_id['a5']['duplicate_group_id'])
        self.assertEqual(by_id['a1']['dedup_status'], 'pending_review')
        self.assertEqual(by_id['a5']['dedup_status'], 'singleton')

    def test_ready_snapshot_runs_all_three_baselines(self):
        from src.data_pipeline.advisor_skill_snapshot import close_snapshot

        def claim(channel, artifact, score):
            return {'advisor_id': 'a', 'skill_id': 'python', 'artifact_id': artifact,
                    'channel': channel, 'score': score, 'usage_status': 'used',
                    'review_status': 'approved', 'available_at': '2025-11-01T00:00:00+07:00',
                    'split': 'train', 'training_eligibility': 'point_in_time_verified',
                    'evidence_id': artifact}

        result = close_snapshot(
            profile_claims=[claim('prediction', 'p1', 80), claim('evidence', 'p1', 90)],
            thesis_claims=[claim('thesis', 't1', 100)], registry=['a'], semester='2025.1',
            cutoff='2025-12-01T00:00:00+07:00', scope='point_in_time_verified',
            requirements=[{'student_id': 's1', 'skill_id': 'python', 'requirement_weight': 1,
                           'mandatory': True, 'review_status': 'approved',
                           'training_eligibility': 'point_in_time_verified',
                           'available_at': '2025-11-01T00:00:00+07:00',
                           'evidence_scope': 'predecision_requirement'}],
            student_ids=['s1'], capacities=[1], eligible=[[True]], present=[True],
        )

        self.assertEqual(set(result['baselines']), {'hungarian', 'greedy', 'random'})
        self.assertTrue(all(item['status'] == 'feasible' for item in result['baselines'].values()))

    def test_thesis_extraction_preserves_student_membership_for_grouped_split(self):
        from scripts.advisor_skill_pipeline import extract_jobs

        claims, _ = extract_jobs([{
            'artifact_id': 't1', 'advisor_id': 'a', 'channel': 'thesis',
            'content_scope': 'full_text_complete', 'expected_units': ['page:1'],
            'text_units': [{'unit_id': 'page:1', 'text': 'Python được sử dụng trong phương pháp.'}],
            'student_ids': ['s1', 's2'], 'supervision_id': 'link-1',
        }])

        self.assertTrue(claims)
        self.assertEqual(claims[0]['student_ids'], ['s1', 's2'])
        self.assertEqual(claims[0]['supervision_id'], 'link-1')


if __name__ == '__main__':
    unittest.main()