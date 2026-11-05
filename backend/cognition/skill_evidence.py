"""Build cognitive skill levels only from distinct, supervised branch assessments."""
from __future__ import annotations

import json
from typing import Any

from cognition.catalog import COGNITIVE_CATALOG


def build_validated_skill_data(
    rows: list[dict[str, Any]],
    catalog: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], int]:
    """Return engine-shaped branch data and the number of unique passing proofs.

    Each row must come from a passing competency_tests record. Its details JSON
    must explicitly identify a supervisor-approved supervised_assessment and
    contain a non-empty evidence string. Duplicate evidence never adds levels.
    """
    source_catalog = catalog or COGNITIVE_CATALOG
    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for row in rows:
        try:
            system_key, branch_key = str(row["test_name"]).split(":", 1)
            details = row.get("details", {})
            if isinstance(details, str):
                details = json.loads(details or "{}")
            if not isinstance(details, dict):
                continue
            score = float(row["score"])
            passed = row.get("passed", 1)
        except (KeyError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if system_key not in source_catalog or passed not in (1, True) or not 70 <= score <= 100:
            continue
        branches = source_catalog[system_key].get("sub_branches", {})
        if branch_key not in branches:
            continue
        evidence = str(details.get("evidence", "")).strip()
        if (
            details.get("supervisor_approved") is not True
            or details.get("source") != "supervised_assessment"
            or not evidence
        ):
            continue
        grouped.setdefault((system_key, branch_key), {})[evidence] = {
            "score": score,
            "tested_at": str(row.get("tested_at", "")),
        }

    engine_data: dict[str, Any] = {}
    total = 0
    for (system_key, branch_key), evidence_map in grouped.items():
        assessments = list(evidence_map.values())
        scores = [item["score"] for item in assessments]
        average_score = sum(scores) / len(scores)
        confidence = min(1.0, len(assessments) / 3.0)
        # One supervised success is an initial signal, not mastery.
        engine_data.setdefault(system_key, {})[branch_key] = {
            "level": int(round(average_score * 0.30 * confidence)),
            "mastery": average_score,
            "confidence": confidence,
            "xp": len(assessments) * 10,
            "evidence": "Évaluations supervisées distinctes : " + str(len(assessments)),
        }
        total += len(assessments)
    return engine_data, total
