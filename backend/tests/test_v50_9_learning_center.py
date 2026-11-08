"""V50.9 dashboard contract: supervised suggestions are visible and safe."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")


def test_authenticated_read_only_agenda_endpoint_exists():
    assert '@app.get("/api/learning/supervised-agenda")' in SERVER
    assert "return suggest_supervised_learning_agenda(db, user_id, limit=5)" in SERVER


def test_dashboard_has_supervised_learning_center_and_refresh():
    assert 'id="learningAgendaTitle"' in HTML
    assert 'id="learningAgendaList"' in HTML
    assert 'onclick="loadSupervisedAgenda()"' in HTML
    assert "préparer une piste ne lance rien" in HTML.lower()


def test_agenda_actions_only_prefill_existing_supervised_forms():
    assert 'apiCall("/api/learning/supervised-agenda")' in APP
    assert 'causalHypothesisId' in APP
    assert 'causalObservationId' in APP
    assert "aucune hypothèse ni expérience n'a été créée" in APP


def test_agenda_cards_use_text_content_and_dismissal_is_session_only():
    assert "title.textContent = item.topic" in APP
    assert "reason.textContent = item.reason" in APP
    assert "dismissedAgendaItems = new Set()" in APP
    assert "localStorage" not in APP[APP.index("// V50.9"):APP.index("// V34 — causal learning controls")]
