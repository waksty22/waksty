import unittest

from learning.live_visual_observation import (
    LIVE_VISUAL_OBSERVATION_INTERVAL_SECONDS,
    build_live_visual_observation,
    live_visual_observation_due,
)


class LiveVisualObservationTests(unittest.TestCase):
    def test_frame_receipt_does_not_claim_semantic_understanding(self):
        observation = build_live_visual_observation("YWJj", "image/jpeg")
        self.assertIsNotNone(observation)
        self.assertEqual(observation["modality"], "vision")
        self.assertEqual(observation["confidence"], 0.0)
        self.assertFalse(observation["metadata"]["image_bytes_persisted"])
        self.assertFalse(observation["metadata"]["semantic_analysis_performed"])
        self.assertIn("ne décrit pas le contenu", observation["content"])

    def test_rejects_empty_payload_and_unsupported_mime_type(self):
        self.assertIsNone(build_live_visual_observation("", "image/jpeg"))
        self.assertIsNone(build_live_visual_observation("YWJj", "image/webp"))
        self.assertIsNone(build_live_visual_observation(b"abc", "image/jpeg"))

    def test_rate_limit_requires_full_interval(self):
        interval = LIVE_VISUAL_OBSERVATION_INTERVAL_SECONDS
        self.assertFalse(live_visual_observation_due(10.0 + interval - 0.01, 10.0))
        self.assertTrue(live_visual_observation_due(10.0 + interval, 10.0))

    def test_invalid_or_backwards_monotonic_values_are_rejected(self):
        self.assertFalse(live_visual_observation_due(True, 0.0))
        self.assertFalse(live_visual_observation_due(2.0, 3.0))
        self.assertFalse(live_visual_observation_due(-1.0, 0.0))


if __name__ == "__main__":
    unittest.main()
