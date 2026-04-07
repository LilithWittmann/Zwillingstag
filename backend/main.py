import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from models import Speech
from services.bundestag_api import BundestagAPI
from services.debate_simulator import DebateSimulator
from services.kv_store import CloudflareKVStore, DiskKVStore, KVStore
from services.llm_service import LLMService
from services.mdb_service import MdbService


# ------------------------------------------------------------------
# KV store initialisation
# ------------------------------------------------------------------

def _init_kv_store() -> KVStore:
    """
    Return the appropriate KV store:
    - When running inside a Cloudflare Worker the ``js`` module is available
      and the SPEECH_CACHE binding is exposed on ``js.env``.
    - Otherwise fall back to a local disk-based store (useful for local dev
      and standard uvicorn deployments).
    """
    try:
        # ``js`` is only importable in the Pyodide / Cloudflare Workers runtime.
        # ImportError is expected in all other environments and is handled below.
        import js  # noqa: PLC0415
        namespace = getattr(js.env, "SPEECH_CACHE", None)
        if namespace is not None:
            logger.info("Using Cloudflare Workers KV store (SPEECH_CACHE binding)")
            return CloudflareKVStore(namespace)
    except ImportError:
        pass

    cache_dir = Path(os.getenv("KV_CACHE_DIR", "data/kv_cache"))
    logger.info(f"Using disk-based KV store at {cache_dir}")
    return DiskKVStore(cache_dir)


kv_store = _init_kv_store()


# ------------------------------------------------------------------
# Lifespan
# ------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load CDU/CSU members from Bundestag XML API (cached via KV store)
    await simulator.load_members()
    yield


app = FastAPI(
    title="Zwillingstag – CDU Digital Twin",
    description="Real-time simulation of CDU/CSU Bundestag member reactions.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Services
bundestag_api = BundestagAPI(
    api_key=os.getenv("BUNDESTAG_API_KEY"),
    kv_store=kv_store,
)
llm_service = LLMService(
    api_key=os.getenv("OPENAI_API_KEY"),
    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    base_url=os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1"),
)
mdb_service = MdbService(kv_store=kv_store)
simulator = DebateSimulator(bundestag_api, llm_service, mdb_service, kv_store=kv_store)

# Active WebSocket connections
connections: List[WebSocket] = []


# ------------------------------------------------------------------
# REST endpoints
# ------------------------------------------------------------------


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/members")
async def get_members():
    return simulator.get_members()


@app.get("/api/sessions")
async def get_sessions():
    return await bundestag_api.get_recent_sessions()


@app.get("/api/speeches")
async def get_speeches():
    if not simulator.available_speeches:
        await simulator.load_speeches()
    return [s.model_dump() for s in simulator.available_speeches]


@app.get("/api/speeches/{speech_id}")
async def get_speech(speech_id: str):
    speech = await bundestag_api.get_speech(speech_id)
    if not speech:
        raise HTTPException(status_code=404, detail="Speech not found")
    return speech.model_dump()


@app.get("/api/reactions/{speech_id}")
async def get_reactions(speech_id: str):
    return await simulator.get_reactions(speech_id)


@app.get("/api/state")
async def get_state():
    return await simulator.get_state()


# ------------------------------------------------------------------
# WebSocket
# ------------------------------------------------------------------


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connections.append(websocket)
    try:
        # Send current state immediately on connect
        state = await simulator.get_state()
        await websocket.send_json(state)

        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            action = msg.get("action")
            if action == "select_speech":
                await simulator.select_speech(msg["speech_id"])
                await broadcast(await simulator.get_state())
            elif action == "refresh":
                await simulator.refresh()
                await broadcast(await simulator.get_state())

    except WebSocketDisconnect:
        connections.remove(websocket)


async def broadcast(data: dict):
    dead = []
    for conn in connections:
        try:
            await conn.send_json(data)
        except Exception:
            dead.append(conn)
    for conn in dead:
        if conn in connections:
            connections.remove(conn)
