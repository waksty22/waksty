import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cognition.skill_evidence import build_validated_skill_data, normalize_evidence_text


def test_evidence_normalization_collapses_case_and_whitespace():
    assert normalize_evidence_text("  Chappie   connaît le mot. ") == normalize_evidence_text("CHAPPIE connaît LE MOT.")


def test_only_supervised_passing_branch_evidence_changes_profile():
    rows = [
        {
            "test_name": "mots:vocabulaire",
            "passed": 1,
            "score": 80,
            "tested_at": "2026-11-05T10:00:00Z",
            "details": {
                "source": "supervised_assessment",
                "supervisor_approved": True,
                "evidence": "Chappie a correctement répété dix mots distincts.",
            },
        },
        {
            "test_name": "mots:syntaxe",
            "passed": 1,
            "score": 95,
            "details": {"source": "model_generated", "evidence": "auto-évaluation"},
        },
        {
            "test_name": "unknown:branch",
            "passed": 1,
            "score": 100,
            "details": {
                "source": "supervised_assessment",
                "supervisor_approved": True,
                "evidence": "Une preuve distincte suffisamment détaillée.",
            },
        },
    ]
    profile, count = build_validated_skill_data(rows)
    assert count == 1
    assert profile["mots"]["vocabulaire"]["level"] == 8
    assert "syntaxe" not in profile["mots"]


def test_duplicate_evidence_does_not_increase_skill_level():
    proof = "Il a identifié correctement le même objet dans cinq essais."
    details = {
        "source": "supervised_assessment",
        "supervisor_approved": True,
        "evidence": proof,
    }
    rows = [
        {"test_name": "sens:reconnaissance_visuelle", "passed": 1, "score": 90, "details": details},
        {"test_name": "sens:reconnaissance_visuelle", "passed": 1, "score": 90, "details": details},
    ]
    profile, count = build_validated_skill_data(rows)
    assert count == 1
    assert profile["sens"]["reconnaissance_visuelle"]["xp"] == 10
    assert profile["sens"]["reconnaissance_visuelle"]["confidence"] == 1 / 3
    assert profile["sens"]["reconnaissance_visuelle"]["level"] == 9



def test_duplicate_evidence_ignores_case_and_whitespace_variations():
    rows = [
        {
            "test_name": "mots:vocabulaire", "passed": 1, "score": 90,
            "tested_at": "2026-11-01T10:00:00Z",
            "details": {
                "source": "supervised_assessment", "supervisor_approved": True,
                "evidence": "Chappie reconnaît correctement le mot appris.",
            },
        },
        {
            "test_name": "mots:vocabulaire", "passed": 1, "score": 100,
            "tested_at": "2026-11-02T10:00:00Z",
            "details": {
                "source": "supervised_assessment", "supervisor_approved": True,
                "evidence": "  CHAPPIE   RECONNAÎT correctement le mot appris.  ",
            },
        },
    ]
    profile, count = build_validated_skill_data(rows)
    assert count == 1
    assert profile["mots"]["vocabulaire"]["confidence"] == 1 / 3
    assert profile["mots"]["vocabulaire"]["level"] == 9

def test_duplicate_proof_cannot_upgrade_score_with_repeated_submission():
    proof = "Chappie a correctement identifié le même mot dans un exercice contrôlé."
    details = {
        "source": "supervised_assessment",
        "supervisor_approved": True,
        "evidence": proof,
    }
    # Deliberately provide the newer, higher score first: the result
    # must be based on chronology, not database/input iteration order.
    rows = [
        {"test_name": "mots:vocabulaire", "passed": 1, "score": 100,
         "tested_at": "2026-11-02T10:00:00Z", "details": details},
        {"test_name": "mots:vocabulaire", "passed": 1, "score": 70,
         "tested_at": "2026-11-01T10:00:00Z", "details": details},
    ]
    profile, count = build_validated_skill_data(rows)
    assert count == 1
    assert profile["mots"]["vocabulaire"]["confidence"] == 1 / 3
    # The earliest score is retained; a duplicate cannot raise the level.
    assert profile["mots"]["vocabulaire"]["level"] == 7



def test_explicitly_empty_catalog_does_not_fall_back_to_default():
    rows = [{
        "test_name": "mots:vocabulaire",
        "passed": 1,
        "score": 90,
        "tested_at": "2026-11-03T10:00:00Z",
        "details": {
            "source": "supervised_assessment",
            "supervisor_approved": True,
            "evidence": "Chappie a répété correctement le mot observé.",
        },
    }]
    profile, count = build_validated_skill_data(rows, catalog={})
    assert profile == {}
    assert count == 0


def test_malformed_catalog_entries_are_ignored_safely():
    row = {
        "test_name": "mots:vocabulaire",
        "passed": 1,
        "score": 90,
        "tested_at": "2026-11-03T10:00:00Z",
        "details": {
            "source": "supervised_assessment",
            "supervisor_approved": True,
            "evidence": "Chappie a répété correctement le mot observé.",
        },
    }
    for catalog in (None, [], {"mots": None}, {"mots": {"sub_branches": []}}):
        if catalog is None:
            continue  # None deliberately selects the built-in catalog.
        profile, count = build_validated_skill_data([row], catalog=catalog)
        assert profile == {}
        assert count == 0


def test_overflowing_persisted_score_is_ignored_without_crashing():
    row = {
        "test_name": "mots:vocabulaire",
        "passed": 1,
        "score": 10 ** 10000,
        "tested_at": "2026-11-03T10:00:00Z",
        "details": {
            "source": "supervised_assessment",
            "supervisor_approved": True,
            "evidence": "Chappie a répété correctement le mot observé.",
        },
    }
    profile, count = build_validated_skill_data([row])
    assert profile == {}
    assert count == 0

def test_failed_or_unapproved_assessment_is_ignored():
    rows = [
        {
            "test_name": "tete:logique_formelle",
            "passed": 0,
            "score": 60,
            "details": {
                "source": "supervised_assessment",
                "supervisor_approved": True,
                "evidence": "Test supervisé mais score inférieur au seuil.",
            },
        },
        {
            "test_name": "tete:logique_formelle",
            "passed": 1,
            "score": 95,
            "details": {
                "source": "supervised_assessment",
                "supervisor_approved": False,
                "evidence": "Pas de validation du superviseur.",
            },
        },
    ]
    profile, count = build_validated_skill_data(rows)
    assert count == 0
    assert profile == {}



def test_three_distinct_supervised_proofs_unlock_full_score_level():
    rows = []
    for index in range(3):
        rows.append({
            "test_name": "mots:vocabulaire",
            "passed": 1,
            "score": 80,
            "tested_at": f"2026-11-0{index + 1}T10:00:00Z",
            "details": {
                "source": "supervised_assessment",
                "supervisor_approved": True,
                "evidence": f"Preuve indépendante numéro {index + 1}.",
            },
        })
    profile, count = build_validated_skill_data(rows)
    assert count == 3
    assert profile["mots"]["vocabulaire"]["confidence"] == 1.0
    assert profile["mots"]["vocabulaire"]["level"] == 24



def test_supervised_skill_profile_rebuilds_after_database_restart(tmp_path):
    import sqlite3

    from cognition.engine import CognitiveEngine
    from learning.curriculum import init_learning_tables, evaluate_competency_test

    database_path = tmp_path / "chappie-learning.sqlite3"
    proof_rows = [
        "Chappie distingue correctement le mot prononcé pendant le premier exercice.",
        "Chappie répète le mot correctement dans un contexte différent.",
        "Chappie reconnaît et réutilise le mot sans aide supplémentaire.",
    ]

    first_connection = sqlite3.connect(database_path)
    first_connection.row_factory = sqlite3.Row
    try:
        init_learning_tables(first_connection)
        for index, proof in enumerate(proof_rows):
            evaluate_competency_test(
                first_connection,
                "owner",
                "mots:vocabulaire",
                True,
                80 + index,
                {
                    "source": "supervised_assessment",
                    "supervisor_approved": True,
                    "evidence": proof,
                },
            )
        first_connection.commit()
        persisted_rows = [
            dict(row)
            for row in first_connection.execute(
                """SELECT test_name, passed, score, details, tested_at
                   FROM competency_tests WHERE user_id=?
                   ORDER BY tested_at ASC, id ASC""",
                ("owner",),
            ).fetchall()
        ]
        initial_skill_data, initial_count = build_validated_skill_data(persisted_rows)
        initial_engine = CognitiveEngine(cache_ttl=3600)
        initial_profile = initial_engine.compute_cognitive_profile(
            "owner", initial_skill_data, force_recompute=True,
        )
    finally:
        first_connection.close()

    # Simule un nouveau processus : la connexion et le cache cognitif repartent de zéro.
    second_connection = sqlite3.connect(database_path)
    second_connection.row_factory = sqlite3.Row
    try:
        restored_rows = [
            dict(row)
            for row in second_connection.execute(
                """SELECT test_name, passed, score, details, tested_at
                   FROM competency_tests WHERE user_id=?
                   ORDER BY tested_at ASC, id ASC""",
                ("owner",),
            ).fetchall()
        ]
    finally:
        second_connection.close()

    assert restored_rows == persisted_rows
    restored_skill_data, evidence_count = build_validated_skill_data(restored_rows)
    assert initial_count == evidence_count == 3

    restarted_engine = CognitiveEngine(cache_ttl=3600)
    restored_profile = restarted_engine.compute_cognitive_profile(
        "owner", restored_skill_data, force_recompute=True,
    )
    assert restored_profile["global_maturity"] == initial_profile["global_maturity"]
    assert restored_profile["systems"] == initial_profile["systems"]
    branch = restored_profile["systems"]["mots"]["sub_branches"]["vocabulaire"]
    assert branch["confidence"] == 1.0
    assert branch["level"] == 24


def test_skill_assessment_route_rejects_overflowing_score_with_422(monkeypatch):
    import asyncio
    import server
    from fastapi import HTTPException

    class FakeRequest:
        async def json(self):
            return {
                "system": "mots",
                "branch": "vocabulaire",
                "evidence": "Chappie a correctement répété le mot observé.",
                "supervisor_approved": True,
                "score": 10 ** 10000,
            }

    monkeypatch.setattr(server, "_authenticated_user", lambda auth: "owner")
    with pytest.raises(HTTPException) as error:
        asyncio.run(server.api_record_skill_assessment(FakeRequest(), auth="creator"))
    assert error.value.status_code == 422
