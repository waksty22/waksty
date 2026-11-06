from diagnostics.runtime import collect_runtime_snapshot


def test_runtime_snapshot_is_safe_and_serializable():
    snapshot = collect_runtime_snapshot()

    assert snapshot["pid"] > 0
    assert snapshot["python_version"]
    assert snapshot["platform"]
    assert snapshot["uptime_seconds"] >= 0
    assert isinstance(snapshot["port_configured"], bool)
    assert "TURSO_AUTH_TOKEN" not in snapshot
    assert "GEMINI_API_KEY" not in snapshot
