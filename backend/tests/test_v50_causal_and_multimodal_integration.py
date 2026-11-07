"""V50 causal reasoning and cautious multimodal fusion on local libSQL."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import libsql

from storage.libsql_adapter import adapt_libsql_connection
from learning.sensory import init_sensory_tables, record_observation
from learning.perception_fusion import (
    init_perception_fusion_tables,
    link_temporally_cooccurring_observation,
    list_perception_fusions,
)
from learning.causal_learning import (
    init_causal_learning_tables,
    record_observation as record_causal_observation,
    propose_hypothesis,
    plan_experiment,
    evaluate_experiment,
    list_causal_learning,
)


def test_causal_reasoning_and_multimodal_candidates_share_libsql():
    native = libsql.connect(database=":memory:")
    db = adapt_libsql_connection(native)
    try:
        init_sensory_tables(db)
        init_perception_fusion_tables(db)
        init_causal_learning_tables(db)

        # Two modalities close in time create only a reviewable candidate.
        audio = record_observation(
            db, "owner", "audio", "Un bruit de clochette.",
            "synthetic_test", confidence=0.75,
        )
        vision = record_observation(
            db, "owner", "vision", "Une petite cloche sur une table.",
            "synthetic_test", confidence=0.8,
        )
        candidates = link_temporally_cooccurring_observation(
            db, "owner", audio["observation_id"], window_seconds=120,
        )
        assert len(candidates) == 1
        assert candidates[0]["status"] == "candidate"
        assert candidates[0]["requires_validation"] is True
        fusion_rows = list_perception_fusions(db, "owner")
        assert len(fusion_rows) == 1
        assert fusion_rows[0]["status"] == "candidate"
        assert fusion_rows[0]["evidence"]["rule"] == "temporal_cooccurrence_only"
        assert list_perception_fusions(db, "other") == []

        # Causal knowledge remains a hypothesis until a supervised,
        # simulation-only experiment is explicitly approved and evaluated.
        observation = record_causal_observation(
            db, "owner", "Une clochette est secouée.",
            "Un son est entendu.", context="Exercice synthétique",
            source_type="taught", evidence="Donnée fictive de test.",
            confidence=0.6,
        )
        hypothesis = propose_hypothesis(
            db, "owner", observation["id"],
            "Secouer la clochette produit un son.",
            "Un son sera entendu.", confidence=0.4,
        )
        assert hypothesis["status"] == "proposed"

        try:
            plan_experiment(
                db, "owner", hypothesis["id"], "simulation",
                "Simuler un mouvement de clochette.",
                "Un son synthétique doit être produit.",
                supervisor_approved=False,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Une expérience sans approbation doit être refusée.")

        experiment = plan_experiment(
            db, "owner", hypothesis["id"], "simulation",
            "Simuler un mouvement de clochette.",
            "Un son synthétique doit être produit.",
            supervisor_approved=True,
        )
        assert experiment["status"] == "planned"
        evaluated = evaluate_experiment(
            db, "owner", experiment["id"],
            "Le son synthétique est présent.", "supported",
        )
        assert evaluated["status"] == "supported"
        assert evaluated["confidence"] > evaluated["previous_confidence"]

        history = list_causal_learning(db, "owner")
        assert len(history["observations"]) == 1
        assert len(history["hypotheses"]) == 1
        assert history["experiments"][0]["status"] == "completed"
        assert list_causal_learning(db, "other") == {
            "observations": [], "hypotheses": [], "experiments": [],
        }
    finally:
        db.close()
