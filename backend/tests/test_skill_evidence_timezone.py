from cognition.skill_evidence import build_validated_skill_data


def _row(score, tested_at):
    return {
        "test_name": "mots:vocabulaire",
        "passed": 1,
        "score": score,
        "tested_at": tested_at,
        "details": {
            "source": "supervised_assessment",
            "supervisor_approved": True,
            "evidence": "Chappie reconnaît correctement le même mot appris.",
        },
    }


def test_duplicate_proof_uses_absolute_time_across_timezone_offsets():
    # 09:00+02:00 is 07:00Z, earlier than 07:30Z.
    rows = [
        _row(100, "2026-11-26T07:30:00Z"),
        _row(70, "2026-11-26T09:00:00+02:00"),
    ]
    profile, count = build_validated_skill_data(rows)
    assert count == 1
    assert profile["mots"]["vocabulaire"]["level"] == 7


def test_duplicate_proof_prefers_valid_timestamp_over_malformed_timestamp():
    rows = [
        _row(100, "not-a-timestamp"),
        _row(70, "2026-11-26T07:00:00Z"),
    ]
    profile, count = build_validated_skill_data(rows)
    assert count == 1
    assert profile["mots"]["vocabulaire"]["level"] == 7
