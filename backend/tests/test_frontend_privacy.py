from pathlib import Path


def test_live_websocket_payloads_are_not_written_to_browser_console():
    source = (
        Path(__file__).resolve().parents[1] / "static" / "js" / "app.js"
    ).read_text(encoding="utf-8")

    assert 'console.log("Message Live reçu :", data)' not in source
    assert 'console.error("Erreur Gemini Live :", data.message || data.error)' not in source



def test_perception_fusion_review_ui_is_explicit_and_uses_safe_dom_text():
    backend = Path(__file__).resolve().parents[1]
    source = (backend / "static" / "js" / "app.js").read_text(encoding="utf-8")
    html = (backend / "static" / "index.html").read_text(encoding="utf-8")
    start = source.index("window.loadPerceptionFusions")
    end = source.index("window.loadKnownObjects", start)
    review_ui = source[start:end]

    assert "/api/perception/fusions" in review_ui
    assert "/review" in review_ui
    assert "textContent" in review_ui
    assert "innerHTML" not in review_ui
    assert 'item.status === "candidate"' in review_ui
    assert "proof.value" in review_ui
    assert 'id="perceptionFusionList"' in html
    assert "Actualiser les rapprochements" in html
    assert "Une coïncidence temporelle n'est pas une identité" in html
