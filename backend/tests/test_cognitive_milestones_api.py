"""Regression tests for persisted cognitive milestones."""
from __future__ import annotations

import asyncio


def test_cognitive_milestones_route_returns_only_evidenced_owner_skills(
    monkeypatch, tmp_path
):
    import server

    database_path = tmp_path / "cognitive-milestones.sqlite3"
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("CHAPPIE_SQLITE_PATH", str(database_path))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CHAPPIE_ALLOW_TURSO_MIGRATION", raising=False)
    monkeypatch.setattr(server, "DB_PATH", database_path)
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)

    server.init_db()
    with server.db_connection() as db:
        db.execute(
            """INSERT INTO skills
               (user_id, skill_name, level, xp, evidence, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("creator", "vocabulaire", 5, 50, "Preuve validée par le créateur.", "2026-11-24T10:00:00Z"),
        )
        db.execute(
            """INSERT INTO skills
               (user_id, skill_name, level, xp, evidence, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("creator", "logique", 10, 100, "", "2026-11-24T10:01:00Z"),
        )
        db.execute(
            """INSERT INTO skills
               (user_id, skill_name, level, xp, evidence, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("other-user", "vocabulaire", 10, 100, "Preuve d'un autre utilisateur.", "2026-11-24T10:02:00Z"),
        )
        db.commit()

    response = asyncio.run(server.api_cognition_milestones(auth="creator"))
    milestones = response["milestones"]

    assert [item["id"] for item in milestones] == [
        "premier_palier:vocabulaire",
        "progression_confirmee:vocabulaire",
    ]
    assert all(item["source"] == "persisted_supervised_skill" for item in milestones)
    assert all(item["evidence"] == "Preuve validée par le créateur." for item in milestones)
    assert all(item["skill_name"] == "vocabulaire" for item in milestones)


def test_cognitive_milestones_rejects_blank_user_id():
    from cognition.engine import get_cognitive_milestones

    assert get_cognitive_milestones("   ") == []
