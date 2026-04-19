"""Socket.IO event names, data-class payloads, and enums shared by client and server."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Tuple


# --- Room status ---------------------------------------------------------------

class RoomStatus(str, Enum):
    WAITING = "waiting"
    PLAYING = "playing"
    FINISHED = "finished"


# --- Client -> Server events ---------------------------------------------------

EV_LIST_ROOMS = "list_rooms"
EV_CREATE_ROOM = "create_room"
EV_JOIN_ROOM = "join_room"
EV_LEAVE_ROOM = "leave_room"
EV_KICK_PLAYER = "kick_player"
EV_ADD_AI = "add_ai"
EV_REMOVE_AI = "remove_ai"
EV_SET_READY = "set_ready"
EV_START_GAME = "start_game"
EV_MAKE_MOVE = "make_move"
EV_REQUEST_REMATCH = "request_rematch"
EV_CHAT_MESSAGE = "chat_message"


# --- Server -> Client events ---------------------------------------------------

EV_ROOMS_LIST = "rooms_list"
EV_ROOM_CREATED = "room_created"
EV_ROOM_JOINED = "room_joined"
EV_ROOM_UPDATED = "room_updated"
EV_PLAYER_JOINED = "player_joined"
EV_PLAYER_LEFT = "player_left"
EV_PLAYER_KICKED = "player_kicked"
EV_GAME_STARTED = "game_started"
EV_GAME_UPDATE = "game_update"
EV_YOUR_TURN = "your_turn"
EV_GAME_OVER = "game_over"
EV_ERROR = "error"
EV_CHAT_RECEIVED = "chat_received"


# --- Error codes ---------------------------------------------------------------

ERR_ROOM_NOT_FOUND = "ROOM_NOT_FOUND"
ERR_ROOM_FULL = "ROOM_FULL"
ERR_ROOM_IN_PROGRESS = "ROOM_IN_PROGRESS"
ERR_NOT_HOST = "NOT_HOST"
ERR_NOT_YOUR_TURN = "NOT_YOUR_TURN"
ERR_INVALID_MOVE = "INVALID_MOVE"
ERR_ALREADY_IN_ROOM = "ALREADY_IN_ROOM"
ERR_CONNECTION_LOST = "CONNECTION_LOST"
ERR_SLOT_OCCUPIED = "SLOT_OCCUPIED"
ERR_INVALID_AI = "INVALID_AI"


# --- Data structures -----------------------------------------------------------

@dataclass
class PlayerDTO:
    """Human player in a room."""
    id: str
    name: str
    slot: int
    is_host: bool = False
    is_ready: bool = False
    connected: bool = True


@dataclass
class AISlotDTO:
    """AI-controlled slot in a room."""
    slot: int
    ai_type: str
    params: Dict = field(default_factory=dict)


@dataclass
class GameStateDTO:
    """Snapshot of a game in progress for transmission over the wire."""
    board: List[List[int]]
    current_player: int
    scores: Dict[int, int]
    winner: Optional[int] = None
    win_reason: str = ""
    last_move: Optional[Tuple[int, int]] = None
    win_cells: List[Tuple[int, int]] = field(default_factory=list)
    status: str = RoomStatus.PLAYING.value


@dataclass
class RoomDTO:
    """Full room state sent to clients on create/join/update."""
    code: str
    name: str
    host_id: str
    is_public: bool
    max_players: int
    players: List[PlayerDTO] = field(default_factory=list)
    ai_slots: List[AISlotDTO] = field(default_factory=list)
    status: str = RoomStatus.WAITING.value
    created_at: str = ""
    game_state: Optional[GameStateDTO] = None


@dataclass
class RoomSummaryDTO:
    """Entry in the public-room browser."""
    code: str
    name: str
    player_count: int
    max_players: int
    status: str
    has_ai: bool


def to_dict(obj) -> dict:
    """asdict helper that tolerates None."""
    if obj is None:
        return {}
    return asdict(obj)
