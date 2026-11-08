import unittest
import numpy as np

from src.features.advisor_skill_matching import build_skill_problem
from src.baselines.rebuild_baselines import solve
from src.features.advisor_skill_scores import SCHEMA_VERSION


class SkillMatchingTests(unittest.TestCase):
    def args(self):
        return dict(advisor_ids=['a', 'b'], student_ids=['s'], capacities=np.array([1, 1]),
                    eligible=np.ones((1, 2), dtype=bool), present=np.ones(2, dtype=bool),
                    cutoff='2025-12-01T00:00:00+07:00', scope='point_in_time_verified', coverage_floor=.5)

    def score(self, advisor, skill, value):
        return dict(advisor_id=advisor, skill_id=skill, final_score=value, known_mask=True,
                    schema_version=SCHEMA_VERSION,
                    status='complete', scope='point_in_time_verified', cutoff=self.args()['cutoff'])

    def requirement(self, skill, **updates):
        return dict(student_id='s', skill_id=skill, requirement_weight=1, review_status='approved',
                    training_eligibility='point_in_time_verified', available_at='2025-11-01T00:00:00+07:00',
                    evidence_scope='predecision_requirement', **updates)

    def test_unknown_does_not_renormalize_and_native_baseline(self):
        p = build_skill_problem([self.score('a', 'python', 80), self.score('b', 'python', 60),
                                 self.score('b', 'sql', 60)],
                                [self.requirement('python'), self.requirement('sql')], **self.args())
        np.testing.assert_allclose(p.scores, [[.4, .6]])
        np.testing.assert_allclose(p.metadata['skill_coverage'], [[.5, 1.]])
        result = solve(p, 'hungarian')
        self.assertTrue(p.metadata['requires_new_or_migrated_checkpoint'])
        self.assertEqual(result['status'], 'feasible')
        self.assertEqual(result['assignments'][0]['advisor_id'], 'b')
        self.assertEqual(result['metrics']['constraint_violations'], 0)

    def test_mandatory_missing_masks_pair(self):
        p = build_skill_problem([self.score('a', 'python', 80)],
                                [self.requirement('python'), self.requirement('sql', mandatory=True)], **self.args())
        self.assertFalse(p.available.any())
        self.assertEqual(p.metadata['review_status'], 'needs_review')
        self.assertTrue(any(r['reason'] == 'mandatory_skill_evidence_unknown' for r in p.metadata['review_reasons']))

    def test_advisor_order_changes_checkpoint_contract(self):
        kwargs = self.args()
        a = build_skill_problem([], [], **kwargs)
        b = build_skill_problem([], [], **(kwargs | {'advisor_ids': ['b', 'a']}))
        self.assertNotEqual(a.metadata['feature_contract_sha256'], b.metadata['feature_contract_sha256'])

    def test_future_or_thesis_requirements_rejected(self):
        for change in ({'available_at': '2026-01-01T00:00:00+07:00'},
                       {'evidence_scope': 'inferred_from_thesis'}):
            row = self.requirement('python') | change
            with self.assertRaisesRegex(ValueError, 'prediction_time_leakage'):
                build_skill_problem([], [row], **self.args())

    def test_mismatched_snapshot_and_duplicate_rejected(self):
        row = self.score('a', 'python', 80)
        with self.assertRaisesRegex(ValueError, 'duplicate_advisor_skill'):
            build_skill_problem([row, row], [], **self.args())
        with self.assertRaisesRegex(ValueError, 'snapshot_contract_mismatch'):
            build_skill_problem([row | {'scope': 'retrospective_proxy'}], [], **self.args())


if __name__ == '__main__':
    unittest.main()
