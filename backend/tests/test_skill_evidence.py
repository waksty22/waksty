import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cognition.skill_evidence import build_validated_skill_data


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
    assert profile["mots"]["vocabulaire"]["level"] == 24
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
        {"test_name": "sens:reconnaissance_visuelle", "score": 90, "details": details},
    ]
    profile, count = build_validated_skill_data(rows)
    assert count == 1
    assert profile["sens"]["reconnaissance_visuelle"]["xp"] == 10
    assert profile["sens"]["vision"]["confidence"] == 1 / 3


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
