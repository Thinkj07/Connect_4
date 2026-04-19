"""FastAPI + python-socketio entry point. Run with `uvicorn server.main:socket_app`."""

from __future__ import annotations

import asyncio
import sys
import os

# Ensure project root is on sys.path so that `import board`, `import ai` etc. work
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import socketio

from server import config
from server.events import register_handlers
from server.game_session import GameSession
from server.room_manager import RoomManager


app = FastAPI(title="Connect Four Online Server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.CORS_ORIGINS] if config.CORS_ORIGINS != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=config.CORS_ORIGINS,
    ping_timeout=30,
    ping_interval=25,
)

socket_app = socketio.ASGIApp(sio, app)

room_manager = RoomManager()
game_sessions: dict[str, GameSession] = {}
register_handlers(sio, room_manager, game_sessions)


@app.get("/")
async def root() -> dict:
    return {
        "service": "connect-four-online",
        "rooms_active": len(room_manager.rooms),
        "games_active": len(game_sessions),
    }


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.on_event("startup")
async def _start_cleanup() -> None:
    async def loop():
        while True:
            await asyncio.sleep(config.ROOM_CLEANUP_INTERVAL)
            removed = room_manager.cleanup_empty_rooms()
            if removed:
                print(f"[cleanup] removed {removed} stale rooms")

    asyncio.create_task(loop())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server.main:socket_app",
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        reload=False,
    )
