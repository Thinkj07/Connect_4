"""Socket.IO event handlers bound to an AsyncServer instance."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Dict

from shared.protocol import (
    ERR_CONNECTION_LOST,
    ERR_INVALID_MOVE,
    ERR_NOT_YOUR_TURN,
    ERR_ROOM_NOT_FOUND,
    EV_CHAT_MESSAGE,
    EV_CHAT_RECEIVED,
    EV_CREATE_ROOM,
    EV_ERROR,
    EV_GAME_OVER,
    EV_GAME_STARTED,
    EV_GAME_UPDATE,
    EV_JOIN_ROOM,
    EV_KICK_PLAYER,
    EV_LEAVE_ROOM,
    EV_LIST_ROOMS,
    EV_MAKE_MOVE,
    EV_PLAYER_JOINED,
    EV_PLAYER_KICKED,
    EV_PLAYER_LEFT,
    EV_REMOVE_AI,
    EV_REQUEST_REMATCH,
    EV_ROOM_CREATED,
    EV_ROOM_JOINED,
    EV_ROOM_UPDATED,
    EV_ROOMS_LIST,
    EV_SET_READY,
    EV_ADD_AI,
    EV_START_GAME,
    EV_YOUR_TURN,
    RoomStatus,
)

from . import config
from .game_session import GameSession
from .models import Room
from .room_manager import RoomError, RoomManager


def _room_payload(room: Room) -> dict:
    return asdict(room.to_dto())


def register_handlers(sio, room_manager: RoomManager,
                      game_sessions: Dict[str, GameSession]) -> None:
    """Attach all Client->Server event handlers onto *sio*."""

    async def emit_error(sid: str, code: str, message: str) -> None:
        await sio.emit(EV_ERROR, {"code": code, "message": message}, to=sid)

    async def broadcast_room(room: Room) -> None:
        await sio.emit(EV_ROOM_UPDATED, {"room": _room_payload(room)},
                       room=room.code)

    async def broadcast_rooms_list() -> None:
        rooms = [asdict(r) for r in room_manager.get_public_rooms()]
        await sio.emit(EV_ROOMS_LIST, {"rooms": rooms})

    async def run_ai_turns(room_code: str) -> None:
        """Play AI moves sequentially until human turn or game over."""
        session = game_sessions.get(room_code)
        if not session:
            return
        while (session.room.status == RoomStatus.PLAYING
               and session.is_ai_turn()):
            await asyncio.sleep(config.AI_MOVE_DELAY)
            session = game_sessions.get(room_code)
            if not session or session.room.status != RoomStatus.PLAYING:
                return
            col, state = session.process_ai_turn()
            if col is None:
                return
            await sio.emit(EV_GAME_UPDATE,
                           {"game_state": asdict(state)},
                           room=room_code)
            if session.room.status == RoomStatus.FINISHED:
                await sio.emit(EV_GAME_OVER, {
                    "winner": session.winner,
                    "reason": session.win_reason,
                    "scores": session.scores,
                    "win_cells": [list(c) for c in session.win_cells],
                }, room=room_code)
                return
            # Notify next human if needed
            if not session.is_ai_turn():
                pid = session.slot_player_id.get(session.current_player)
                if pid:
                    await sio.emit(EV_YOUR_TURN,
                                   {"timeout_seconds": config.TURN_TIMEOUT},
                                   to=pid)

    # -- connection lifecycle -------------------------------------------------

    @sio.event
    async def connect(sid, environ, auth=None):
        print(f"[connect] sid={sid}")

    @sio.event
    async def disconnect(sid):
        print(f"[disconnect] sid={sid}")
        room = room_manager.get_room_for_player(sid)
        code = room_manager.leave_room(sid)
        if code:
            await sio.emit(EV_PLAYER_LEFT,
                           {"player_id": sid},
                           room=code, skip_sid=sid)
            remaining = room_manager.get_room(code)
            if remaining:
                await broadcast_room(remaining)
            else:
                game_sessions.pop(code, None)
        if room and room.is_public:
            await broadcast_rooms_list()

    # -- room ops --------------------------------------------------------------

    @sio.on(EV_LIST_ROOMS)
    async def on_list_rooms(sid, data=None):
        rooms = [asdict(r) for r in room_manager.get_public_rooms()]
        await sio.emit(EV_ROOMS_LIST, {"rooms": rooms}, to=sid)

    @sio.on(EV_CREATE_ROOM)
    async def on_create_room(sid, data):
        data = data or {}
        try:
            room = room_manager.create_room(
                host_id=sid,
                host_name=data.get("player_name", "Host"),
                name=data.get("name", ""),
                is_public=bool(data.get("is_public", True)),
                max_players=int(data.get("max_players", 3)),
            )
        except RoomError as e:
            await emit_error(sid, e.code, e.message)
            return
        await sio.enter_room(sid, room.code)
        await sio.emit(EV_ROOM_CREATED,
                       {"room": _room_payload(room)}, to=sid)
        if room.is_public:
            await broadcast_rooms_list()

    @sio.on(EV_JOIN_ROOM)
    async def on_join_room(sid, data):
        data = data or {}
        try:
            room = room_manager.join_room(
                room_code=data.get("room_code", ""),
                player_id=sid,
                player_name=data.get("player_name", "Player"),
            )
        except RoomError as e:
            await emit_error(sid, e.code, e.message)
            return
        await sio.enter_room(sid, room.code)
        await sio.emit(EV_ROOM_JOINED,
                       {"room": _room_payload(room)}, to=sid)
        new_player = room.players[-1]
        await sio.emit(EV_PLAYER_JOINED,
                       {"player": asdict(new_player.to_dto())},
                       room=room.code, skip_sid=sid)
        await broadcast_room(room)
        if room.is_public:
            await broadcast_rooms_list()

    @sio.on(EV_LEAVE_ROOM)
    async def on_leave_room(sid, data=None):
        room = room_manager.get_room_for_player(sid)
        if not room:
            return
        is_public = room.is_public
        code = room.code
        room_manager.leave_room(sid)
        await sio.leave_room(sid, code)
        await sio.emit(EV_PLAYER_LEFT, {"player_id": sid},
                       room=code, skip_sid=sid)
        remaining = room_manager.get_room(code)
        if remaining:
            await broadcast_room(remaining)
        else:
            game_sessions.pop(code, None)
        if is_public:
            await broadcast_rooms_list()

    @sio.on(EV_KICK_PLAYER)
    async def on_kick_player(sid, data):
        data = data or {}
        target_id = data.get("player_id")
        room = room_manager.get_room_for_player(sid)
        if not room or not target_id:
            await emit_error(sid, ERR_ROOM_NOT_FOUND, "Room not found.")
            return
        try:
            room_manager.kick_player(room.code, sid, target_id)
        except RoomError as e:
            await emit_error(sid, e.code, e.message)
            return
        await sio.emit(EV_PLAYER_KICKED, {"reason": "Kicked by host."},
                       to=target_id)
        await sio.leave_room(target_id, room.code)
        await broadcast_room(room)
        if room.is_public:
            await broadcast_rooms_list()

    @sio.on(EV_ADD_AI)
    async def on_add_ai(sid, data):
        data = data or {}
        room = room_manager.get_room_for_player(sid)
        if not room:
            await emit_error(sid, ERR_ROOM_NOT_FOUND, "Room not found.")
            return
        try:
            room_manager.add_ai(
                room_code=room.code,
                host_id=sid,
                slot=int(data.get("slot", 0)),
                ai_type=str(data.get("ai_type", "Random")),
                params=data.get("params", {}),
            )
        except RoomError as e:
            await emit_error(sid, e.code, e.message)
            return
        await broadcast_room(room)

    @sio.on(EV_REMOVE_AI)
    async def on_remove_ai(sid, data):
        data = data or {}
        room = room_manager.get_room_for_player(sid)
        if not room:
            await emit_error(sid, ERR_ROOM_NOT_FOUND, "Room not found.")
            return
        try:
            room_manager.remove_ai(room.code, sid, int(data.get("slot", 0)))
        except RoomError as e:
            await emit_error(sid, e.code, e.message)
            return
        await broadcast_room(room)

    @sio.on(EV_SET_READY)
    async def on_set_ready(sid, data):
        data = data or {}
        room = room_manager.get_room_for_player(sid)
        if not room:
            return
        player = room.find_player(sid)
        if player:
            player.is_ready = bool(data.get("ready", False))
            await broadcast_room(room)

    @sio.on(EV_START_GAME)
    async def on_start_game(sid, data=None):
        room = room_manager.get_room_for_player(sid)
        if not room:
            await emit_error(sid, ERR_ROOM_NOT_FOUND, "Room not found.")
            return
        if room.host_id != sid:
            await emit_error(sid, "NOT_HOST", "Only host can start.")
            return
        if room.total_occupants() < 2:
            await emit_error(sid, "NOT_ENOUGH", "Need at least 2 players.")
            return
        if not room.is_full():
            await emit_error(sid, "NOT_ENOUGH",
                             f"Room needs {room.max_players} occupants to start.")
            return
        session = GameSession(room)
        game_sessions[room.code] = session
        state = session.initialize_game()
        await sio.emit(EV_GAME_STARTED,
                       {"room": _room_payload(room),
                        "game_state": asdict(state)},
                       room=room.code)
        if room.is_public:
            await broadcast_rooms_list()
        # Announce first turn or kick off AI
        if session.is_ai_turn():
            asyncio.create_task(run_ai_turns(room.code))
        else:
            pid = session.slot_player_id.get(session.current_player)
            if pid:
                await sio.emit(EV_YOUR_TURN,
                               {"timeout_seconds": config.TURN_TIMEOUT},
                               to=pid)

    @sio.on(EV_MAKE_MOVE)
    async def on_make_move(sid, data):
        data = data or {}
        room = room_manager.get_room_for_player(sid)
        if not room:
            await emit_error(sid, ERR_ROOM_NOT_FOUND, "Room not found.")
            return
        session = game_sessions.get(room.code)
        if not session:
            await emit_error(sid, "NO_SESSION", "Game not started.")
            return
        slot = session.get_player_slot(sid)
        if slot is None:
            await emit_error(sid, ERR_NOT_YOUR_TURN, "You are not in this game.")
            return
        if slot != session.current_player:
            await emit_error(sid, ERR_NOT_YOUR_TURN, "Not your turn.")
            return
        ok, state, msg = session.make_move(slot, int(data.get("col", -1)))
        if not ok:
            await emit_error(sid, ERR_INVALID_MOVE, msg or "Invalid move.")
            return
        await sio.emit(EV_GAME_UPDATE, {"game_state": asdict(state)},
                       room=room.code)
        if session.room.status == RoomStatus.FINISHED:
            await sio.emit(EV_GAME_OVER, {
                "winner": session.winner,
                "reason": session.win_reason,
                "scores": session.scores,
                "win_cells": [list(c) for c in session.win_cells],
            }, room=room.code)
            return
        if session.is_ai_turn():
            asyncio.create_task(run_ai_turns(room.code))
        else:
            pid = session.slot_player_id.get(session.current_player)
            if pid:
                await sio.emit(EV_YOUR_TURN,
                               {"timeout_seconds": config.TURN_TIMEOUT},
                               to=pid)

    @sio.on(EV_REQUEST_REMATCH)
    async def on_request_rematch(sid, data=None):
        room = room_manager.get_room_for_player(sid)
        if not room or room.host_id != sid:
            return
        room.status = RoomStatus.WAITING
        room.game_state = None
        game_sessions.pop(room.code, None)
        for p in room.players:
            p.is_ready = False
        await broadcast_room(room)
        if room.is_public:
            await broadcast_rooms_list()

    @sio.on(EV_CHAT_MESSAGE)
    async def on_chat_message(sid, data):
        data = data or {}
        room = room_manager.get_room_for_player(sid)
        if not room:
            return
        player = room.find_player(sid)
        if not player:
            return
        msg = str(data.get("message", ""))[:200]
        await sio.emit(EV_CHAT_RECEIVED,
                       {"player_name": player.name, "message": msg},
                       room=room.code)
