"""Thread-safe python-socketio client wrapper. Dispatches events to callbacks."""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional

try:
    import socketio
    _HAS_SIO = True
except ImportError:
    socketio = None
    _HAS_SIO = False

from shared.protocol import (
    EV_ADD_AI,
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
    EV_START_GAME,
    EV_YOUR_TURN,
)


class NetworkManager:
    """Wraps socketio.Client; exposes callback registration + convenience emitters."""

    def __init__(self):
        self.connected: bool = False
        self.server_url: str = ""
        self._lock = threading.Lock()
        self._callbacks: Dict[str, Callable[..., None]] = {}
        self.last_error: Optional[str] = None

        if _HAS_SIO:
            self.sio = socketio.Client(reconnection=True, reconnection_attempts=3)
            self._setup_handlers()
        else:
            self.sio = None

    # --- lifecycle ------------------------------------------------------------

    def available(self) -> bool:
        return self.sio is not None

    def connect(self, server_url: str, timeout: float = 5.0) -> bool:
        if not self.sio:
            self.last_error = "python-socketio not installed."
            return False
        try:
            self.sio.connect(server_url, wait_timeout=timeout,
                             transports=["websocket", "polling"])
            self.server_url = server_url
            self.connected = True
            self.last_error = None
            return True
        except Exception as e:
            self.connected = False
            self.last_error = str(e)
            return False

    def disconnect(self) -> None:
        if self.sio and self.connected:
            try:
                self.sio.disconnect()
            except Exception:
                pass
        self.connected = False

    # --- callbacks ------------------------------------------------------------

    def set_callback(self, event: str, cb: Callable[..., None]) -> None:
        with self._lock:
            self._callbacks[event] = cb

    def _trigger(self, event: str, *args) -> None:
        cb = self._callbacks.get(event)
        if cb:
            try:
                cb(*args)
            except Exception as e:
                print(f"[network callback error] {event}: {e}")

    def _setup_handlers(self) -> None:
        sio = self.sio

        @sio.event
        def connect():
            self.connected = True
            self._trigger("on_connect")

        @sio.event
        def disconnect():
            self.connected = False
            self._trigger("on_disconnect")

        @sio.event
        def connect_error(data):
            self.connected = False
            self.last_error = str(data)
            self._trigger("on_connect_error", data)

        @sio.on(EV_ROOMS_LIST)
        def _(data):
            self._trigger("on_rooms_list", data.get("rooms", []))

        @sio.on(EV_ROOM_CREATED)
        def _(data):
            self._trigger("on_room_created", data.get("room"))

        @sio.on(EV_ROOM_JOINED)
        def _(data):
            self._trigger("on_room_joined", data.get("room"))

        @sio.on(EV_ROOM_UPDATED)
        def _(data):
            self._trigger("on_room_updated", data.get("room"))

        @sio.on(EV_PLAYER_JOINED)
        def _(data):
            self._trigger("on_player_joined", data.get("player"))

        @sio.on(EV_PLAYER_LEFT)
        def _(data):
            self._trigger("on_player_left", data.get("player_id"))

        @sio.on(EV_PLAYER_KICKED)
        def _(data):
            self._trigger("on_player_kicked", data.get("reason", ""))

        @sio.on(EV_GAME_STARTED)
        def _(data):
            self._trigger("on_game_started", data.get("game_state"),
                          data.get("room"))

        @sio.on(EV_GAME_UPDATE)
        def _(data):
            self._trigger("on_game_update", data.get("game_state"))

        @sio.on(EV_YOUR_TURN)
        def _(data):
            self._trigger("on_your_turn", data.get("timeout_seconds", 60))

        @sio.on(EV_GAME_OVER)
        def _(data):
            self._trigger("on_game_over", data)

        @sio.on(EV_ERROR)
        def _(data):
            self._trigger("on_error", data.get("code"), data.get("message"))

        @sio.on(EV_CHAT_RECEIVED)
        def _(data):
            self._trigger("on_chat", data.get("player_name"),
                          data.get("message"))

    # --- emitters -------------------------------------------------------------

    def _emit(self, event: str, data: Any = None) -> None:
        if not self.sio or not self.connected:
            return
        try:
            self.sio.emit(event, data or {})
        except Exception as e:
            self.last_error = str(e)

    def request_rooms_list(self) -> None:
        self._emit(EV_LIST_ROOMS)

    def create_room(self, name: str, is_public: bool, max_players: int,
                    player_name: str) -> None:
        self._emit(EV_CREATE_ROOM, {
            "name": name,
            "is_public": is_public,
            "max_players": max_players,
            "player_name": player_name,
        })

    def join_room(self, room_code: str, player_name: str) -> None:
        self._emit(EV_JOIN_ROOM,
                   {"room_code": room_code.upper(), "player_name": player_name})

    def leave_room(self) -> None:
        self._emit(EV_LEAVE_ROOM)

    def kick_player(self, player_id: str) -> None:
        self._emit(EV_KICK_PLAYER, {"player_id": player_id})

    def add_ai(self, slot: int, ai_type: str, params: dict) -> None:
        self._emit(EV_ADD_AI,
                   {"slot": slot, "ai_type": ai_type, "params": params})

    def remove_ai(self, slot: int) -> None:
        self._emit(EV_REMOVE_AI, {"slot": slot})

    def set_ready(self, ready: bool) -> None:
        self._emit(EV_SET_READY, {"ready": ready})

    def start_game(self) -> None:
        self._emit(EV_START_GAME)

    def make_move(self, col: int) -> None:
        self._emit(EV_MAKE_MOVE, {"col": int(col)})

    def request_rematch(self) -> None:
        self._emit(EV_REQUEST_REMATCH)

    def send_chat(self, message: str) -> None:
        self._emit(EV_CHAT_MESSAGE, {"message": message})
