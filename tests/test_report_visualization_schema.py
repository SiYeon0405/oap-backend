import unittest

from pydantic import ValidationError

from app.schemas.analysis_report import (
    ChannelScoreWeights,
    KPI,
    Metric,
    PurchaseFactor,
    Scale,
    TargetSegment,
)


def metric(**overrides):
    values = {
        "key": "metric",
        "label": "Metric",
        "value": None,
        "unit": "score",
        "direction": "higher_is_better",
        "valueType": "observed",
        "evidenceIds": [],
    }
    values.update(overrides)
    return Metric(**values)


class ReportVisualizationSchemaTest(unittest.TestCase):
    def test_score_boundaries_and_null_are_allowed(self):
        self.assertEqual(metric(value=0).value, 0)
        self.assertEqual(metric(value=100).value, 100)
        self.assertIsNone(metric(value=None).value)

    def test_score_outside_range_is_rejected(self):
        for value in (-1, 101):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                metric(value=value)

    def test_confidence_boundaries_are_allowed(self):
        self.assertEqual(metric(confidence=0).confidence, 0)
        self.assertEqual(metric(confidence=1).confidence, 1)

    def test_confidence_outside_range_is_rejected(self):
        for value in (-0.01, 1.01):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                metric(confidence=value)

    def test_rate_outside_range_is_rejected(self):
        with self.assertRaises(ValidationError):
            PurchaseFactor(
                id="factor",
                label="Factor",
                positiveMentionRate=1.1,
                valueType="observed",
            )

    def test_evidence_ids_are_deduplicated(self):
        self.assertEqual(metric(evidenceIds=[1, 1, 2]).evidenceIds, [1, 2])

    def test_scale_min_greater_than_max_is_rejected(self):
        with self.assertRaises(ValidationError):
            Scale(min=10, max=1)

    def test_rank_zero_is_rejected_and_estimated_share_none_allowed(self):
        values = {
            "id": "segment",
            "rank": 0,
            "label": "Segment",
            "priorityScore": 50,
            "valueType": "estimated",
            "estimatedShare": None,
            "scoringModelVersion": "target-priority-v1.0",
        }
        with self.assertRaises(ValidationError):
            TargetSegment(**values)
        values["rank"] = 1
        self.assertIsNone(TargetSegment(**values).estimatedShare)

    def test_between_operator_requires_valid_range(self):
        base = {
            "key": "kpi",
            "label": "KPI",
            "metric": "conversion",
            "unit": "percent",
            "targetOperator": "between",
            "measurementWindow": "30 days",
            "decisionRule": "Continue when inside range",
            "source": "experiment",
            "calculation": "conversions / visits",
        }
        with self.assertRaises(ValidationError):
            KPI(**base)
        self.assertEqual(KPI(**base, targetMin=1, targetMax=3).targetMax, 3)

    def test_score_weights_must_sum_to_one(self):
        valid = {
            "audienceFit": 0.2,
            "contentFormatFit": 0.2,
            "costEfficiency": 0.2,
            "conversionIntent": 0.2,
            "executionFeasibility": 0.2,
        }
        self.assertEqual(sum(ChannelScoreWeights(**valid).model_dump().values()), 1)
        valid["executionFeasibility"] = 0.1
        with self.assertRaises(ValidationError):
            ChannelScoreWeights(**valid)


if __name__ == "__main__":
    unittest.main()
