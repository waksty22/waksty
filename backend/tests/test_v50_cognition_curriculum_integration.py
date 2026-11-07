"""V50 reasoning, decisions, preferences and curriculum on shared libSQL."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import libsql

from storage.libsql_adapter import adapt_libsql_connection
from cognition.reasoning import (
    init_cognition_tables, log_cognitive_trace,
    evaluate_decision_doubt, get_cognitive_traces,
    run_metacognitive_audit,
)
from cognition.development import (
    init_development_tables, record_affective_snapshot,
    record_decision, evaluate_decision, list_decisions,
    record_preference, list_preferences,
)
from learning.curriculum import (
    init_learning_tables, evaluate_competency_test,
    update_cognitive_milestones, get_learning_statistics,
)


def test_reasoning_development_and_curriculum_share_libsql():
    native = libsql.connect(database=":memory:")
    db = adapt_libsql_connection(native)
    try:
        init_cognition_tables(db)
        init_development_tables(db)
        init_learning_tables(db)

        trace = log_cognitive_trace(
            db, "owner", "analysis", "Exercice de raisonnement synthétique",
            "Comparer deux options", 0.55,
        )
        assert trace["confidence"] == 0.55
        assert evaluate_decision_doubt(0.2)["requires_doubt"] is True
        assert len(get_cognitive_traces(db, "owner")) == 1
        audit = run_metacognitive_audit(db, "owner")
        assert audit["trace_count"] == 1

        affect = record_affective_snapshot(
            db, "owner",
            {"joy": 65, "curiosity": 80, "energy": 90},
            source="synthetic_test", event_label="test",
        )
        assert affect["state"]["joy"] == 65

        decision = record_decision(
            db, "owner", "Quel objet choisir ?",
            ["objet A", "objet B"], chosen_option="objet A",
            reasons="Choix fictif du test.", confidence=0.7,
            evidence=["Donnée synthétique"],
        )
        evaluated = evaluate_decision(
            db, "owner", decision["id"], "Résultat simulé satisfaisant.",
        )
        assert evaluated["status"] == "evaluated"
        assert list_decisions(db, "owner")[0]["status"] == "evaluated"

        preference = record_preference(
            db, "owner", "interface", "thème sombre",
            "Préférence explicitement déclarée dans le scénario de test.",
        )
        assert preference["basis"] == "explicit_statement"
        assert len(list_preferences(db, "owner")) == 1
        assert list_preferences(db, "other") == []

        competency = evaluate_competency_test(
            db, "owner", "reconnaissance_exercice", True, 90,
            {"source": "synthetic_test"},
        )
        assert competency["passed"] is True
        milestones = update_cognitive_milestones(db, "owner", 1.0)
        assert any(item["status"] == "achieved" for item in milestones)
        stats = get_learning_statistics(db, "owner")
        assert stats["total_tests"] == 1
        assert stats["passed_tests"] == 1
    finally:
        db.close()
