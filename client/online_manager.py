"""Coordinates NetworkManager callbacks with the Pygame App's online state."""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional

from .network import NetworkManager


class OnlineManager:
    """Thread-safe store for room/game state populated by network callbacks."""

    def __init__(self, network: NetworkManager):
        self.network = network
        self._lock = threading.Lock()

        self.state: str = "disconnected"
        self.room: Optional[dict] = None
        self.game_state: Optional[dict] = None
        self.my_sid: str = ""
        self.my_slot: int = 0
        self.my_name: str = "Player"
        self.is_my_turn: bool = False
        self.rooms_list: List[dict] = []
        self.last_error: Optional[tuple] = None
        self.chat_log: List[tuple] = []

        self._pending_events: List[tuple] = []  # (kind, payload)
        self._setup_callbacks()

    # --- callback wiring ------------------------------------------------------

    def _setup_callbacks(self) -> None:
        n = self.network
        n.set_callback("on_connect", self._on_connect)
        n.set_callback("on_disconnect", self._on_disconnect)
        n.set_callback("on_connect_error", self._on_connect_error)
        n.set_callback("on_rooms_list", self._on_rooms_list)
        n.set_callback("on_room_created", self._on_room_created)
        n.set_callback("on_room_joined", self._on_room_joined)
        n.set_callback("on_room_updated", self._on_room_updated)
        n.set_callback("on_player_joined", self._on_player_joined)
        n.set_callback("on_player_left", self._on_player_left)
        n.set_callback("on_player_kicked", self._on_player_kicked)
        n.set_callback("on_game_started", self._on_game_started)
        n.set_callback("on_game_update", self._on_game_update)
        n.set_callback("on_your_turn", self._on_your_turn)
        n.set_callback("on_game_over", self._on_game_over)
        n.set_callback("on_error", self._on_error)
        n.set_callback("on_chat", self._on_chat)

    # --- connection -----------------------------------------------------------

    def connect_to_server(self, url: str) -> bool:
        if not self.network.available():
            self.last_error = ("NO_SOCKETIO",
                               "python-socketio client not installed.")
            return False
        if self.network.connected:
            return True
        ok = self.network.connect(url)
        if ok:
            self.state = "lobby"
            self._push("connected")
        else:
            self.state = "disconnected"
            self.last_error = ("CONNECT_FAILED", self.network.last_error or "")
        return ok

    def disconnect(self) -> None:
        try:
            self.network.disconnect()
        finally:
            with self._lock:
                self.state = "disconnected"
                self.room = None
                self.game_state = None
                self.is_my_turn = False
                self.rooms_list = []

    def is_connected(self) -> bool:
        return self.network.connected

    # --- outgoing requests ----------------------------------------------------

    def set_name(self, name: str) -> None:
        self.my_name = (name or "Player").strip()[:16]

    def request_rooms(self) -> None:
        if self.is_connected():
            self.network.request_rooms_list()

    def create_room(self, name: str, is_public: bool, max_players: int) -> None:
        if self.is_connected():
            self.network.create_room(name, is_public, max_players, self.my_name)

    def join_room_by_code(self, code: str) -> None:
        if self.is_connected():
            self.network.join_room(code, self.my_name)

    def join_room_from_summary(self, summary: dict) -> None:
        if summary and self.is_connected():
            self.network.join_room(summary.get("code", ""), self.my_name)

    def leave_room(self) -> None:
        if self.is_connected():
            self.network.leave_room()
        with self._lock:
            self.room = None
            self.game_state = None
            self.is_my_turn = False
            self.state = "lobby" if self.is_connected() else "disconnected"

    def kick(self, player_id: str) -> None:
        self.network.kick_player(player_id)

    def add_ai(self, slot: int, ai_type: str, params: dict) -> None:
        self.network.add_ai(slot, ai_type, params)

    def remove_ai(self, slot: int) -> None:
        self.network.remove_ai(slot)

    def start_game(self) -> None:
        self.network.start_game()

    def make_move(self, col: int) -> bool:
        if not self.is_my_turn:
            return False
        self.network.make_move(col)
        with self._lock:
            self.is_my_turn = False
        return True

    def request_rematch(self) -> None:
        self.network.request_rematch()

    def send_chat(self, message: str) -> None:
        if message.strip():
            self.network.send_chat(message.strip())

    # --- helpers --------------------------------------------------------------

    def _push(self, kind: str, payload: Any = None) -> None:
        with self._lock:
            self._pending_events.append((kind, payload))

    def drain_events(self) -> List[tuple]:
        """Pop and return all pending events from network callbacks."""
        with self._lock:
            out, self._pending_events = self._pending_events, []
        return out

    def _find_my_slot(self) -> int:
        if not self.room:
            return 0
        # Prefer server-provided host_id match via self.my_sid, but fall back to name
        for p in self.room.get("players", []):
            if p.get("id") and self.my_sid and p["id"] == self.my_sid:
                return int(p.get("slot", 0))
        # Fallback: first player with matching name
        for p in self.room.get("players", []):
            if p.get("name") == self.my_name:
                return int(p.get("slot", 0))
        return 0

    def am_host(self) -> bool:
        if not self.room:
            return False
        host_id = self.room.get("host_id")
        if host_id and self.my_sid and host_id == self.my_sid:
            return True
        # Fallback: check players list
        for p in self.room.get("players", []):
            if p.get("is_host") and (
                    (self.my_sid and p.get("id") == self.my_sid) or
                    p.get("name") == self.my_name):
                return True
        return False

    def get_my_player(self) -> Optional[dict]:
        if not self.room:
            return None
        for p in self.room.get("players", []):
            if ((self.my_sid and p.get("id") == self.my_sid)
                    or p.get("name") == self.my_name):
                return p
        return None

    # --- network callbacks (run on socketio thread) ---------------------------

    def _on_connect(self) -> None:
        # Save our sid for ownership checks
        sid = ""
        try:
            if self.network.sio is not None:
                sid = self.network.sio.get_sid() or ""
        except Exception:
            sid = ""
        with self._lock:
            self.my_sid = sid
            self.state = "lobby"
        self._push("connected")

    def _on_disconnect(self) -> None:
        with self._lock:
            self.state = "disconnected"
            self.room = None
            self.game_state = None
            self.is_my_turn = False
        self._push("disconnected")

    def _on_connect_error(self, data: Any) -> None:
        self.last_error = ("CONNECT_ERROR", str(data))
        self._push("connect_error", data)

    def _on_rooms_list(self, rooms: List[dict]) -> None:
        with self._lock:
            self.rooms_list = list(rooms or [])
        self._push("rooms_list")

    def _on_room_created(self, room: dict) -> None:
        with self._lock:
            self.room = room
            self.my_slot = self._find_my_slot()
            self.state = "in_room"
        self._push("room_created")

    def _on_room_joined(self, room: dict) -> None:
        with self._lock:
            self.room = room
            self.my_slot = self._find_my_slot()
            self.state = "in_room"
        self._push("room_joined")

    def _on_room_updated(self, room: dict) -> None:
        with self._lock:
            self.room = room
            self.my_slot = self._find_my_slot()
        self._push("room_updated")

    def _on_player_joined(self, player: dict) -> None:
        self._push("player_joined", player)

    def _on_player_left(self, player_id: str) -> None:
        self._push("player_left", player_id)

    def _on_player_kicked(self, reason: str) -> None:
        with self._lock:
            self.room = None
            self.game_state = None
            self.is_my_turn = False
            self.state = "lobby"
        self._push("kicked", reason)

    def _on_game_started(self, game_state: dict, room: dict = None) -> None:
        with self._lock:
            if room:
                self.room = room
                self.my_slot = self._find_my_slot()
            self.game_state = game_state
            self.state = "playing"
            self.is_my_turn = (game_state
                               and game_state.get("current_player") == self.my_slot)
        self._push("game_started")

    def _on_game_update(self, game_state: dict) -> None:
        with self._lock:
            self.game_state = game_state
            self.is_my_turn = (game_state
                               and game_state.get("current_player") == self.my_slot)
        self._push("game_update")

    def _on_your_turn(self, timeout_seconds: int) -> None:
        with self._lock:
            self.is_my_turn = True
        self._push("your_turn", timeout_seconds)

    def _on_game_over(self, payload: dict) -> None:
        with self._lock:
            self.state = "gameover"
            self.is_my_turn = False
        self._push("game_over", payload)

    def _on_error(self, code: str, message: str) -> None:
        self.last_error = (code, message)
        self._push("error", (code, message))

    def _on_chat(self, name: str, message: str) -> None:
        with self._lock:
            self.chat_log.append((name, message))
            self.chat_log = self.chat_log[-30:]
        self._push("chat")
