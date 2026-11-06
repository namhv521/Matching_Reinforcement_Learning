import unittest

from src.features.advisor_skill_scores import score_advisor_skills


CUTOFF = '2026-05-31T23:59:59+07:00'


def claim(channel, artifact, score, **changes):
    row = dict(advisor_id='A', skill_id='python', artifact_id=artifact, channel=channel,
               score=score, usage_status='used', review_status='approved',
               available_at='2026-01-01T00:00:00+07:00', split='train',
               training_eligibility='point_in_time_verified', evidence_id=artifact)
    row.update(changes)
    return row


class AdvisorSkillScoresTest(unittest.TestCase):
    def setUp(self):
        self.profile = [claim('prediction', 'paper', 70), claim('evidence', 'paper', 90)]
        self.theses = [claim('thesis', 't1', 80), claim('thesis', 't2', 100),
                       claim('thesis', 't3', None, usage_status='not_used')]

    def score(self, profile=None, theses=None, **kwargs):
        return score_advisor_skills(self.profile if profile is None else profile,
                                    self.theses if theses is None else theses,
                                    cutoff=CUTOFF, **kwargs)

    def test_fixed_weights_and_not_used_excluded(self):
        row = self.score()[0]
        self.assertEqual((row['profile_score'], row['gvhd_score'], row['final_score']), (82, 90, 86))
        self.assertEqual(row['thesis_count'], 2)
        self.assertEqual(row['status'], 'complete')

    def test_dedup_does_not_weight_same_thesis_twice(self):
        self.assertEqual(self.score(theses=self.theses + [self.theses[0]])[0]['final_score'], 86)
        with self.assertRaisesRegex(ValueError, 'conflicting_duplicate'):
            self.score(theses=self.theses + [claim('thesis', 't1', 100)])

    def test_future_other_split_and_self_exclusion(self):
        rows = self.theses + [claim('thesis', 'future', 0, available_at='2026-06-01T00:00:00+07:00'),
                              claim('thesis', 'holdout', 0, split='test')]
        row = self.score(theses=rows, excluded_thesis_ids=['t1'])[0]
        self.assertEqual(row['gvhd_score'], 100)
        self.assertEqual(row['thesis_count'], 1)

    def test_missing_is_null_without_renormalization(self):
        row = self.score(profile=self.profile[:1], theses=[])[0]
        self.assertIsNone(row['profile_score'])
        self.assertIsNone(row['gvhd_score'])
        self.assertIsNone(row['final_score'])
        self.assertFalse(row['known_mask'])

    def test_partial_or_unreviewed_claim_blocks_final(self):
        for changes in ({'content_completeness': 'partial'}, {'review_status': 'pending'},
                        {'supervision_review_status': 'needs_review'},
                        {'article_person_link_status': 'pending'},
                        {'article_identity_review_status': 'pending'},
                        {'downloaded_document_matches_article': None},
                        {'downloaded_document_matches_article': False}):
            row = self.score(theses=self.theses + [claim('thesis', 'incomplete', 80, **changes)])[0]
            self.assertEqual(row['status'], 'partial')
            self.assertIsNone(row['final_score'])

    def test_zero_is_not_an_absence_filter(self):
        row = self.score(theses=[claim('thesis', 'real_zero', 0)])[0]
        self.assertEqual(row['gvhd_score'], 0)
        self.assertEqual(row['thesis_count'], 1)

    def test_invalid_scores_usage_and_dates(self):
        for changes in ({'score': float('nan')}, {'score': True}, {'score': 101},
                        {'available_at': '2026-01-01'}, {'usage_status': 'not_used'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.score(theses=[dict(claim('thesis', 'invalid', 80), **changes)])

    def test_proxy_does_not_enter_strict_snapshot(self):
        row = self.score(theses=[claim('thesis', 'proxy', 100,
                                     training_eligibility='retrospective_proxy')])[0]
        self.assertIsNone(row['gvhd_score'])

    def test_registry_advisor_without_data_retained(self):
        rows = self.score(advisor_ids=['A', 'B'])
        self.assertEqual(rows[1]['advisor_id'], 'B')
        self.assertIsNone(rows[1]['skill_id'])
        self.assertIsNone(rows[1]['final_score'])


if __name__ == '__main__':
    unittest.main()
