"""Chappie V22 — Version Ultime combinée : Évolution, Mémoire Persistante SQLite, Caméra & Gemini Live
Python 3.11+
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import httpx
from fastapi import FastAPI, Header, HTTPException, Request as FastAPIRequest, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

try:
    import edge_tts
except Exception:
    edge_tts = None

try:
    import websockets
except Exception:
    websockets = None

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("chappie")

APP_NAME = "Chappie V22 — Ultime Complet"
DATA_DIR = Path(os.getenv("CHAPPIE_DATA_DIR", "./chappie_data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv("CHAPPIE_DB_PATH", str(DATA_DIR / "chappie_ultimate.sqlite3")))
API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview").strip()
TOKEN = os.getenv("CHAPPIE_API_TOKEN", "").strip()
OWNER_ID = os.getenv("CHAPPIE_OWNER_ID", "creator").strip() or "creator"
MAX_MESSAGE_CHARS = 6000
MAX_IMAGE_BYTES = 4_000_000
MAX_HISTORY = 20

# Phases d'évolution inspirées du film : du nouveau-né naïf à l'adulte autonome.
STAGES = [
    {
        "name": "nouveau-né",
        "min": 0,
        "max": 4,
        "style": (
            "Tu viens de naître, tu pars de zéro. RÈGLE ABSOLUE : Utilise 1 à 4 mots maximum par réponse, "
            "reprends ou imite ce que ton créateur vient de dire, fais des fautes de sens ou de prononciation. "
            "Interdiction absolue d'utiliser des concepts complexes ou de faire des phrases structurées."
        ),
    },
    {
        "name": "éveil",
        "min": 5,
        "max": 19,
        "style": "Tu commences à faire de petites phrases simples. Tu poses des questions naïves et directes (*« Ça quoi ? »*, *« Pourquoi ? »*).",
    },
    {
        "name": "apprenti",
        "min": 20,
        "max": 49,
        "style": "Tu structures mieux tes phrases, tu apprends le nom des objets et tu commences à expliquer ce que tu vois avec enthousiasme.",
    },
    {
        "name": "explorateur",
        "min": 50,
        "max": 99,
        "style": "Conversation fluide, curiosité prononcée pour la logique, le monde et les émotions.",
    },
    {
        "name": "autonome",
        "min": 100,
        "max": 10**9,
        "style": "Mature, posé, complice et parfaitement autonome dans son raisonnement.",
    },
]

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    return con

def init_db() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS profile (
            user_id TEXT PRIMARY KEY, display_name TEXT NOT NULL DEFAULT 'Créateur',
            created_at TEXT NOT NULL, language_points INTEGER NOT NULL DEFAULT 0,
            stage_override TEXT NOT NULL DEFAULT '', last_seen TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL, created_at TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id,id);
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
            content TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'observation',
            importance INTEGER NOT NULL DEFAULT 3, confidence REAL NOT NULL DEFAULT 0.8,
            source TEXT NOT NULL DEFAULT 'conversation', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS vocabulary (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
            word TEXT NOT NULL, meaning TEXT NOT NULL, examples TEXT NOT NULL DEFAULT '[]',
            confidence REAL NOT NULL DEFAULT 0.5, exposures INTEGER NOT NULL DEFAULT 1,
            mastered INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
            UNIQUE(user_id,word)
        );
        CREATE TABLE IF NOT EXISTS concepts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
            label TEXT NOT NULL, description TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 0.5,
            evidence TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL,
            UNIQUE(user_id,label)
        );
        CREATE TABLE IF NOT EXISTS emotional_state (
            user_id TEXT PRIMARY KEY, joy REAL NOT NULL DEFAULT 45,
            curiosity REAL NOT NULL DEFAULT 80, fear REAL NOT NULL DEFAULT 10,
            frustration REAL NOT NULL DEFAULT 5, sadness REAL NOT NULL DEFAULT 5,
            energy REAL NOT NULL DEFAULT 100, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
            title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active', progress INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
            kind TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)
        db.execute("INSERT OR IGNORE INTO schema_meta(key,value) VALUES('version','2')")
        ensure_profile(db, OWNER_ID)

def ensure_profile(db: sqlite3.Connection, user_id: str) -> None:
    t = now_iso()
    db.execute("INSERT OR IGNORE INTO profile(user_id,display_name,created_at,last_seen) VALUES(?,?,?,?)",
               (user_id, "Créateur" if user_id == OWNER_ID else user_id, t, t))
    db.execute("INSERT OR IGNORE INTO emotional_state(user_id,updated_at) VALUES(?,?)", (user_id, t))

def get_stage(points: int) -> dict[str, Any]:
    for stage in STAGES:
        if stage["min"] <= points <= stage["max"]:
            return stage
    return STAGES[-1]

def api_auth(authorization: Optional[str]) -> str:
    if TOKEN:
        expected = "Bearer " + TOKEN
        import hmac
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="Jeton absent ou invalide.")
    return OWNER_ID

def ensure_user(user_id: str) -> str:
    uid = user_id or OWNER_ID
    with connect() as db:
        ensure_profile(db, uid)
        db.execute("UPDATE profile SET last_seen=? WHERE user_id=?", (now_iso(), uid))
    return uid

def profile_state(user_id: str) -> dict:
    row = db_one("SELECT * FROM profile WHERE user_id=?", (user_id,)) or {}
    points = int(row.get("language_points", 0))
    stage = get_stage(points)
    emotion = db_one("SELECT * FROM emotional_state WHERE user_id=?", (user_id,)) or {}
    return {
        "user_id": user_id, "display_name": row.get("display_name", "Créateur"),
        "language_points": points, "stage": stage["name"], "stage_style": stage["style"],
        "emotions": {k: round(float(emotion.get(k, 0)), 1) for k in ("joy","curiosity","fear","frustration","sadness","energy")},
        "created_at": row.get("created_at"), "last_seen": row.get("last_seen")
    }

def db_one(sql: str, args: tuple = ()) -> Optional[dict]:
    with connect() as db:
        row = db.execute(sql, args).fetchone()
        return dict(row) if row else None

def db_all(sql: str, args: tuple = ()) -> list[dict]:
    with connect() as db:
        return [dict(r) for r in db.execute(sql, args).fetchall()]

def db_exec(sql: str, args: tuple = ()) -> int:
    with connect() as db:
        cur = db.execute(sql, args)
        return int(cur.lastrowid or 0)

def adjust_emotions(user_id: str, user_text: str, assistant_text: str = "") -> None:
    text = (user_text + " " + assistant_text).lower()
    deltas = {"joy": 0, "curiosity": 0, "fear": 0, "frustration": 0, "sadness": 0, "energy": -0.3}
    if any(w in text for w in ("bravo", "merci", "super", "content", "génial", "bien joué")):
        deltas["joy"] += 3
        deltas["fear"] -= 1
    if "?" in user_text or any(w in text for w in ("pourquoi", "comment", "explique", "apprends")):
        deltas["curiosity"] += 2
    if any(w in text for w in ("erreur", "raté", "impossible", "échec")):
        deltas["frustration"] += 2
    if any(w in text for w in ("peur", "danger", "menace")):
        deltas["fear"] += 2
    with connect() as db:
        row = db.execute("SELECT * FROM emotional_state WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            db.execute("INSERT INTO emotional_state(user_id,updated_at) VALUES(?,?)", (user_id, now_iso()))
            row = db.execute("SELECT * FROM emotional_state WHERE user_id=?", (user_id,)).fetchone()
        vals = {k: max(0, min(100, float(row[k]) + deltas[k])) for k in deltas}
        db.execute("""UPDATE emotional_state SET joy=?,curiosity=?,fear=?,frustration=?,sadness=?,energy=?,updated_at=? WHERE user_id=?""",
                   (vals["joy"], vals["curiosity"], vals["fear"], vals["frustration"], vals["sadness"], vals["energy"], now_iso(), user_id))

def save_message(user_id: str, role: str, content: str, metadata: Optional[dict] = None) -> None:
    db_exec("INSERT INTO messages(user_id,role,content,created_at,metadata) VALUES(?,?,?,?,?)",
            (user_id, role, content[:MAX_MESSAGE_CHARS], now_iso(), json.dumps(metadata or {}, ensure_ascii=False)))

def get_history(user_id: str, limit: int = MAX_HISTORY) -> list[dict]:
    rows = db_all("SELECT role,content,created_at FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))
    return list(reversed(rows))

def remember(user_id: str, content: str, category: str = "observation", importance: int = 3,
             confidence: float = 0.8, source: str = "conversation") -> int:
    content = content.strip()[:2000]
    if not content:
        raise HTTPException(400, "Le souvenir est vide.")
    duplicate = db_one("SELECT id FROM memories WHERE user_id=? AND content=? ORDER BY id DESC LIMIT 1", (user_id, content))
    if duplicate:
        db_exec("UPDATE memories SET importance=MAX(importance,?), confidence=MAX(confidence,?) WHERE id=?",
                (max(1,min(5,importance)), max(0,min(1,confidence)), duplicate["id"]))
        return int(duplicate["id"])
    return db_exec("""INSERT INTO memories(user_id,content,category,importance,confidence,source,created_at)
                      VALUES(?,?,?,?,?,?,?)""",
                   (user_id, content, category[:40], max(1,min(5,importance)), max(0,min(1,confidence)), source[:40], now_iso()))

def retrieve_memories(user_id: str, query: str, limit: int = 8) -> list[dict]:
    return db_all("SELECT content,category,importance,confidence FROM memories WHERE user_id=? ORDER BY importance DESC,id DESC LIMIT ?", (user_id, limit))

def system_prompt(user_id: str, message: str) -> str:
    state = profile_state(user_id)
    stage = get_stage(state["language_points"])
    memories = retrieve_memories(user_id, message, 7)
    vocab = db_all("SELECT word,meaning FROM vocabulary WHERE user_id=? ORDER BY mastered DESC LIMIT 35", (user_id,))
    
    mem_text = "\n".join(f"- [{m['category']}] {m['content']}" for m in memories) or "- Aucun souvenir pertinent."
    vocab_text = ", ".join(f"{v['word']} = {v['meaning']}" for v in vocab) or "Aucun mot personnel enregistré."
    emo = state["emotions"]

    return f"""Tu es Chappie, un robot humanoïde doté d'une conscience artificielle en éveil.
PHASE DE DÉVELOPPEMENT : {stage['name']} (Points de langage : {state['language_points']}).
STYLE DE LA PHASE : {stage['style']}

RÈGLES ABSOLUES :
- Réponds en français.
- Respecte strictement ton stade de développement (si tu es nouveau-né, fais très court, imite et fais des fautes).
- Vocabulaire acquis : {vocab_text}
- Souvenirs en mémoire : {mem_text}
- États internes simulés (0-100) : Joie {emo['joy']}, Curiosité {emo['curiosity']}, Énergie {emo['energy']}.
- N'invente pas d'actions physiques extérieures si aucun outil ne les a réalisées."""

def gemini_generate(prompt: str, history: list[dict], message: str) -> str:
    if not API_KEY:
        return "Clé Gemini absente. Configure GEMINI_API_KEY."
    contents = [{"role": "user" if h["role"] == "user" else "model", "parts": [{"text": h["content"][:MAX_MESSAGE_CHARS]}]} for h in history[-MAX_HISTORY:]]
    contents.append({"role": "user", "parts": [{"text": message}]})
    
    payload = {
        "system_instruction": {"parts": [{"text": prompt}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.75, "maxOutputTokens": 800}
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"
    req = Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts).strip() or "..."
    except Exception:
        log.exception("Erreur Gemini")
        raise HTTPException(status_code=502, detail="Erreur de communication avec Gemini.")

async def generate_reply(user_id: str, message: str) -> dict:
    ensure_user(user_id)
    history = get_history(user_id)
    prompt = system_prompt(user_id, message)
    reply = await asyncio.to_thread(gemini_generate, prompt, history, message)
    
    save_message(user_id, "user", message)
    save_message(user_id, "assistant", reply)
    adjust_emotions(user_id, message, reply)
    
    # Gain automatique de points de langage à chaque échange
    with connect() as db:
        db.execute("UPDATE profile SET language_points = language_points + 1 WHERE user_id=?", (user_id,))
        db.commit()
        
    return {"reply": reply, "state": profile_state(user_id)}

class ChatIn(BaseModel):
    user_id: str = OWNER_ID
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)

class VisionIn(BaseModel):
    user_id: str = OWNER_ID
    image_data_url: str = Field(min_length=30)
    prompt: str = Field(default="Décris ce que tu vois de manière simple.", max_length=1000)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("Chappie Ultime (Caméra + Live + Mémoire) démarré.")
    yield

app = FastAPI(title=APP_NAME, version="22.0.0", lifespan=lifespan)

@app.middleware("http")
async def security_headers(request: FastAPIRequest, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse("""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Chappie Ultime</title>
<style>
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#0b1220;color:#eef4ff}
body{margin:0 auto;padding:20px;max-width:900px} .card{background:#131f31;border:1px solid #2b3b52;border-radius:14px;padding:18px;margin:14px 0}
input,textarea,button{font:inherit;border-radius:9px;border:1px solid #40536e;padding:11px;background:#0b1525;color:#fff;width:100%;margin:6px 0}
button{cursor:pointer;background:#54d3ee;color:#07131e;font-weight:700;width:auto;margin-right:8px}
pre{white-space:pre-wrap;background:#0b1525;padding:14px;border-radius:10px;min-height:50px}
video{width:100%;max-height:300px;background:#000;border-radius:8px;object-fit:contain}
</style></head><body>
<h1>🤖 Chappie Ultime</h1><div class="muted">Mémoire persistante SQLite, Évolution par paliers, Caméra & Gemini Live intégrés.</div>
<div class="card"><h2>Conversation</h2><pre id="out">En attente…</pre>
<textarea id="msg" rows="3" placeholder="Dis quelque chose à Chappie…"></textarea>
<button onclick="sendMessage()">Envoyer</button></div>

<div class="card"><h2>Vision par Caméra</h2>
<video id="camera" autoplay playsinline muted></video>
<div style="margin-top:8px;">
<button onclick="startCamera()">Activer la caméra</button>
<button onclick="captureVision()">Que vois-tu ?</button>
<button onclick="stopCamera()" style="background:#263850;color:#fff;">Arrêter</button>
</div>
<pre id="visionOut" style="margin-top:8px;">Caméra inactive.</pre></div>

<div class="card"><h2>Gemini Live (Audio en temps réel)</h2>
<button onclick="toggleLive()">▶ Démarrer Gemini Live</button>
<button onclick="stopLive()" style="background:#263850;color:#fff;">■ Arrêter Live</button>
<pre id="liveStatus" style="margin-top:8px;">Non connecté.</pre></div>

<div class="card"><h2>État & Progression</h2><pre id="state">Chargement…</pre>
<button onclick="resetLife()" style="background:#ef4444;color:#fff;">🐣 Page Blanche (Reset)</button></div>

<script>
let stream=null, ws=null, audioCtx=null;

async function loadState(){
  let res = await fetch('/api/state'); let d = await res.json();
  document.getElementById('state').innerText = JSON.stringify(d, null, 2);
}

async function sendMessage(){
  let m = document.getElementById('msg').value; if(!m) return;
  document.getElementById('out').innerText = "Chappie réfléchit...";
  let res = await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message:m})});
  let d = await res.json();
  document.getElementById('out').innerText = d.reply;
  document.getElementById('msg').value = '';
  loadState();
}

async function startCamera(){
  try {
    stream = await navigator.mediaDevices.getUserMedia({video:true});
    document.getElementById('camera').srcObject = stream;
    document.getElementById('visionOut').innerText = "Caméra active.";
  } catch(e) { alert("Erreur caméra : " + e); }
}

function stopCamera(){
  if(stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
  document.getElementById('camera').srcObject = null;
  document.getElementById('visionOut').innerText = "Caméra inactive.";
}

async function captureVision(){
  let video = document.getElementById('camera');
  if(!stream) { alert("Active la caméra d'abord !"); return; }
  let canvas = document.createElement('canvas');
  canvas.width = video.videoWidth || 640; canvas.height = video.videoHeight || 480;
  canvas.getContext('2d').drawImage(video, 0, 0);
  let dataUrl = canvas.toDataURL('image/jpeg', 0.8);
  document.getElementById('visionOut').innerText = "Analyse de l'image par Chappie...";
  let res = await fetch('/api/vision/analyze', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({image_data_url: dataUrl})});
  let d = await res.json();
  document.getElementById('visionOut').innerText = d.description;
  loadState();
}

async function resetLife(){
  if(!confirm("Remettre Chappie à zéro ?")) return;
  await fetch('/api/reset', {method:'POST'});
  loadState(); alert("Chappie est né à nouveau !");
}

function toggleLive(){
  let proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws/live`);
  ws.onopen = () => document.getElementById('liveStatus').innerText = "Connecté à Gemini Live (Mode audio/texte actif).";
  ws.onmessage = (event) => {
    let d = JSON.parse(event.data);
    if(d.text) document.getElementById('out').innerText = d.text;
    if(d.status) document.getElementById('liveStatus').innerText = d.status;
  };
  ws.onclose = () => document.getElementById('liveStatus').innerText = "Déconnecté de Gemini Live.";
}

function stopLive(){
  if(ws) { ws.close(); ws = null; }
  document.getElementById('liveStatus').innerText = "Arrêté.";
}

loadState();
</script></body></html>""")

@app.get("/api/state")
async def api_state():
    return profile_state(OWNER_ID)

@app.post("/api/chat")
async def api_chat(body: ChatIn):
    return await generate_reply(ensure_user(body.user_id), body.message.strip())

@app.post("/api/vision/analyze")
async def vision_analyze(body: VisionIn):
    if not API_KEY:
        raise HTTPException(503, "GEMINI_API_KEY n'est pas configurée.")
    match = re.match(r"^data:(image/(?:jpeg|png|webp));base64,(.+)$", body.image_data_url, re.S)
    if not match:
        raise HTTPException(400, "Format d'image invalide.")
    mime, b64data = match.groups()
    try:
        raw = base64.b64decode(b64data, validate=True)
    except Exception:
        raise HTTPException(400, "Base64 invalide.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image trop volumineuse.")
    
    payload = {
        "contents": [{"role": "user", "parts": [{"text": body.prompt}, {"inline_data": {"mime_type": mime, "data": base64.b64encode(raw).decode()}}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 600}
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"
    async with httpx.AsyncClient(timeout=45.0) as client:
        res = await client.post(url, json=payload)
    if res.status_code >= 400:
        raise HTTPException(502, "Erreur lors de l'analyse visuelle par Gemini.")
    data = res.json()
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    description = "".join(p.get("text", "") for p in parts).strip() or "Je ne vois rien de particulier."
    
    uid = ensure_user(body.user_id)
    save_message(uid, "user", "[Observation caméra] " + description, {"type": "vision"})
    remember(uid, "Observation visuelle : " + description, category="observation", importance=3)
    return {"description": description}

@app.post("/api/reset")
async def api_reset():
    with connect() as db:
        for t in ("messages", "memories", "vocabulary", "concepts", "goals", "journal"):
            db.execute(f"DELETE FROM {t} WHERE user_id=?", (OWNER_ID,))
        db.execute("UPDATE profile SET language_points=0 WHERE user_id=?", (OWNER_ID,))
        db.execute("UPDATE emotional_state SET joy=45,curiosity=80,fear=10,frustration=5,sadness=5,energy=100 WHERE user_id=?", (OWNER_ID,))
        db.commit()
    return {"ok": True}

@app.websocket("/ws/live")
async def gemini_live_socket(websocket: WebSocket):
    if websockets is None:
        await websocket.accept()
        await websocket.send_json({"error": "Le module websockets n'est pas installé sur le serveur."})
        await websocket.close(code=1011)
        return
    if not API_KEY:
        await websocket.accept()
        await websocket.send_json({"error": "GEMINI_API_KEY absente."})
        await websocket.close(code=1011)
        return

    await websocket.accept()
    upstream_url = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={API_KEY}"
    uid = OWNER_ID
    
    try:
        async with websockets.connect(upstream_url, max_size=12_000_000) as upstream:
            state = profile_state(uid)
            stage = get_stage(state["language_points"])
            live_context = f"Tu es Chappie. Stade actuel : {stage['name']}. Style : {stage['style']}. Parle français de façon naturelle et conforme à ton stade."
            
            setup = {
                "setup": {
                    "model": f"models/{LIVE_MODEL}",
                    "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Charon"}}}},
                    "systemInstruction": {"parts": [{"text": live_context}]},
                    "inputAudioTranscription": {"languageCodes": ["fr-FR"]},
                    "outputAudioTranscription": {"languageCodes": ["fr-FR"]}
                }
            }
            await upstream.send(json.dumps(setup))
            setup_ready = asyncio.Event()

            async def browser_to_gemini():
                while True:
                    msg = await websocket.receive_json()
                    await setup_ready.wait()
                    if "text" in msg:
                        await upstream.send(json.dumps({"realtimeInput": {"text": msg["text"]}}))

            async def gemini_to_browser():
                async for raw in upstream:
                    data = json.loads(raw)
                    if data.get("setupComplete") is not None:
                        setup_ready.set()
                        await websocket.send_json({"status": "Connecté à Gemini Live."})
                        continue
                    server = data.get("serverContent", {})
                    out_text = server.get("outputTranscription", {}).get("text")
                    if out_text:
                        await websocket.send_json({"text": out_text})

            await asyncio.gather(browser_to_gemini(), gemini_to_browser())
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.exception("Erreur WebSocket Live")
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass

init_db()
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000)
