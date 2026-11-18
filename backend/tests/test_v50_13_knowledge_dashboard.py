"""V50.13 — read-only knowledge library dashboard contract."""
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SERVER = (BACKEND / "server.py").read_text(encoding="utf-8")
HTML = (BACKEND / "static" / "index.html").read_text(encoding="utf-8")
APP = (BACKEND / "static" / "js" / "app.js").read_text(encoding="utf-8")


def test_authenticated_read_only_knowledge_endpoint_uses_user_scope():
    route = SERVER.split('@app.get("/api/learning/knowledge")', 1)[1].split(
        '@app.get("/api/learning/supervised-agenda")', 1
    )[0]
    assert "auth=Depends(require_auth)" in route
    assert "_authenticated_user(auth)" in route
    assert "retrieve_acquired_knowledge(db, user_id" in route
    assert "INSERT " not in route.upper()
    assert "DELETE " not in route.upper()


def test_dashboard_has_search_and_provenance_labels():
    assert 'id="acquiredKnowledgeQuery"' in HTML
    assert 'id="acquiredKnowledgeList"' in HTML
    assert "loadAcquiredKnowledge()" in HTML
    assert "Souvenir confirmé" in APP
    assert "Enseigné · maîtrise non vérifiée" in APP
    assert "Observé · compréhension non vérifiée" in APP
    assert "Compétence validée sous supervision" in APP


def test_dashboard_uses_safe_text_rendering_and_read_only_api():
    assert '"/api/learning/knowledge?"' in APP
    assert "card.append(meta, title, content, source)" in APP
    assert "innerHTML" not in APP[APP.index("// V50.13 — provenance-aware knowledge library"):APP.index("// V50.10 — supervised personal learning goals")]
    assert "lecture seule" in APP


def test_knowledge_library_loads_when_dashboard_starts_with_saved_token():
    tail = APP[APP.rfind("if (savedToken)"):]
    assert "window.loadAcquiredKnowledge();" in tail
