from pathlib import Path

DOC = Path(__file__).resolve().parents[1] / "docs" / "V50_32_MIGRATION_PLAN.md"


def test_migration_plan_requires_dry_run_and_complete_inventory():
    text = DOC.read_text(encoding="utf-8")
    for required in (
        "Dry-run local",
        "nombre de lignes",
        "empreintes de contenu",
        "clés étrangères",
        "index",
        "idempotentes",
        "sans valeurs de souvenirs",
    ):
        assert required in text


def test_migration_plan_forbids_unapproved_production_cutover():
    text = DOC.read_text(encoding="utf-8")
    assert "approbation explicite distincte" in text
    assert "Aucune opération distante ou de production" in text
    assert "conserver la source intacte" in text
