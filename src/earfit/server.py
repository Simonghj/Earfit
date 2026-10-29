"""EarFit web app: chat with the Nemotron designer and preview the result in three.js."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from earfit.agent import MODEL, Designer
from earfit.geometry import sample_plug

ROOT = Path(__file__).resolve().parents[2]
SESSIONS_DIR = ROOT / "out" / "sessions"
MESH_NAMES = {"impression", "plug", "mold_a", "mold_b"}

app = FastAPI(title="EarFit")
IMPRESSION = sample_plug()
sessions: dict[str, Designer] = {}


class ChatIn(BaseModel):
    session_id: str
    message: str


@app.post("/api/session")
def new_session() -> dict:
    session_id = uuid.uuid4().hex
    out_dir = SESSIONS_DIR / session_id
    out_dir.mkdir(parents=True)
    IMPRESSION.export(out_dir / "impression.stl")
    sessions[session_id] = Designer(IMPRESSION, out_dir)
    backend = "Nebius Token Factory" if os.environ.get("NEBIUS_API_KEY") else "local llama.cpp"
    return {"session_id": session_id, "model": MODEL, "backend": backend}


@app.post("/api/chat")
def chat(body: ChatIn) -> dict:
    designer = sessions.get(body.session_id)
    if designer is None:
        raise HTTPException(404, "unknown session; reload the page")
    before = designer.design
    reply = designer.chat(body.message)
    return {"reply": reply, "design": designer.design, "updated": designer.design is not before}


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
