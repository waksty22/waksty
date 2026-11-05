"""Consent-based spatial memory for Chappie.

Stores only explicit browser geolocation samples and textual visual place
observations. A GPS coordinate or visual resemblance is evidence, not proof
of identity. No background tracking is performed by this module.
"""
from __future__ import annotations

import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finite(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} invalide.")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} invalide.") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name} hors limites.")
    return number


def _text(value: Any, name: str, limit: int, required: bool = False) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise ValueError(f"{name} est obligatoire.")
    if len(result) > limit:
        raise ValueError(f"{name} dépasse {limit} caractères.")
    return result


def init_spatial_tables(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS spatial_sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            device_label TEXT NOT NULL DEFAULT '',
            consented INTEGER NOT NULL DEFAULT 1 CHECK(consented IN (0,1)),
            started_at TEXT NOT NULL,
            ended_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_spatial_sessions_user
            ON spatial_sessions(user_id, started_at DESC);

        CREATE TABLE IF NOT EXISTS spatial_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            accuracy_m REAL,
            altitude_m REAL,
            heading_deg REAL,
            speed_mps REAL,
            recorded_at TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'browser_geolocation',
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES spatial_sessions(session_id)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_spatial_visits_user_time
            ON spatial_visits(user_id, recorded_at);
        CREATE INDEX IF NOT EXISTS idx_spatial_visits_session
            ON spatial_visits(session_id, recorded_at);

        CREATE TABLE IF NOT EXISTS place_memories (
            place_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL,
            visual_signature TEXT NOT NULL DEFAULT '',
            latitude REAL,
            longitude REAL,
            confidence REAL NOT NULL DEFAULT 0.0,
            identity_status TEXT NOT NULL DEFAULT 'unconfirmed'
                CHECK(identity_status IN ('unconfirmed','candidate','confirmed')),
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            observations_count INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_place_memories_user
            ON place_memories(user_id, last_seen_at DESC);
    """)
    db.commit()


def start_location_session(
    db: sqlite3.Connection, user_id: str, consented: bool,
    device_label: str = ""
) -> dict[str, Any]:
    if consented is not True:
        raise ValueError("Le consentement explicite est nécessaire.")
    now = _now()
    session_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO spatial_sessions
           (session_id,user_id,device_label,consented,started_at,created_at)
           VALUES (?,?,?,?,?,?)""",
        (session_id, user_id, _text(device_label, "Appareil", 80), 1, now, now),
    )
    db.commit()
    return {
        "session_id": session_id, "user_id": user_id,
        "started_at": now, "consented": True,
    }


def stop_location_session(
    db: sqlite3.Connection, user_id: str, session_id: str
) -> dict[str, Any]:
    row = db.execute(
        "SELECT * FROM spatial_sessions WHERE session_id=? AND user_id=?",
        (session_id, user_id),
    ).fetchone()
    if row is None:
        raise ValueError("Session de localisation introuvable.")
    now = _now()
    db.execute(
        "UPDATE spatial_sessions SET ended_at=? WHERE session_id=? AND user_id=?",
        (now, session_id, user_id),
    )
    db.commit()
    return {"session_id": session_id, "ended_at": now, "stopped": True}


def record_location(
    db: sqlite3.Connection, user_id: str, session_id: str,
    latitude: Any, longitude: Any, accuracy_m: Any = None,
    altitude_m: Any = None, heading_deg: Any = None, speed_mps: Any = None,
    recorded_at: str = ""
) -> dict[str, Any]:
    session = db.execute(
        """SELECT session_id FROM spatial_sessions
           WHERE session_id=? AND user_id=? AND consented=1 AND ended_at IS NULL""",
        (session_id, user_id),
    ).fetchone()
    if session is None:
        raise ValueError("Aucune session de localisation active et autorisée.")
    lat = _finite(latitude, "Latitude", -90, 90)
    lon = _finite(longitude, "Longitude", -180, 180)
    accuracy = None if accuracy_m is None else _finite(accuracy_m, "Précision", 0, 100000)
    if accuracy is not None and accuracy > 250:
        raise ValueError("Précision GPS insuffisante (plus de 250 m).")
    altitude = None if altitude_m is None else _finite(altitude_m, "Altitude", -12000, 100000)
    heading = None if heading_deg is None else _finite(heading_deg, "Cap", 0, 360)
    speed = None if speed_mps is None else _finite(speed_mps, "Vitesse", 0, 500)
    stamp = _text(recorded_at, "Horodatage", 64) or _now()
    # Avoid duplicate browser samples caused by repeated callbacks.
    previous = db.execute(
        """SELECT latitude,longitude,recorded_at FROM spatial_visits
           WHERE session_id=? ORDER BY id DESC LIMIT 1""",
        (session_id,),
    ).fetchone()
    if previous and previous["recorded_at"] == stamp:
        return {"stored": False, "reason": "duplicate_timestamp"}
    cursor = db.execute(
        """INSERT INTO spatial_visits
           (user_id,session_id,latitude,longitude,accuracy_m,altitude_m,
            heading_deg,speed_mps,recorded_at,source,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,'browser_geolocation',?)""",
        (user_id, session_id, lat, lon, accuracy, altitude, heading, speed, stamp, _now()),
    )
    db.commit()
    return {"stored": True, "id": cursor.lastrowid, "latitude": lat, "longitude": lon,
            "accuracy_m": accuracy, "recorded_at": stamp}


def record_place_observation(
    db: sqlite3.Connection, user_id: str, description: str,
    latitude: Any = None, longitude: Any = None,
    label: str = "", visual_signature: str = "", confidence: Any = 0.35
) -> dict[str, Any]:
    description = _text(description, "Description visuelle", 4000, True)
    label = _text(label, "Nom du lieu", 120)
    signature = _text(visual_signature, "Signature visuelle", 1000) or description.casefold()
    conf = _finite(confidence, "Confiance", 0, 1)
    lat = None if latitude is None else _finite(latitude, "Latitude", -90, 90)
    lon = None if longitude is None else _finite(longitude, "Longitude", -180, 180)
    if (lat is None) != (lon is None):
        raise ValueError("Latitude et longitude doivent être fournies ensemble.")
    now = _now()
    place_id = "place-" + str(uuid.uuid4())
    # A visual description is stored as an observation. It never auto-confirms
    # a named landmark or a familiar location.
    db.execute(
        """INSERT INTO place_memories
           (place_id,user_id,label,description,visual_signature,latitude,longitude,
            confidence,identity_status,first_seen_at,last_seen_at,observations_count,
            created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,'unconfirmed',?,?,1,?,?)""",
        (place_id, user_id, label, description, signature, lat, lon, conf,
         now, now, now, now),
    )
    db.commit()
    return {"place_id": place_id, "label": label, "description": description,
            "latitude": lat, "longitude": lon, "confidence": conf,
            "identity_status": "unconfirmed", "observations_count": 1}


def get_map_state(
    db: sqlite3.Connection, user_id: str, limit: int = 2000
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 5000))
    visits = db.execute(
        """SELECT v.id,v.session_id,v.latitude,v.longitude,v.accuracy_m,
                  v.recorded_at,v.source,s.device_label
           FROM spatial_visits v
           JOIN spatial_sessions s ON s.session_id=v.session_id
           WHERE v.user_id=? ORDER BY v.recorded_at ASC LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    sessions = db.execute(
        """SELECT session_id,device_label,started_at,ended_at
           FROM spatial_sessions WHERE user_id=? ORDER BY started_at DESC LIMIT 100""",
        (user_id,),
    ).fetchall()
    places = db.execute(
        """SELECT place_id,label,description,latitude,longitude,confidence,
                  identity_status,first_seen_at,last_seen_at,observations_count
           FROM place_memories WHERE user_id=? ORDER BY last_seen_at DESC LIMIT 200""",
        (user_id,),
    ).fetchall()
    return {
        "sessions": [dict(row) for row in sessions],
        "visits": [dict(row) for row in visits],
        "places": [dict(row) for row in places],
        "statistics": {
            "sessions": db.execute(
                "SELECT COUNT(*) FROM spatial_sessions WHERE user_id=?", (user_id,)
            ).fetchone()[0],
            "location_samples": db.execute(
                "SELECT COUNT(*) FROM spatial_visits WHERE user_id=?", (user_id,)
            ).fetchone()[0],
            "known_place_observations": db.execute(
                "SELECT COUNT(*) FROM place_memories WHERE user_id=?", (user_id,)
            ).fetchone()[0],
        },
        "tracking_requires_active_consent": True,
        "visual_identity_is_not_automatically_confirmed": True,
    }
