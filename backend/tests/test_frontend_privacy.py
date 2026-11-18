from pathlib import Path


def test_live_websocket_payloads_are_not_written_to_browser_console():
    source = (
        Path(__file__).resolve().parents[1] / "static" / "js" / "app.js"
    ).read_text(encoding="utf-8")

    assert 'console.log("Message Live reçu :", data)' not in source
    assert 'console.error("Erreur Gemini Live :", data.message || data.error)' not in source
