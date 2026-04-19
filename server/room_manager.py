"""In-memory CRUD for rooms plus helpers for hosts, AI slots, and browsing."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from shared.protocol import RoomStatus, RoomSummaryDTO

from . import config
from .models import AISlot, Player, Room


class RoomError(Exception):
    """Raised for recoverable room operation failures (code kept as .code)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class RoomManager:
    """Tracks active rooms and which socket ID belongs to which room."""

    def __init__(self):
        self.rooms: Dict[str, Room] = {}
        self.player_room_map: Dict[str, str] = {}

    # --- code generation ------------------------------------------------------

    def _generate_code(self) -> str:
        while True:
            code = "".join(
                secrets.choice(config.ROOM_CODE_ALPHABET)
                for _ in range(config.ROOM_CODE_LENGTH)
            )
            if code not in self.rooms:
                return code

    # --- CRUD -----------------------------------------------------------------

    def create_room(self, host_id: str, host_name: str, name: str,
                    is_public: bool, max_players: int) -> Room:
        if host_id in self.player_room_map:
            raise RoomError("ALREADY_IN_ROOM", "You are already in a room.")
        if len(self.rooms) >= config.MAX_ROOMS:
            raise RoomError("SERVER_FULL", "Server room capacity reached.")
        if max_players not in (2, 3):
            raise RoomError("INVALID_MAX", "max_players must be 2 or 3.")

        code = self._generate_code()
        host = Player(id=host_id, name=host_name or "Host", slot=1, is_host=True)
        room = Room(
            code=code,
            name=name or f"{host.name}'s Room",
            host_id=host_id,
            is_public=bool(is_public),
            max_players=int(max_players),
            players=[host],
        )
        self.rooms[code] = room
        self.player_room_map[host_id] = code
        return room

    def join_room(self, room_code: str, player_id: str,
                  player_name: str) -> Room:
        if player_id in self.player_room_map:
            raise RoomError("ALREADY_IN_ROOM", "You are already in a room.")
        room = self.rooms.get((room_code or "").upper())
        if not room:
            raise RoomError("ROOM_NOT_FOUND", "Room code doesn't exist.")
        if room.status != RoomStatus.WAITING:
            raise RoomError("ROOM_IN_PROGRESS", "Game has already started.")
        if room.is_full():
            raise RoomError("ROOM_FULL", "Room is full.")

        slot = room.next_free_slot()
        if slot is None:
            raise RoomError("ROOM_FULL", "No free slot available.")

        player = Player(id=player_id, name=player_name or f"Player{slot}", slot=slot)
        room.players.append(player)
        self.player_room_map[player_id] = room.code
        return room

    def leave_room(self, player_id: str) -> Optional[str]:
        """Remove player from their room; return room code (or None)."""
        code = self.player_room_map.pop(player_id, None)
        if not code:
            return None
        room = self.rooms.get(code)
        if not room:
            return code

        for i, p in enumerate(room.players):
            if p.id == player_id:
                was_host = p.is_host
                room.players.pop(i)
                if was_host and room.players:
                    new_host = room.players[0]
                    new_host.is_host = True
                    room.host_id = new_host.id
                break

        # Clean up empty rooms immediately
        if not room.players:
            self.rooms.pop(code, None)

        return code

    # --- lookups --------------------------------------------------------------

    def get_room(self, room_code: str) -> Optional[Room]:
        if not room_code:
            return None
        return self.rooms.get(room_code.upper())

    def get_room_for_player(self, player_id: str) -> Optional[Room]:
        code = self.player_room_map.get(player_id)
        return self.rooms.get(code) if code else None

    def get_public_rooms(self) -> List[RoomSummaryDTO]:
        out = []
        for room in self.rooms.values():
            if room.is_public and room.status == RoomStatus.WAITING:
                out.append(room.to_summary())
        return out

    # --- host operations ------------------------------------------------------

    def _require_host(self, room: Room, host_id: str) -> None:
        if room.host_id != host_id:
            raise RoomError("NOT_HOST", "Only the host can perform this action.")

    def kick_player(self, room_code: str, host_id: str,
                    target_id: str) -> Room:
        room = self.get_room(room_code)
        if not room:
            raise RoomError("ROOM_NOT_FOUND", "Room not found.")
        self._require_host(room, host_id)
        if target_id == host_id:
            raise RoomError("INVALID_KICK", "Host cannot kick themselves.")
        target = room.find_player(target_id)
        if not target:
            raise RoomError("PLAYER_NOT_FOUND", "Player not in room.")
        room.players = [p for p in room.players if p.id != target_id]
        self.player_room_map.pop(target_id, None)
        return room

    def add_ai(self, room_code: str, host_id: str, slot: int,
               ai_type: str, params: dict) -> Room:
        room = self.get_room(room_code)
        if not room:
            raise RoomError("ROOM_NOT_FOUND", "Room not found.")
        self._require_host(room, host_id)
        if room.status != RoomStatus.WAITING:
            raise RoomError("ROOM_IN_PROGRESS", "Cannot add AI after start.")
        if slot < 1 or slot > room.max_players:
            raise RoomError("INVALID_SLOT", "Slot out of range.")
        if room.slot_occupied(slot):
            raise RoomError("SLOT_OCCUPIED", "Slot already occupied.")
        if ai_type not in ("Random", "MCTS", "Minimax"):
            raise RoomError("INVALID_AI", "Unknown AI type.")
        room.ai_slots.append(AISlot(slot=slot, ai_type=ai_type,
                                    params=dict(params or {})))
        return room

    def remove_ai(self, room_code: str, host_id: str, slot: int) -> Room:
        room = self.get_room(room_code)
        if not room:
            raise RoomError("ROOM_NOT_FOUND", "Room not found.")
        self._require_host(room, host_id)
        if room.status != RoomStatus.WAITING:
            raise RoomError("ROOM_IN_PROGRESS", "Cannot remove AI after start.")
        if not room.remove_ai(slot):
            raise RoomError("AI_NOT_FOUND", "No AI in that slot.")
        return room

    # --- maintenance ----------------------------------------------------------

    def cleanup_empty_rooms(self) -> int:
        cutoff = datetime.utcnow() - timedelta(seconds=config.EMPTY_ROOM_TIMEOUT)
        stale = [code for code, r in self.rooms.items()
                 if not r.players and r.created_at < cutoff]
        for code in stale:
            self.rooms.pop(code, None)
        return len(stale)
