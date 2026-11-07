"""V50 schema smoke test: initialize every cognitive subsystem on one libSQL DB.

Uses only an ephemeral local :memory: database; no remote Turso or production data.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import libsql

from storage.libsql_adapter import adapt_libsql_connection
from memory.episodic_memory import init_memory_tables
from memory.autobiographical import init_autobiographical_tables
from world.spatial_memory import init_spatial_tables
from world.world_model import init_world_tables
from learning.curriculum import init_learning_tables
from learning.language import init_language_tables
from learning.sensory import init_sensory_tables
from learning.object_learning import init_object_learning_tables
from learning.causal_learning import init_causal_learning_tables
from learning.supervised_learning import init_supervised_learning_tables
from learning.perception_fusion import init_perception_fusion_tables
from cognition.reasoning import init_cognition_tables
from cognition.development import init_development_tables


def test_all_cognitive_subsystems_initialize_on_one_libsql_connection():
    native = libsql.connect(database=":memory:")
    db = adapt_libsql_connection(native)
    initializers = (
        init_memory_tables,
        init_autobiographical_tables,
        init_spatial_tables,
        init_world_tables,
        init_learning_tables,
        init_language_tables,
        init_sensory_tables,
        init_object_learning_tables,
        init_causal_learning_tables,
        init_supervised_learning_tables,
        init_perception_fusion_tables,
        init_cognition_tables,
        init_development_tables,
    )
    try:
        for initialize in initializers:
            initialize(db)

        tables = {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        required_tables = {
            "memories_v19",
            "autobiographical_events",
            "spatial_sessions",
            "world_entities",
            "cognitive_milestones",
            "personal_vocabulary",
            "sensory_observations",
        }
        assert required_tables <= tables
        assert len(tables) >= 13
    finally:
        db.close()
