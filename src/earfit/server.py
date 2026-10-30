"""EarFit web app: chat with the Nemotron designer and preview the result in three.js."""

from __future__ import annotations

import io
import os
import uuid
from pathlib import Path

import trimesh
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from earfit.agent import COLORS, MODEL, SILICONES, Designer
from earfit.geometry import clean_scan, sample_plug
from earfit.sourcing import find_supplies

ROOT = Path(__file__).resolve().parents[2]
SESSIONS_DIR = ROOT / "out" / "sessions"
MESH_NAMES = {"impression", "plug", "mold_a", "mold_b"}
SCAN_TYPES = {"stl", "obj", "ply", "glb", "gltf", "off"}
MAX_SCAN_BYTES = 100 * 1024 * 1024

app = FastAPI(title="EarFit")
IMPRESSION = sample_plug()
sessions: dict[str, Designer] = {}


class ChatIn(BaseModel):
    session_id: str
    message: str


class AdjustIn(BaseModel):
    session_id: str
    changes: dict


def _session(session_id: str) -> Designer:
    designer = sessions.get(session_id)
    if designer is None:
        raise HTTPException(404, "unknown session; reload the page")
    return designer


def _start(session_id: str, impression: trimesh.Trimesh) -> Designer:
    out_dir = SESSIONS_DIR / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in MESH_NAMES:
        (out_dir / f"{name}.stl").unlink(missing_ok=True)
    impression.export(out_dir / "impression.stl")
    sessions[session_id] = Designer(impression, out_dir)
    return sessions[session_id]


@app.post("/api/session")
def new_session() -> dict:
    session_id = uuid.uuid4().hex
    _start(session_id, IMPRESSION)
    backend = "Nebius Token Factory" if os.environ.get("NEBIUS_API_KEY") else "local llama.cpp"
    return {"session_id": session_id, "model": MODEL, "backend": backend, "colors": COLORS, "silicones": SILICONES}


@app.post("/api/upload")
async def upload_scan(request: Request, session_id: str, filename: str, longest_mm: float | None = None) -> dict:
    """Replace the session's impression with a phone scan (raw file bytes in the body)."""
    _session(session_id)
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in SCAN_TYPES:
        raise HTTPException(400, f"unsupported file type .{ext}; use one of {sorted(SCAN_TYPES)}")
    data = await request.body()
    if len(data) > MAX_SCAN_BYTES:
        raise HTTPException(413, "scan is larger than 100 MB")
    if longest_mm is not None and not 5 <= longest_mm <= 60:
        raise HTTPException(400, "longest side should be between 5 and 60 mm")
    try:
        mesh = trimesh.load(io.BytesIO(data), file_type=ext)
        impression = await run_in_threadpool(clean_scan, mesh, longest_mm)
    except Exception as err:  # parser and repair errors are user-facing scan problems
        raise HTTPException(422, f"could not use this scan: {err}") from err
    _start(session_id, impression)
    return {"size_mm": [round(float(x), 1) for x in impression.extents], "volume_mm3": round(float(impression.volume))}


@app.post("/api/chat")
def chat(body: ChatIn) -> dict:
    designer = _session(body.session_id)
    before = designer.design
    reply = designer.chat(body.message)
    return {"reply": reply, "design": designer.design, "updated": designer.design is not before}


@app.post("/api/adjust")
def adjust(body: AdjustIn) -> dict:
    try:
        return {"design": _session(body.session_id).adjust(body.changes)}
    except ValueError as err:
        raise HTTPException(400, str(err)) from err


@app.get("/api/supplies")
def supplies(session_id: str) -> dict:
    """Live Tavily web search for the current design's silicone and a print service."""
    designer = _session(session_id)
    if designer.design is None:
        raise HTTPException(400, "design an earplug first")
    try:
        return {"results": find_supplies(designer.design["silicone"])}
    except Exception as err:  # missing key / network errors are shown to the user, not a crash
        raise HTTPException(502, f"web search failed: {err}") from err


@app.get("/files/{session_id}/{name}.stl")
def mesh_file(session_id: str, name: str) -> FileResponse:
    if session_id not in sessions or name not in MESH_NAMES:
        raise HTTPException(404)
    path = SESSIONS_DIR / session_id / f"{name}.stl"
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="model/stl", filename=f"earfit_{name}.stl")


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")


def main() -> None:
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))
