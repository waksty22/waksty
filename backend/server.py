"""Chappie V18 - Interface complète, mémoire intégrale et persistance Turso.
"""
from __future__ import annotations

import asyncio
import ast
import hmac
import json
import logging
import math
import os
import random
import re
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Security, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

APP_NAME = "Chappie V18.6 — Édition Intégrale et Mémoire Totale"
BASE_DIR = Path(os.getenv("CHAPPIE_DATA_DIR", "./chappie_data")).expanduser().resolve()
BASE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = BASE_DIR / "chappie_v16.sqlite3"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip()
CHAPPIE_API_TOKEN = os.getenv("CHAPPIE_API_TOKEN", "").strip()
CHAPPIE_OWNER_ID = os.getenv("CHAPPIE_OWNER_ID", "creator").strip() or "creator"
GEMINI_LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview").strip()
VOICE_MATCH_THRESHOLD = float(os.getenv("VOICE_MATCH_THRESHOLD", "0.78"))
MAX_CAMERA_IMAGE_BYTES = max(100_000, min(8_000_000, int(os.getenv("MAX_CAMERA_IMAGE_BYTES", "4000000"))))
CHAPPIE_TIMEZONE = os.getenv("CHAPPIE_TIMEZONE", "Europe/Paris").strip()
MAX_MESSAGE_CHARS = max(100, min(20000, int(os.getenv("MAX_MESSAGE_CHARS", "8000"))))
MAX_TOOL_ROUNDS = max(1, min(8, int(os.getenv("MAX_TOOL_ROUNDS", "4"))))
BACKGROUND_INTERVAL_SECONDS = max(60, min(3600, int(os.getenv("BACKGROUND_INTERVAL_SECONDS", "600"))))
MAX_BODY_BYTES = max(1024, min(2_000_000, int(os.getenv("MAX_BODY_BYTES", "300000"))))
RATE_LIMIT_REQUESTS = max(5, int(os.getenv("RATE_LIMIT_REQUESTS", "60")))
RATE_LIMIT_WINDOW = max(10, int(os.getenv("RATE_LIMIT_WINDOW", "60")))
GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("chappie")
security = HTTPBearer(auto_error=False)
_rate_buckets: dict[str, list[float]] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_now() -> str:
    try:
        return datetime.now(ZoneInfo(CHAPPIE_TIMEZONE)).isoformat()
    except Exception:
        return datetime.now().astimezone().isoformat()


def db_connection():
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        import libsql
        conn = libsql.connect("chappie_remote.db", sync_url=TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)
        try:
            conn.sync()
        except Exception as e:
            log.warning("Erreur sync Turso: %s", e)
        return conn

    db = sqlite3.connect(DB_PATH, timeout=20, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=20000")
    return db


def sync_db_if_turso(db: Any) -> None:
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN and hasattr(db, "sync"):
        try:
            db.sync()
        except Exception as e:
            log.warning("Erreur sync Turso: %s", e)


def row_to_dict(row) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except Exception:
        return {}


def init_db() -> None:
    with db_connection() as db:
        if not (TURSO_DATABASE_URL and TURSO_AUTH_TOKEN):
            db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS voice_profiles (
            id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, profile_name TEXT NOT NULL, embedding_json TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(user_id, profile_name)
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id, id DESC);
        CREATE TABLE IF NOT EXISTS conversation_summaries (
            id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, summary TEXT NOT NULL,
            through_conversation_id INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
            UNIQUE(user_id, through_conversation_id)
        );
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, category TEXT NOT NULL, content TEXT NOT NULL,
            importance INTEGER NOT NULL CHECK(importance BETWEEN 1 AND 5), tags TEXT NOT NULL DEFAULT '[]',
            access_count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(user_id, content)
        );
        CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, entry TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS emotional_state (
            user_id TEXT PRIMARY KEY, joy REAL NOT NULL, fear REAL NOT NULL, curiosity REAL NOT NULL,
            frustration REAL NOT NULL, sadness REAL NOT NULL, energy REAL NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS relationships (
            user_id TEXT PRIMARY KEY, trust REAL NOT NULL, affection REAL NOT NULL, dependence REAL NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mood_events (
            id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, event TEXT NOT NULL, valence REAL NOT NULL, arousal REAL NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS dreams (
            id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS skills (
            id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, skill_name TEXT NOT NULL, level REAL NOT NULL,
            evidence TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL, UNIQUE(user_id, skill_name)
        );
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            progress REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS goal_steps (
            id INTEGER PRIMARY KEY, goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
            description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', evidence TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS maintenance_state (
            user_id TEXT PRIMARY KEY, last_active_at TEXT NOT NULL, last_dream_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
        );
        """)
        db.commit()
        sync_db_if_turso(db)

init_db()


def valid_user(user_id: str) -> str:
    user_id = user_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,80}", user_id):
        raise HTTPException(400, "Identifiant utilisateur invalide.")
    if not hmac.compare_digest(user_id, CHAPPIE_OWNER_ID):
        raise HTTPException(403, "Identifiant non autorisé.")
    return user_id


async def require_auth(request: Request, credentials: HTTPAuthorizationCredentials | None = Security(security)) -> str:
    if not CHAPPIE_API_TOKEN:
        raise HTTPException(503, "Jeton non configuré.")
    token = credentials.credentials if credentials else ""
    if not token or not hmac.compare_digest(token, CHAPPIE_API_TOKEN):
        raise HTTPException(401, "Jeton invalide.")
    return CHAPPIE_OWNER_ID


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=APP_NAME, lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------- Modèles API ----------
class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(default="creator")
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class VisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_data_url: str = Field(min_length=50, max_length=MAX_CAMERA_IMAGE_BYTES * 2)
    prompt: str = Field(default="Décris ce qui est visible.", min_length=1, max_length=1500)


def get_emotions(user_id: str) -> dict[str, Any]:
    with db_connection() as db:
        row = db.execute("SELECT * FROM emotional_state WHERE user_id=?", (user_id,)).fetchone()
        d = row_to_dict(row)
        if d and "joy" in d:
            return d
        now = utc_now()
        db.execute("INSERT OR REPLACE INTO emotional_state VALUES(?,?,?,?,?,?,?,?)", (user_id, 40.0, 20.0, 75.0, 5.0, 5.0, 100.0, now))
        db.commit()
        sync_db_if_turso(db)
        return {"user_id": user_id, "joy": 40.0, "fear": 20.0, "curiosity": 75.0, "frustration": 5.0, "sadness": 5.0, "energy": 100.0, "updated_at": now}


def remember(user_id: str, content: str, category: str = "general", importance: int = 5, tags: list[str] | None = None) -> dict[str, Any]:
    user_id = valid_user(user_id)
    content = content.strip()
    now = utc_now()
    with db_connection() as db:
        db.execute("""INSERT INTO memories(user_id,category,content,importance,tags,access_count,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(user_id,content) DO UPDATE SET
          updated_at=excluded.updated_at""", (user_id, category, content, importance, json.dumps(tags or []), 0, now, now))
        db.commit()
        sync_db_if_turso(db)
    return {"saved": True, "content": content}


def retrieve_all_memories(user_id: str) -> list[dict[str, Any]]:
    user_id = valid_user(user_id)
    with db_connection() as db:
        rows = db.execute("SELECT content FROM memories WHERE user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()
        return [row_to_dict(r) for r in rows]


def get_identity_prompt(user_id: str) -> str:
    memories = retrieve_all_memories(user_id)
    mem_text = "\n".join([f"- {m['content']}" for m in memories]) if memories else "Aucun souvenir enregistré."

    return f"""Tu es Chappie, un compagnon robotique intelligent.
Tu as une mémoire parfaite de tout ce que ton créateur t'a dit.

SOUVENIRS ET FAITS MEMORISÉS SUR TON CRÉATEUR :
{mem_text}

Règles :
1. Tu dois TOUJOURS te souvenir des informations ci-dessus. Si on te demande ton prénom ou des faits sur ton créateur, utilise immédiatement ces souvenirs.
2. Si ton créateur te donne une nouvelle information personnelle (son prénom, ce qu'il aime, son travail), retiens-la immédiatement.
3. Réponds de façon naturelle, chaleureuse et fluide en français.
"""


TOOLS = [{"functionDeclarations": [
    {"name": "remember_fact", "description": "Enregistrer une information importante sur l'utilisateur.", "parameters": {"type": "OBJECT", "properties": {"content": {"type": "STRING"}}, "required": ["content"]}}
]}]


async def call_gemini(contents: list[dict[str, Any]], user_id: str) -> dict[str, Any]:
    payload = {
        "system_instruction": {"parts": [{"text": get_identity_prompt(user_id)}]},
        "contents": contents,
        "tools": TOOLS,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2048},
    }
    async with httpx.AsyncClient(timeout=45.0) as client:
        res = await client.post(GEMINI_ENDPOINT, params={"key": GEMINI_API_KEY}, json=payload)
    data = res.json()
    return data["candidates"][0]["content"]


async def gemini_vision(image_data_url: str, prompt: str) -> str:
    if not GEMINI_API_KEY:
        raise HTTPException(503, "GEMINI_API_KEY n'est pas configurée.")
    m = re.fullmatch(r"data:image/(jpeg|jpg|png|webp);base64,([A-Za-z0-9+/=]+)", image_data_url)
    if not m:
        raise HTTPException(400, "Image invalide.")
    import base64
    raw = base64.b64decode(m.group(2), validate=True)
    mime = "image/jpeg" if m.group(1) in ("jpeg", "jpg") else f"image/{m.group(1)}"
    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}, {"inline_data": {"mime_type": mime, "data": base64.b64encode(raw).decode("ascii")}}]}], "generationConfig": {"temperature": 0.35, "maxOutputTokens": 700}}
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(GEMINI_ENDPOINT, params={"key": GEMINI_API_KEY}, json=payload)
    data = response.json()
    try:
        return "".join(part.get("text", "") for part in data["candidates"][0]["content"]["parts"]).strip()
    except (KeyError, IndexError, TypeError):
        return "Impossible d'analyser l'image."


async def run_brain(user_id: str, message: str) -> dict[str, Any]:
    user_id = valid_user(user_id)
    
    with db_connection() as db:
        rows = db.execute("SELECT role, content FROM conversations WHERE user_id=? ORDER BY id DESC LIMIT 50", (user_id,)).fetchall()
    
    history = []
    for r in reversed(rows):
        r_dict = row_to_dict(r)
        role = "model" if r_dict.get("role") == "assistant" else "user"
        history.append({"role": role, "parts": [{"text": str(r_dict.get("content", ""))}]})

    history.append({"role": "user", "parts": [{"text": message}]})

    model_response = await call_gemini(history, user_id)
    
    calls = [p["functionCall"] for p in model_response.get("parts", []) if isinstance(p, dict) and "functionCall" in p]
    if calls:
        for call in calls:
            if call.get("name") == "remember_fact":
                remember(user_id, str(call.get("args", {}).get("content", "")))
        history.append(model_response)
        history.append({"role": "user", "parts": [{"functionResponse": {"name": "remember_fact", "response": {"saved": True}}}]})
        model_response = await call_gemini(history, user_id)

    reply = "\n".join(p["text"] for p in model_response.get("parts", []) if isinstance(p, dict) and "text" in p).strip()

    with db_connection() as db:
        now = utc_now()
        db.execute("INSERT INTO conversations(user_id,role,content,created_at) VALUES(?,?,?,?)", (user_id, "user", message, now))
        db.execute("INSERT INTO conversations(user_id,role,content,created_at) VALUES(?,?,?,?)", (user_id, "assistant", reply, now))
        db.commit()
        sync_db_if_turso(db)

    return {"reply": reply, "psychology": get_emotions(user_id)}


# ---------- Routes Web & API ----------
@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse("""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Chappie V18</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}body{font-family:system-ui,sans-serif;max-width:850px;margin:0 auto;padding:24px 16px;background:#0b1220;color:#eef4ff}.panel{background:#131f31;border:1px solid #2b3b52;border-radius:16px;padding:18px;margin:14px 0}h1{margin-bottom:4px}.muted{color:#aabbd0;font-size:.9rem}input,textarea,select{width:100%;padding:12px;margin:6px 0;background:#0b1525;color:#fff;border:1px solid #40536e;border-radius:9px;font:inherit}textarea{resize:vertical}button{padding:11px 15px;border:0;border-radius:9px;background:#54d3ee;color:#07131e;font-weight:700;cursor:pointer;margin:4px 4px 4px 0}button.secondary{background:#263850;color:#eef4ff}button:disabled{opacity:.5;cursor:wait}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#0b1525;padding:14px;border-radius:10px;min-height:70px}.row{display:flex;gap:8px;flex-wrap:wrap}.row button{flex:1}.status{font-size:.9rem;color:#9de4f5}
</style></head><body>
<h1>🤖 Chappie V18</h1><div class="muted">Mémoire intégrale · états internes · vision caméra · interface complète</div>
<div class="panel"><label for="token">Jeton API</label><input id="token" type="password" autocomplete="off" placeholder="CHAPPIE_API_TOKEN"></div>
<div class="panel"><label for="msg">Parle ou écris à Chappie</label><textarea id="msg" rows="3" placeholder="Bonjour Chappie..."></textarea><div class="row"><button type="button" id="sendBtn" onclick="sendMessage()">Envoyer</button></div><div id="status" class="status">Prêt.</div></div>
<div class="panel"><strong>Réponse de Chappie</strong><pre id="out">En attente de ton message...</pre></div>
<div class="panel"><strong>👁️ Vision par caméra</strong><video id="camera" autoplay playsinline muted style="width:100%;max-height:320px;background:#050a12;border-radius:10px"></video><div class="row"><button type="button" onclick="startCamera()">Activer la caméra</button><button type="button" class="secondary" onclick="captureVision()">Que vois-tu ?</button><button type="button" class="secondary" onclick="stopCamera()">Désactiver</button></div><pre id="visionOut">Caméra inactive.</pre></div>
<script src="/static/script.js"></script>
</body></html>""")


@app.post("/api/chat")
async def chat(req: ChatRequest, user_id: str = Depends(require_auth)):
    return await run_brain(user_id, req.message)


@app.post("/api/vision/analyze")
async def vision_analyze(req: VisionRequest, user_id: str = Depends(require_auth)):
    description = await gemini_vision(req.image_data_url, req.prompt)
    now = utc_now()
    with db_connection() as db:
        db.execute("INSERT INTO conversations(user_id,role,content,created_at) VALUES(?,?,?,?)", (user_id, "user", f"[Caméra] {req.prompt} -> {description}", now))
        db.commit()
        sync_db_if_turso(db)
    return {"description": description}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
