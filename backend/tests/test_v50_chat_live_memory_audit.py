from pathlib import Path

DOC = Path(__file__).resolve().parents[1] / "docs" / "V50_33_CHAT_LIVE_MEMORY_AUDIT.md"


def test_chat_live_audit_records_shared_paths_and_open_gaps():
    text = DOC.read_text(encoding="utf-8")
    for required in (
        "/api/chat",
        "run_brain(user_id, message)",
        'source="gemini_live"',
        "get_shared_brain_snapshot()",
        "interrompus",
        "idempotence",
        "Turso isolé",
    ):
        assert required in text


def test_chat_live_audit_forbids_claiming_durable_memory_without_proof():
    text = DOC.read_text(encoding="utf-8")
    assert "Pas de bascule Turso" in text
    assert "Pas de déploiement" in text
    assert "Aucune promesse de mémoire durable" in text
