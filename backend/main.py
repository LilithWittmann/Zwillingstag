import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
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
from services.llm_service import LLMService
from services.mdb_service import MdbService


# ------------------------------------------------------------------
# Background live-update loop
# ------------------------------------------------------------------

async def auto_update_loop():
    interval = int(os.getenv("POLL_INTERVAL_SECONDS", "120"))
    while True:
        await asyncio.sleep(interval)
        try:
            updated = await simulator.check_for_updates()
            if updated:
                await broadcast(await simulator.get_state())
        except Exception as e:
            logger.error(f"Auto-update loop error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load CDU/CSU members from Bundestag XML API (cached to disk)
    await simulator.load_members()
    asyncio.create_task(auto_update_loop())
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
bundestag_api = BundestagAPI(api_key=os.getenv("BUNDESTAG_API_KEY"))
llm_service = LLMService(
    api_key=os.getenv("OPENAI_API_KEY"),
    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
)
mdb_service = MdbService()
simulator = DebateSimulator(bundestag_api, llm_service, mdb_service)

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
