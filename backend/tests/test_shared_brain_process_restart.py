"""Cognitive learning survives a real Python process boundary."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run_python(script: str, database: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-c", script, str(database)],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_cross_modal_learning_survives_independent_process_restart(tmp_path):
    database = tmp_path / "chappie-learning.sqlite3"
    writer = r'''
import sqlite3, sys
from learning.language import init_language_tables, record_heard_word, advance_word
from learning.sensory import init_sensory_tables, record_observation, associate_word_with_observation
from learning.perception_fusion import init_perception_fusion_tables, link_temporally_cooccurring_observation

db = sqlite3.connect(sys.argv[1])
db.row_factory = sqlite3.Row
db.execute("PRAGMA foreign_keys=ON")
init_language_tables(db)
init_sensory_tables(db)
init_perception_fusion_tables(db)
record_heard_word(db, "owner", "pomme", "Entendu pendant la session 1")
advance_word(db, "owner", "pomme", "imitated")
vision = record_observation(db, "owner", "vision", "Une pomme rouge.", "camera_test")
associate_word_with_observation(db, "owner", "pomme", vision["observation_id"])
audio = record_observation(db, "owner", "audio", "Le mot pomme.", "micro_test")
stamp = "2026-01-01T12:00:00+00:00"
db.execute("UPDATE sensory_observations SET created_at=? WHERE observation_id IN (?, ?)",
           (stamp, vision["observation_id"], audio["observation_id"]))
link_temporally_cooccurring_observation(db, "owner", audio["observation_id"], 30)
db.commit()
db.close()
'''
    first = _run_python(writer, database)
    assert first.returncode == 0, first.stdout + first.stderr

    reader = r'''
import json, sqlite3, sys
from cognition.shared_brain import get_shared_brain_snapshot, format_shared_brain_context

db = sqlite3.connect(sys.argv[1])
db.row_factory = sqlite3.Row
snapshot = get_shared_brain_snapshot(db, "owner")
assert snapshot["vocabulary"][0]["word"] == "pomme"
assert snapshot["word_visual_associations"][0]["word"] == "pomme"
assert snapshot["perception_fusions"][0]["status"] == "candidate"
assert snapshot["perception_fusions"][0]["evidence"]["rule"] == "temporal_cooccurrence_only"
context = format_shared_brain_context(snapshot)
assert "ASSOCIATIONS MOT-IMAGE" in context
assert "RAPPROCHEMENTS AUDIO-VISION" in context
print(json.dumps({
    "vocabulary": len(snapshot["vocabulary"]),
    "visual_associations": len(snapshot["word_visual_associations"]),
    "fusion_candidates": len(snapshot["perception_fusions"]),
}))
db.close()
'''
    second = _run_python(reader, database)
    assert second.returncode == 0, second.stdout + second.stderr
    assert '"visual_associations": 1' in second.stdout
    assert '"fusion_candidates": 1' in second.stdout
