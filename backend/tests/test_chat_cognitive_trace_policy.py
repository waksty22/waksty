import sqlite3

from cognition.reasoning import (
    evaluate_memory_relevance_doubt,
    init_cognition_tables,
    log_cognitive_trace,
    get_cognitive_traces,
)


def test_empty_memory_retrieval_is_not_recorded_as_low_confidence():
    assert evaluate_memory_relevance_doubt([]) is None
    assert evaluate_memory_relevance_doubt(None) is None


def test_low_confidence_trace_requires_actual_memory_evidence():
    result = evaluate_memory_relevance_doubt([
        {"confidence": 0.2},
        {"confidence": 0.4},
    ])
    assert result is not None
    assert result["requires_doubt"] is True
    assert result["confidence"] == 0.3


def test_invalid_memory_rows_do_not_create_a_false_doubt_signal():
    assert evaluate_memory_relevance_doubt([None, "not-a-memory"]) is None


def test_trace_persists_bounded_neutral_context_without_user_message():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_cognition_tables(db)
    trace = log_cognitive_trace(
        db, "creator", "incertitude_contexte_memoire",
        "Les éléments de mémoire récupérés présentent une confiance limitée.",
        "Demander une vérification ou des informations complémentaires.",
        0.3,
    )
    rows = get_cognitive_traces(db, "creator")
    assert len(rows) == 1
    assert "insulte" not in rows[0]["context_summary"].casefold()
    assert "message utilisateur" not in rows[0]["context_summary"].casefold()
    assert trace["confidence"] == 0.3
    db.close()
