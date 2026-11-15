"""EarFit web app: chat with the Nemotron designer and preview the result in three.js.

Sessions (chat history, scan, generated meshes) live in this process's memory and under out/sessions/,
so run exactly one worker process. Everything a public deployment needs to survive strangers is here:
idle-session expiry, per-IP rate limits, a daily model budget and a streamed upload cap.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import shutil
import threading
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import openai
import trimesh
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from earfit.agent import COLORS, MODEL, SILICONES, Designer, make_client, usage_cost
from earfit.geometry import clean_scan, sample_plug
from earfit.sourcing import find_supplies

ROOT = Path(__file__).resolve().parents[2]
SESSIONS_DIR = ROOT / "out" / "sessions"
MESH_NAMES = {"impression", "plug", "mold_a", "mold_b"}
SCAN_TYPES = {"stl", "obj", "ply", "glb", "gltf", "off"}
SessionId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]

# Tunables (read after earfit.agent has loaded .env).
SESSION_TTL_MIN = float(os.environ.get("EARFIT_SESSION_TTL_MIN") or 60)
MAX_SESSIONS = int(os.environ.get("EARFIT_MAX_SESSIONS") or 200)
MAX_SCAN_MB = int(os.environ.get("EARFIT_MAX_SCAN_MB") or 25)
DAILY_BUDGET_USD = float(os.environ.get("EARFIT_DAILY_BUDGET_USD") or 2.0)
MAX_SCAN_FACES = 500_000  # repair and orientation time grows with triangle count
MAX_TURNS = 40  # chat turns per session; every turn resends the whole history to the model
SUPPLIES_TTL_S = 6 * 3600

log = logging.getLogger("uvicorn.error")


class RateLimit:
    """Sliding-window request limit per client IP, usable as a FastAPI dependency."""

    def __init__(self, limit: int, window_s: float):
        self.limit, self.window_s = limit, window_s
        self.hits: dict[str, deque[float]] = {}
        self.lock = threading.Lock()

    def __call__(self, request: Request) -> None:
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with self.lock:
            hits = self.hits.setdefault(client, deque())
            while hits and hits[0] <= now - self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                retry = int(hits[0] + self.window_s - now) + 1
                raise HTTPException(
                    429, f"too many requests; try again in {retry} s", headers={"Retry-After": str(retry)}
                )
            hits.append(now)

    def prune(self) -> None:
        cutoff = time.monotonic() - self.window_s
        with self.lock:
            self.hits = {client: hits for client, hits in self.hits.items() if hits and hits[-1] > cutoff}


LIMITS = {
    "session": [RateLimit(60, 3600)],
    "chat": [RateLimit(12, 60), RateLimit(200, 86400)],
    "adjust": [RateLimit(60, 60)],
    "upload": [RateLimit(10, 600)],
    "supplies": [RateLimit(10, 60)],
}


def limited(name: str) -> list:
    return [Depends(limit) for limit in LIMITS[name]]


class Budget:
    """Caps what the model may cost per UTC day, whoever is asking."""

    def __init__(self, usd_per_day: float):
        self.usd_per_day = usd_per_day
        self.day, self.spent = datetime.now(UTC).date(), 0.0
        self.lock = threading.Lock()

    def _roll(self) -> None:
        today = datetime.now(UTC).date()
        if today != self.day:
            self.day, self.spent = today, 0.0

    def check(self) -> None:
        with self.lock:
            self._roll()
            if self.spent >= self.usd_per_day:
                raise HTTPException(503, "today's free design budget is used up; please come back tomorrow")

    def add(self, usd: float) -> None:
        with self.lock:
            self._roll()
            self.spent += usd


@dataclass
class Session:
    designer: Designer
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_used: float = field(default_factory=time.monotonic)
    turns: int = 0


IMPRESSION = sample_plug()
CLIENT = make_client()
budget = Budget(DAILY_BUDGET_USD)
sessions: dict[str, Session] = {}
sessions_lock = threading.Lock()  # guards adding/removing sessions, not their use
scan_slots = asyncio.Semaphore(2)  # scan repair is CPU- and memory-heavy
supplies_cache: dict[str, tuple[float, list[dict]]] = {}


def _session(session_id: str) -> Session:
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "unknown or expired session")
    session.last_used = time.monotonic()
    return session


@contextmanager
def _exclusive(session_id: str) -> Iterator[Session]:
    """One request at a time per session: the designer's history and mesh files are not concurrency-safe."""
    session = _session(session_id)
    if not session.lock.acquire(blocking=False):
        raise HTTPException(409, "still working on your previous request; wait for it to finish")
    try:
        if sessions.get(session_id) is not session:  # expired between lookup and lock
            raise HTTPException(404, "unknown or expired session")
        yield session
    finally:
        session.last_used = time.monotonic()
        session.lock.release()


def _designer(session_id: str, impression: trimesh.Trimesh) -> Designer:
    """A fresh conversation about this impression; the session's earlier meshes are removed."""
    out_dir = SESSIONS_DIR / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in MESH_NAMES:
        (out_dir / f"{name}.stl").unlink(missing_ok=True)
    impression.export(out_dir / "impression.stl")
    return Designer(impression, out_dir, CLIENT)


def _drop(session_id: str) -> bool:
    """Forget a session and delete its files, unless a request is using it right now."""
    session = sessions.get(session_id)
    if session is None or not session.lock.acquire(blocking=False):
        return False
    try:
        sessions.pop(session_id, None)
        shutil.rmtree(SESSIONS_DIR / session_id, ignore_errors=True)
    finally:
        session.lock.release()
    return True


def _sweep() -> None:
    cutoff = time.monotonic() - SESSION_TTL_MIN * 60
    with sessions_lock:
        for session_id in [sid for sid, session in sessions.items() if session.last_used < cutoff]:
            _drop(session_id)
    for limits in LIMITS.values():
        for limit in limits:
            limit.prune()


async def _sweep_forever() -> None:
    while True:
        await asyncio.sleep(60)
        await run_in_threadpool(_sweep)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Sessions do not survive a restart, so whatever is on disk belongs to nobody.
    shutil.rmtree(SESSIONS_DIR, ignore_errors=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    sweeper = asyncio.create_task(_sweep_forever())
    yield
    sweeper.cancel()


app = FastAPI(title="EarFit", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

SECURITY_HEADERS = {
    # The page keeps its script and styles inline; everything else, three.js included, comes from this server.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


@app.middleware("http")
async def response_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers[name] = value
    if response.headers.get("content-type", "").startswith("text/html"):
        # Without this browsers keep the page for days after a deploy; revalidating costs one 304.
        response.headers["Cache-Control"] = "no-cache"
    elif request.url.path.startswith("/vendor/") and response.status_code == 200:
        # 2 MB of three.js under a versioned path: never worth downloading twice.
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


class ChatIn(BaseModel):
    session_id: SessionId
    message: str = Field(min_length=1, max_length=1000)


class Changes(BaseModel):
    """What the page's controls can change; use_case stays whatever the chat decided."""

    model_config = ConfigDict(extra="forbid")
    length_mm: float | None = None
    profile_trim_mm: float | None = None
    vent_diameter_mm: float | None = None
    grip_tab: bool | None = None
    silicone: Literal[*SILICONES] | None = None
    color: Literal[*COLORS] | None = None


class AdjustIn(BaseModel):
    session_id: SessionId
    changes: Changes


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/api/session", dependencies=limited("session"))
def new_session() -> dict:
    session_id = uuid.uuid4().hex
    with sessions_lock:
        if len(sessions) >= MAX_SESSIONS:
            # Make room by dropping whoever has been idle longest.
            idle_first = sorted(sessions, key=lambda sid: sessions[sid].last_used)
            if not any(_drop(sid) for sid in idle_first):
                raise HTTPException(503, "the server is busy; try again in a minute")
        sessions[session_id] = Session(_designer(session_id, IMPRESSION))
    backend = "Nebius Token Factory" if os.environ.get("NEBIUS_API_KEY") else "local llama.cpp"
    return {
        "session_id": session_id,
        "model": MODEL,
        "backend": backend,
        "colors": COLORS,
        "silicones": SILICONES,
        "max_scan_mb": MAX_SCAN_MB,
        "session_ttl_min": round(SESSION_TTL_MIN),
    }


def _read_scan(data: bytes, ext: str, longest_mm: float | None) -> trimesh.Trimesh:
    mesh = trimesh.load(io.BytesIO(data), file_type=ext)
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.to_geometry()
    if len(mesh.faces) > MAX_SCAN_FACES:
        raise ValueError(f"it has {len(mesh.faces):,} triangles; simplify it to under {MAX_SCAN_FACES:,} first")
    return clean_scan(mesh, longest_mm)


@app.post("/api/upload", dependencies=limited("upload"))
async def upload_scan(request: Request, session_id: str, filename: str, longest_mm: float | None = None) -> dict:
    """Replace the session's impression with a phone scan (raw file bytes in the body)."""
    _session(session_id)
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in SCAN_TYPES:
        raise HTTPException(400, f"unsupported file type .{ext}; use one of {sorted(SCAN_TYPES)}")
    if longest_mm is not None and not 5 <= longest_mm <= 60:
        raise HTTPException(400, "longest side should be between 5 and 60 mm")
    # Count bytes as they arrive: a declared Content-Length can lie and the body must never be buffered unbounded.
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_SCAN_MB * 1024 * 1024:
            raise HTTPException(413, f"scan is larger than {MAX_SCAN_MB} MB")
    with _exclusive(session_id) as session:
        async with scan_slots:
            try:
                impression = await run_in_threadpool(_read_scan, bytes(data), ext, longest_mm)
            except Exception as err:  # parser and repair errors are user-facing scan problems
                raise HTTPException(422, f"could not use this scan: {err}") from err
        session.designer = await run_in_threadpool(_designer, session_id, impression)
        session.turns = 0
    return {"size_mm": [round(float(x), 1) for x in impression.extents], "volume_mm3": round(float(impression.volume))}


@app.post("/api/chat", dependencies=limited("chat"))
def chat(body: ChatIn) -> dict:
    with _exclusive(body.session_id) as session:
        if session.turns >= MAX_TURNS:
            raise HTTPException(429, "this conversation is full; reload the page to start a new design")
        budget.check()
        designer = session.designer
        before, cost_before = designer.design, usage_cost(designer.usage)
        try:
            reply = designer.chat(body.message)
        except (openai.APIError, RuntimeError) as err:
            log.warning("model turn failed: %s: %s", type(err).__name__, err)
            raise HTTPException(502, "the design model is not responding right now; please try again") from err
        finally:
            budget.add(usage_cost(designer.usage) - cost_before)
        session.turns += 1
        return {"reply": reply, "design": designer.design, "updated": designer.design is not before}


@app.post("/api/adjust", dependencies=limited("adjust"))
def adjust(body: AdjustIn) -> dict:
    with _exclusive(body.session_id) as session:
        try:
            return {"design": session.designer.adjust(body.changes.model_dump(exclude_none=True))}
        except ValueError as err:
            raise HTTPException(400, str(err)) from err


@app.get("/api/supplies", dependencies=limited("supplies"))
def supplies(session_id: str) -> dict:
    """Live Tavily web search for the current design's silicone and a print service."""
    design = _session(session_id).designer.design
    if design is None:
        raise HTTPException(400, "design an earplug first")
    # The answer depends only on the silicone, so visitors share one search per silicone every few hours.
    cached = supplies_cache.get(design["silicone"])
    if cached is None or time.monotonic() - cached[0] > SUPPLIES_TTL_S:
        try:
            cached = supplies_cache[design["silicone"]] = (time.monotonic(), find_supplies(design["silicone"]))
        except Exception as err:  # missing key / network errors are shown to the user, not a crash
            raise HTTPException(502, f"web search failed: {err}") from err
    return {"results": cached[1]}


@app.get("/files/{session_id}/{name}.stl")
def mesh_file(session_id: str, name: str) -> FileResponse:
    if name not in MESH_NAMES:
        raise HTTPException(404)
    _session(session_id)
    path = SESSIONS_DIR / session_id / f"{name}.stl"
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="model/stl", filename=f"earfit_{name}.stl")


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")


def main() -> None:
    # One process on purpose: sessions are in memory. Behind a reverse proxy, set FORWARDED_ALLOW_IPS so
    # uvicorn takes the client address (used for rate limits) from X-Forwarded-For.
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))
