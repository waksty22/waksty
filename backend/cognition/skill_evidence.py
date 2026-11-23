"""Build cognitive skill levels only from distinct, supervised branch assessments."""
from __future__ import annotations

import json
import math
from typing import Any

from cognition.catalog import COGNITIVE_CATALOG

MIN_EVIDENCE_LENGTH = 20
MAX_EVIDENCE_LENGTH = 2000


def normalize_evidence_text(value: str) -> str:
    """Normalize evidence for duplicate detection without changing its stored text."""
    return " ".join(value.split()).casefold()


def _assessment_details(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    return value if isinstance(value, dict) else None


def build_validated_skill_data(
    rows: list[dict[str, Any]],
    catalog: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], int]:
    """Return engine-shaped branch data and the number of unique passing proofs.

    A row must contain an exact branch key, a finite numeric passing score,
    explicit supervisor approval, the supervised-assessment source, and
    meaningful textual evidence. Invalid/coerced values are ignored.
    """
    source_catalog = COGNITIVE_CATALOG if catalog is None else catalog
    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    if not isinstance(rows, list) or not isinstance(source_catalog, dict):
        return {}, 0

    for row in rows:
        if not isinstance(row, dict):
            continue
        test_name = row.get("test_name")
        if not isinstance(test_name, str) or test_name.count(":") != 1:
            continue
        system_key, branch_key = (part.strip() for part in test_name.split(":", 1))
        if not system_key or not branch_key or system_key not in source_catalog:
            continue
        system_info = source_catalog[system_key]
        if not isinstance(system_info, dict):
            continue

        details = _assessment_details(row.get("details", {}))
        if not isinstance(details, dict):
            continue

        raw_score = row.get("score")
        if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
            continue
        try:
            score = float(raw_score)
        except (OverflowError, TypeError, ValueError):
            continue
        if not math.isfinite(score) or not 70 <= score <= 100:
            continue

        passed = row.get("passed")
        if isinstance(passed, bool) or not isinstance(passed, int) or passed != 1:
            continue

        branches = system_info.get("sub_branches", {})
        if not isinstance(branches, dict) or branch_key not in branches:
            continue
        branch_info = branches[branch_key]
        if not isinstance(branch_info, dict):
            continue

        evidence_value = details.get("evidence")
        if not isinstance(evidence_value, str):
            continue
        evidence = evidence_value.strip()
        if not MIN_EVIDENCE_LENGTH <= len(evidence) <= MAX_EVIDENCE_LENGTH:
            continue
        # Ignore superficial case/whitespace differences when identifying
        # a repeated proof; retain the original text only for validation.
        evidence_key = normalize_evidence_text(evidence)
        if (
            details.get("supervisor_approved") is not True
            or details.get("source") != "supervised_assessment"
        ):
            continue

        tested_at = row.get("tested_at", "")
        if not isinstance(tested_at, str):
            continue
        # Keep the earliest dated result for an exact proof, regardless
        # of input order. If legacy rows have no timestamp, prefer a dated
        # result; if both are undated, retain the first encountered result.
        # Re-submitting identical evidence with a higher score must not
        # silently upgrade the skill; independent evidence is required.
        evidence_map = grouped.setdefault((system_key, branch_key), {})
        existing = evidence_map.get(evidence_key)
        candidate = {"score": score, "tested_at": tested_at}
        if existing is None:
            evidence_map[evidence_key] = candidate
        else:
            existing_date = existing["tested_at"]
            if tested_at and (not existing_date or tested_at < existing_date):
                evidence_map[evidence_key] = candidate

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
