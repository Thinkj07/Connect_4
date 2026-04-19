"""Server-side data classes for rooms, players, and game state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from shared.protocol import (
    AISlotDTO,
    GameStateDTO,
    PlayerDTO,
    RoomDTO,
    RoomStatus,
    RoomSummaryDTO,
)


@dataclass
class Player:
    """Connected human player in a room."""
    id: str
    name: str
    slot: int
    is_host: bool = False
    is_ready: bool = False
    connected: bool = True

    def to_dto(self) -> PlayerDTO:
        return PlayerDTO(
            id=self.id,
            name=self.name,
            slot=self.slot,
            is_host=self.is_host,
            is_ready=self.is_ready,
            connected=self.connected,
        )


@dataclass
class AISlot:
    """AI-controlled slot in a room (during lobby or play)."""
    slot: int
    ai_type: str
    params: Dict = field(default_factory=dict)

    def to_dto(self) -> AISlotDTO:
        return AISlotDTO(slot=self.slot, ai_type=self.ai_type, params=dict(self.params))


@dataclass
class Room:
    """Persistent room object managed by the server."""
    code: str
    name: str
    host_id: str
    is_public: bool
    max_players: int
    players: List[Player] = field(default_factory=list)
    ai_slots: List[AISlot] = field(default_factory=list)
    status: RoomStatus = RoomStatus.WAITING
    created_at: datetime = field(default_factory=datetime.utcnow)
    game_state: Optional[GameStateDTO] = None

    # --- queries --------------------------------------------------------------

    def total_occupants(self) -> int:
        return len(self.players) + len(self.ai_slots)

    def is_full(self) -> bool:
        return self.total_occupants() >= self.max_players

    def find_player(self, player_id: str) -> Optional[Player]:
        for p in self.players:
            if p.id == player_id:
                return p
        return None

    def next_free_slot(self) -> Optional[int]:
        used = {p.slot for p in self.players} | {a.slot for a in self.ai_slots}
        for s in range(1, self.max_players + 1):
            if s not in used:
                return s
        return None

    def slot_occupied(self, slot: int) -> bool:
        return (any(p.slot == slot for p in self.players) or
                any(a.slot == slot for a in self.ai_slots))

    def get_ai(self, slot: int) -> Optional[AISlot]:
        for a in self.ai_slots:
            if a.slot == slot:
                return a
        return None

    def remove_ai(self, slot: int) -> bool:
        for i, a in enumerate(self.ai_slots):
            if a.slot == slot:
                self.ai_slots.pop(i)
                return True
        return False

    # --- dto export -----------------------------------------------------------

    def to_dto(self) -> RoomDTO:
        return RoomDTO(
            code=self.code,
            name=self.name,
            host_id=self.host_id,
            is_public=self.is_public,
            max_players=self.max_players,
            players=[p.to_dto() for p in self.players],
            ai_slots=[a.to_dto() for a in self.ai_slots],
            status=self.status.value,
            created_at=self.created_at.isoformat(),
            game_state=self.game_state,
        )

    def to_summary(self) -> RoomSummaryDTO:
        return RoomSummaryDTO(
            code=self.code,
            name=self.name,
            player_count=len(self.players),
            max_players=self.max_players,
            status=self.status.value,
            has_ai=bool(self.ai_slots),
        )
