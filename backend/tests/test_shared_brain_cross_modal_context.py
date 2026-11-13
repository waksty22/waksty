"""Cross-modal learning evidence is included in the shared chat/Live brain."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from cognition.shared_brain import get_shared_brain_snapshot, format_shared_brain_context
from learning.language import init_language_tables, record_heard_word, advance_word
from learning.sensory import (
    init_sensory_tables, record_observation, associate_word_with_observation,
)
from learning.perception_fusion import (
    init_perception_fusion_tables, link_temporally_cooccurring_observation,
)


def test_shared_brain_includes_visual_associations_and_unconfirmed_audio_vision_candidates():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        init_language_tables(db)
        init_sensory_tables(db)
        init_perception_fusion_tables(db)

        record_heard_word(db, "owner", "pomme", "Mot entendu")
        advance_word(db, "owner", "pomme", "imitated")

        vision = record_observation(
            db, "owner", "vision", "Une pomme rouge sur une table.",
            "test_camera", confidence=0.9,
        )
        association = associate_word_with_observation(
            db, "owner", "pomme", vision["observation_id"],
            evidence="Association validée dans le test",
        )
        assert association["vocabulary_state"] == "recognized"

        audio = record_observation(
            db, "owner", "audio", "J'entends le mot pomme.",
            "test_microphone", confidence=0.8,
        )
        # Make the timestamps deterministic and co-occurring for this test.
        db.execute(
            "UPDATE sensory_observations SET created_at=? WHERE observation_id IN (?, ?)",
            ("2026-01-01T12:00:00+00:00", vision["observation_id"], audio["observation_id"]),
        )
        candidates = link_temporally_cooccurring_observation(
            db, "owner", audio["observation_id"], window_seconds=30,
        )
        assert len(candidates) == 1
        assert candidates[0]["status"] == "candidate"
        assert candidates[0]["requires_validation"] is True

        snapshot = get_shared_brain_snapshot(db, "owner")
        assert len(snapshot["word_visual_associations"]) == 1
        assert snapshot["word_visual_associations"][0]["word"] == "pomme"
        assert len(snapshot["perception_fusions"]) == 1
        assert snapshot["perception_fusions"][0]["status"] == "candidate"
        assert snapshot["perception_fusions"][0]["evidence"]["rule"] == "temporal_cooccurrence_only"

        context = format_shared_brain_context(snapshot)
        assert "ASSOCIATIONS MOT-IMAGE" in context
        assert "RAPPROCHEMENTS AUDIO-VISION" in context
        assert "pas des identités confirmées" in context
    finally:
        db.close()
