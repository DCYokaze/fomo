from contextlib import contextmanager

from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os
import psycopg2
import psycopg2.extras
import psycopg2.pool

app = FastAPI(title="Game Monitor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your Cloud Run URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── DB ───────────────────────────────────────────────────────────────────────

_pool: psycopg2.pool.ThreadedConnectionPool | None = None

@contextmanager
def get_db():
    conn = _pool.getconn()
    try:
        yield conn
    finally:
        _pool.putconn(conn)

# ─── Auth ─────────────────────────────────────────────────────────────────────

HUNTER_KEYS = set(os.environ.get("HUNTER_API_KEYS", "hunter-key-1").split(","))
PAYER_KEYS  = set(os.environ.get("PAYER_API_KEYS",  "payer-key-1").split(","))
TRAY_KEYS   = set(os.environ.get("TRAY_API_KEYS",   "tray-key-1").split(","))

def require_hunter(x_api_key: str = Header(...)):
    if x_api_key not in HUNTER_KEYS:
        raise HTTPException(status_code=401, detail="Hunter key required")
    return x_api_key

def require_payer(x_api_key: str = Header(...)):
    if x_api_key not in PAYER_KEYS:
        raise HTTPException(status_code=401, detail="Payer key required")
    return x_api_key

def require_tray(x_api_key: str = Header(...)):
    if x_api_key not in TRAY_KEYS:
        raise HTTPException(status_code=401, detail="Tray app key required")
    return x_api_key

# ─── DB Init ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
def init_db():
    global _pool
    _pool = psycopg2.pool.ThreadedConnectionPool(2, 10, os.environ["DATABASE_URL"])
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id          TEXT PRIMARY KEY,
                    payer_name  TEXT NOT NULL,
                    game        TEXT NOT NULL,
                    created_at  TIMESTAMPTZ DEFAULT now()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id           SERIAL PRIMARY KEY,
                    account_id   TEXT REFERENCES accounts(id),
                    hunter_id    TEXT,
                    status       TEXT DEFAULT 'open',
                    working      BOOLEAN DEFAULT FALSE,
                    note         TEXT,
                    created_at   TIMESTAMPTZ DEFAULT now(),
                    accepted_at  TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ
                )
            """)
            cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS working BOOLEAN DEFAULT FALSE")
            cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS game TEXT")
            cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress TEXT")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS heartbeats (
                    id          SERIAL PRIMARY KEY,
                    account_id  TEXT REFERENCES accounts(id),
                    game        TEXT NOT NULL,
                    status      TEXT NOT NULL,
                    timestamp   TIMESTAMPTZ DEFAULT now()
                )
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_heartbeats_lookup
                ON heartbeats (account_id, timestamp DESC)
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS games (
                    id    SERIAL PRIMARY KEY,
                    name  TEXT UNIQUE NOT NULL
                )
            """)

            cur.executemany(
                "INSERT INTO games (name) VALUES (%s) ON CONFLICT DO NOTHING",
                [("Genshin Impact",), ("Star Rail",), ("Honkai Impact 3rd",)]
            )

            # Seed demo account
            cur.execute("""
                INSERT INTO accounts (id, payer_name, game)
                VALUES ('player_a', 'Alex (Payer)', 'Black Desert Online')
                ON CONFLICT DO NOTHING
            """)

        conn.commit()
    print("DB ready")

# ─── Models ───────────────────────────────────────────────────────────────────

class Heartbeat(BaseModel):
    account_id: str
    game: str
    status: str

class JobCreate(BaseModel):
    account_id: str
    game: str
    note: Optional[str] = ""

class JobAccept(BaseModel):
    hunter_id: str

class JobProgress(BaseModel):
    progress: str  # "queued" | "in_progress"

# ─── Tray App Endpoints ────────────────────────────────────────────────────────

@app.post("/heartbeat")
def receive_heartbeat(hb: Heartbeat, _=Depends(require_tray)):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO heartbeats (account_id, game, status) VALUES (%s, %s, %s)",
                (hb.account_id, hb.game, hb.status)
            )
        conn.commit()
    return {"ok": True}

# ─── Hunter Endpoints ─────────────────────────────────────────────────────────

@app.get("/hunter/jobs")
def hunter_list_jobs(_=Depends(require_hunter)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT j.id, j.account_id, j.status, j.working, j.progress, j.note, j.created_at,
                       COALESCE(j.game, a.game) AS game, a.payer_name,
                       h.status as online_status, h.timestamp as last_seen
                FROM jobs j
                JOIN accounts a ON a.id = j.account_id
                LEFT JOIN LATERAL (
                    SELECT status, timestamp FROM heartbeats
                    WHERE account_id = j.account_id
                    ORDER BY timestamp DESC LIMIT 1
                ) h ON true
                WHERE j.status = 'open'
                ORDER BY j.created_at DESC
            """)
            rows = cur.fetchall()
    return {"jobs": [dict(r) for r in rows]}

@app.get("/hunter/my-jobs/{hunter_id}")
def hunter_my_jobs(hunter_id: str, _=Depends(require_hunter)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT j.id, j.account_id, j.hunter_id, j.status, j.working, j.progress, j.note,
                       j.created_at, j.accepted_at, j.completed_at,
                       COALESCE(j.game, a.game) AS game, a.payer_name,
                       h.status as online_status, h.timestamp as last_seen
                FROM jobs j
                JOIN accounts a ON a.id = j.account_id
                LEFT JOIN LATERAL (
                    SELECT status, timestamp FROM heartbeats
                    WHERE account_id = j.account_id
                    ORDER BY timestamp DESC LIMIT 1
                ) h ON true
                WHERE j.hunter_id = %s
                ORDER BY j.created_at DESC
            """, (hunter_id,))
            rows = cur.fetchall()
    return {"jobs": [dict(r) for r in rows]}

@app.post("/hunter/jobs/{job_id}/accept")
def hunter_accept_job(job_id: int, body: JobAccept, _=Depends(require_hunter)):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE jobs SET status='active', hunter_id=%s, accepted_at=now(), progress='queued'
                WHERE id=%s AND status='open'
                RETURNING id
            """, (body.hunter_id, job_id))
            row = cur.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found or already taken")
    return {"ok": True, "job_id": job_id}

@app.post("/hunter/jobs/{job_id}/complete")
def hunter_complete_job(job_id: int, _=Depends(require_hunter)):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE jobs SET status='completed', completed_at=now()
                WHERE id=%s AND status='active'
                RETURNING id
            """, (job_id,))
            row = cur.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found or not active")
    return {"ok": True}

@app.post("/hunter/jobs/{job_id}/progress")
def hunter_set_progress(job_id: int, body: JobProgress, _=Depends(require_hunter)):
    if body.progress not in ("queued", "in_progress"):
        raise HTTPException(status_code=400, detail="progress must be 'queued' or 'in_progress'")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE jobs SET progress=%s
                WHERE id=%s AND status='active'
                RETURNING id
            """, (body.progress, job_id))
            row = cur.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found or not active")
    return {"ok": True, "progress": body.progress}

@app.post("/hunter/jobs/{job_id}/working")
def hunter_toggle_working(job_id: int, _=Depends(require_hunter)):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE jobs SET working = NOT working
                WHERE id=%s AND status='active'
                RETURNING id, working
            """, (job_id,))
            row = cur.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found or not active")
    return {"ok": True, "working": row[1]}

# ─── Payer Endpoints ──────────────────────────────────────────────────────────

@app.get("/payer/status/{account_id}")
def payer_status(account_id: str, _=Depends(require_payer)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT status, timestamp FROM heartbeats
                WHERE account_id=%s
                ORDER BY timestamp DESC LIMIT 1
            """, (account_id,))
            heartbeat = cur.fetchone()
    return {
        "account_id": account_id,
        "online_status": heartbeat["status"] if heartbeat else "unknown",
        "last_seen": str(heartbeat["timestamp"]) if heartbeat else None,
    }

@app.get("/payer/jobs/{account_id}")
def payer_list_jobs(account_id: str, status: Optional[str] = None, _=Depends(require_payer)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if status:
                cur.execute("""
                    SELECT j.id, j.status, j.progress, j.game, j.hunter_id,
                           j.note, j.created_at, j.accepted_at, j.completed_at
                    FROM jobs j
                    WHERE j.account_id=%s AND j.status=%s
                    ORDER BY j.created_at DESC
                """, (account_id, status))
            else:
                cur.execute("""
                    SELECT j.id, j.status, j.progress, j.game, j.hunter_id,
                           j.note, j.created_at, j.accepted_at, j.completed_at
                    FROM jobs j
                    WHERE j.account_id=%s
                    ORDER BY j.created_at DESC
                """, (account_id,))
            rows = cur.fetchall()
    return {"jobs": [dict(r) for r in rows]}

@app.get("/payer/history/{account_id}")
def payer_history(account_id: str, _=Depends(require_payer)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT status, timestamp FROM heartbeats
                WHERE account_id=%s
                ORDER BY timestamp DESC LIMIT 50
            """, (account_id,))
            rows = cur.fetchall()
    return {"history": [dict(r) for r in rows]}

@app.delete("/payer/jobs/{job_id}")
def payer_delete_job(job_id: int, _=Depends(require_payer)):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM jobs WHERE id=%s AND status='open' RETURNING id
            """, (job_id,))
            row = cur.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found or already accepted")
    return {"ok": True}

@app.get("/payer/games")
def payer_list_games(_=Depends(require_payer)):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM games ORDER BY id")
            names = [row[0] for row in cur.fetchall()]
    return {"games": names}

@app.post("/payer/jobs")
def payer_create_job(body: JobCreate, _=Depends(require_payer)):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (account_id, game, note) VALUES (%s, %s, %s) RETURNING id",
                (body.account_id, body.game, body.note)
            )
            job_id = cur.fetchone()[0]
        conn.commit()
    return {"ok": True, "job_id": job_id}

# ─── Static Clients — mount LAST ──────────────────────────────────────────────
# /         → static/index.html  (landing / role picker)
# /hunter/  → static/hunter/index.html
# /payer/   → static/payer/index.html

@app.get("/", include_in_schema=False)
def landing():
    return FileResponse("static/index.html")

app.mount("/hunter", StaticFiles(directory="static/hunter", html=True), name="hunter")
app.mount("/payer",  StaticFiles(directory="static/payer",  html=True), name="payer")
