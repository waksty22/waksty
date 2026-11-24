import sqlite3
import unittest

from learning.sensory import init_sensory_tables, list_observations, record_observation
from learning.live_visual_observation import (
    LIVE_VISUAL_OBSERVATION_INTERVAL_SECONDS,
    build_live_visual_observation,
    build_gemini_visual_observation,
    live_visual_observation_due,
)


class LiveVisualObservationTests(unittest.TestCase):
    def test_frame_receipt_does_not_claim_semantic_understanding(self):
        observation = build_live_visual_observation("YWJj", "image/jpeg")
        self.assertIsNotNone(observation)
        self.assertEqual(observation["modality"], "vision")
        self.assertEqual(observation["source"], "live_camera_frame_received_by_server")
        self.assertEqual(observation["confidence"], 0.0)
        self.assertFalse(observation["metadata"]["image_bytes_persisted"])
        self.assertFalse(observation["metadata"]["semantic_analysis_performed"])
        self.assertIn("ne décrit pas le contenu", observation["content"])
        self.assertIn("ne confirme ni sa transmission au modèle", observation["content"])

    def test_rejects_empty_payload_and_unsupported_mime_type(self):
        self.assertIsNone(build_live_visual_observation("", "image/jpeg"))
        self.assertIsNone(build_live_visual_observation("YWJj", "image/webp"))
        self.assertIsNone(build_live_visual_observation(b"abc", "image/jpeg"))

    def test_rate_limit_requires_full_interval(self):
        interval = LIVE_VISUAL_OBSERVATION_INTERVAL_SECONDS
        self.assertFalse(live_visual_observation_due(10.0 + interval - 0.01, 10.0))
        self.assertTrue(live_visual_observation_due(10.0 + interval, 10.0))


    def test_session_and_frame_provenance_are_attached_without_image_bytes(self):
        observation = build_live_visual_observation(
            "YWJj", "image/jpeg", session_id="live-session-1", frame_sequence=17
        )
        self.assertEqual(observation["metadata"]["session_id"], "live-session-1")
        self.assertEqual(observation["metadata"]["frame_sequence"], 17)
        self.assertFalse(observation["metadata"]["image_bytes_persisted"])

    def test_invalid_session_provenance_is_rejected(self):
        for session_id, sequence in (
            ("", 1),
            ("x" * 129, 1),
            (7, 1),
            ("session", 0),
            ("session", True),
            ("session", 1.5),
        ):
            self.assertIsNone(
                build_live_visual_observation(
                    "YWJj", "image/jpeg", session_id=session_id,
                    frame_sequence=sequence,
                )
            )


    def test_session_provenance_survives_sensory_database_round_trip(self):
        observation = build_live_visual_observation(
            "YWJj", "image/jpeg", session_id="session-round-trip", frame_sequence=9
        )
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        init_sensory_tables(db)
        record_observation(
            db,
            "creator",
            observation["modality"],
            observation["content"],
            observation["source"],
            confidence=observation["confidence"],
            metadata=observation["metadata"],
        )
        db.commit()
        saved = list_observations(db, "creator")[0]
        self.assertEqual(saved["metadata"]["session_id"], "session-round-trip")
        self.assertEqual(saved["metadata"]["frame_sequence"], 9)
        self.assertFalse(saved["metadata"]["image_bytes_persisted"])
        db.close()

    def test_invalid_or_backwards_monotonic_values_are_rejected(self):
        self.assertFalse(live_visual_observation_due(True, 0.0))
        self.assertFalse(live_visual_observation_due(2.0, 3.0))
        self.assertFalse(live_visual_observation_due(-1.0, 0.0))


    def test_gemini_analysis_is_stored_with_explicit_unverified_provenance(self):
        observation = build_gemini_visual_observation(
            "Une forme rouge arrondie est visible.",
            "gemini-3.6-flash",
            "image/jpeg",
            "Décris les éléments visibles.",
        )
        self.assertIsNotNone(observation)
        self.assertEqual(observation["modality"], "vision")
        self.assertEqual(observation["source"], "gemini_image_analysis")
        self.assertEqual(observation["content"], "Une forme rouge arrondie est visible.")
        self.assertEqual(observation["confidence"], 0.0)
        self.assertTrue(observation["metadata"]["model_generated"])
        self.assertTrue(observation["metadata"]["semantic_analysis_performed"])
        self.assertFalse(observation["metadata"]["semantic_understanding_confirmed"])
        self.assertTrue(observation["metadata"]["human_review_required"])
        self.assertFalse(observation["metadata"]["image_bytes_persisted"])
        self.assertFalse(observation["metadata"]["is_learned_fact"])

    def test_gemini_visual_analysis_rejects_missing_or_invalid_provenance(self):
        invalid_cases = (
            ("", "gemini-3.6-flash", "image/jpeg", "question"),
            ("description", "", "image/jpeg", "question"),
            ("description", "gemini-3.6-flash", "image/gif", "question"),
            ("description", "gemini-3.6-flash", "image/jpeg", "q" * 1001),
            ("x" * 12001, "gemini-3.6-flash", "image/jpeg", "question"),
        )
        for args in invalid_cases:
            self.assertIsNone(build_gemini_visual_observation(*args))


if __name__ == "__main__":
    unittest.main()
