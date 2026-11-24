from pathlib import Path


def test_isolated_turso_restore_workflow_checks_out_current_main():
    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "chappie-isolated-turso-backup-restore.yml"
    ).read_text(encoding="utf-8")

    assert "name: Checkout guarded restore implementation" in workflow
    assert "ref: main" in workflow
    assert "ref: feat/safe-logical-restore-core" not in workflow
