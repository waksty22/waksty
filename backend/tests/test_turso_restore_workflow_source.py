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


def test_daily_backup_artifact_triggers_local_recovery_without_production_connection():
    root = Path(__file__).resolve().parents[2]
    workflow = (
        root / ".github" / "workflows"
        / "chappie-isolated-turso-backup-restore.yml"
    ).read_text(encoding="utf-8")
    recovery = (
        root / "scripts" / "test_daily_encrypted_backup_recovery.py"
    ).read_text(encoding="utf-8")

    assert "workflow_run:" in workflow
    assert "Chappie Turso encrypted backup" in workflow
    assert "actions/download-artifact@v8" in workflow
    assert "github.event.workflow_run.id" in workflow
    assert "BACKUP_ENCRYPTION_KEY" in workflow
    assert "restore_daily_artifact" in recovery
    assert 'sqlite3.connect(":memory:")' in recovery
    assert "production_database_contacted" in recovery
    assert "CHAPPIE_PRODUCTION_TURSO_DATABASE_URL" not in recovery
