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



def test_live_visual_observations_can_be_selected_for_supervised_word_association():
    backend = Path(__file__).resolve().parents[1]
    source = (backend / "static" / "js" / "app.js").read_text(encoding="utf-8")
    html = (backend / "static" / "index.html").read_text(encoding="utf-8")
    start = source.index("window.loadSensoryObservations")
    end = source.index("window.loadPerceptionFusions", start)
    sensory_ui = source[start:end]

    assert "/api/senses/observations" in sensory_ui
    assert "semantic_analysis_performed === true" in sensory_ui
    assert "human_review_required === true" in sensory_ui
    assert "is_learned_fact === false" in sensory_ui
    assert "Sélectionner pour associer un mot" in sensory_ui
    assert "field.value = item.observation_id" in sensory_ui
    assert "createElement" in sensory_ui
    assert "textContent" in sensory_ui
    assert "innerHTML" not in sensory_ui
    assert 'id="sensoryHistory"' in html
    assert 'id="visionObservationId"' in html



def test_word_visual_association_requires_user_supplied_evidence():
    backend = Path(__file__).resolve().parents[1]
    source = (backend / "static" / "js" / "app.js").read_text(encoding="utf-8")
    html = (backend / "static" / "index.html").read_text(encoding="utf-8")
    start = source.index("window.associateVisionWord")
    end = source.index("window.loadSensoryObservations", start)
    association_ui = source[start:end]

    assert 'getElementById("visionEvidence")' in association_ui
    assert "evidence.length > 500" in association_ui
    assert "evidence: evidence" in association_ui
    assert "validée manuellement par le créateur" not in association_ui
    assert 'id="visionEvidence"' in html
    assert 'maxlength="500"' in html
    assert "Preuve visuelle observée" in html
