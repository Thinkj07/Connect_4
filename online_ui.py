"""Pygame UI layer for online multiplayer: menus, room browser, lobby, online game.

Implemented as a mixin that expects the host class (``App``) to provide the
common drawing helpers used by offline screens (``_draw_top_bar``,
``_draw_button``, ``_draw_panel``, ``_draw_board`` and the font set).
"""

from __future__ import annotations

import math
import time
from typing import List, Optional

import pygame

from constants import (
    ACCENT_SELECTED,
    ACCENT_SELECTED_LT,
    BOARD_COLOR,
    BOARD_X,
    BOARD_GRID_PX_W,
    BTN_BORDER,
    BTN_HOVER,
    BTN_NORMAL,
    BTN_TEXT,
    CELL_STRIDE,
    CREAM,
    CREAM_DARK,
    DEFAULT_SERVER_URL,
    MAX_PLAYER_NAME_LEN,
    MAX_ROOM_NAME_LEN,
    PANEL_BORDER,
    PLAYER_COLORS,
    PLAYER_NAMES,
    ROOM_CODE_LEN,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TEXT_COLOR,
    TEXT_DIM,
    TEXT_MUTED,
    WHITE,
)


# Subset of AI_TYPES available for online rooms (no "Human" in AI slots)
ONLINE_AI_TYPES = ["Random", "MCTS", "Minimax"]


def _fmt_status(s: str) -> str:
    return {"waiting": "Waiting", "playing": "Playing",
            "finished": "Finished"}.get(s, s.title())


class OnlineUIMixin:
    """Event + draw handlers for every ``online_*`` state.

    Mix into ``App``; do not instantiate directly.
    """

    # ------------------------------------------------------------------
    # one-time setup (called from App.__init__)
    # ------------------------------------------------------------------

    def _online_init(self) -> None:
        self._on_name_input: str = "Player"
        self._on_server_url: str = DEFAULT_SERVER_URL
        self._on_room_name: str = ""
        self._on_room_code: str = ""
        self._on_is_public: bool = True
        self._on_max_players: int = 3
        self._on_active_field: Optional[str] = None
        self._on_connecting_since: float = 0.0
        self._on_toast: str = ""
        self._on_toast_t: float = 0.0
        self._on_last_list_refresh: float = 0.0
        self._on_ai_type_cycle: dict = {}  # slot -> idx into ONLINE_AI_TYPES
        self._on_result_payload: Optional[dict] = None
        self._on_winner: int = 0
        self._on_win_cells: list = []
        self._on_win_reason: str = ""
        self._on_scores: dict = {}

        # Build online manager + network (deferred imports; optional deps)
        try:
            from client.network import NetworkManager
            from client.online_manager import OnlineManager
            self._net = NetworkManager()
            self._online = OnlineManager(self._net)
            self._online_available = self._net.available()
        except Exception as e:
            self._net = None
            self._online = None
            self._online_available = False
            self._on_toast = f"Online disabled: {e}"

    # ------------------------------------------------------------------
    # event routing helpers
    # ------------------------------------------------------------------

    def _online_event(self, ev, mp) -> bool:
        """Return True if *ev* was handled by an online state."""
        h = {
            "online_menu": self._ev_online_menu,
            "online_connecting": self._ev_online_connecting,
            "room_browser": self._ev_room_browser,
            "join_by_code": self._ev_join_by_code,
            "create_room": self._ev_create_room,
            "room_lobby": self._ev_room_lobby,
            "playing_online": self._ev_playing_online,
            "online_gameover": self._ev_online_gameover,
        }.get(self.state)
        if h is None:
            return False
        h(ev, mp)
        return True

    def _online_draw(self, mp) -> bool:
        h = {
            "online_menu": self._dr_online_menu,
            "online_connecting": self._dr_online_connecting,
            "room_browser": self._dr_room_browser,
            "join_by_code": self._dr_join_by_code,
            "create_room": self._dr_create_room,
            "room_lobby": self._dr_room_lobby,
            "playing_online": self._dr_playing_online,
            "online_gameover": self._dr_online_gameover,
        }.get(self.state)
        if h is None:
            return False
        h(mp)
        return True

    def _online_update(self) -> None:
        if not self._online:
            return
        for kind, payload in self._online.drain_events():
            self._on_online_event(kind, payload)
        if self._on_toast and time.time() - self._on_toast_t > 4:
            self._on_toast = ""

    # ------------------------------------------------------------------
    # server event handlers (main thread)
    # ------------------------------------------------------------------

    def _toast(self, msg: str) -> None:
        self._on_toast = msg
        self._on_toast_t = time.time()

    def _on_online_event(self, kind: str, payload) -> None:
        if kind == "connected":
            if self.state == "online_connecting":
                self.state = "online_menu"
        elif kind == "disconnected":
            self._toast("Disconnected from server.")
            if self.state not in ("menu", "modeselect", "howtoplay"):
                self.state = "online_menu"
        elif kind == "connect_error":
            msg = str(payload) if payload else "Unable to reach server."
            # Trim overly long python-socketio error strings
            if len(msg) > 80:
                msg = msg[:77] + "..."
            self._toast(f"Connection failed: {msg}")
            if self.state == "online_connecting":
                self.state = "online_menu"
        elif kind in ("room_created", "room_joined"):
            self._start_online_game_from_room()
            self.state = "room_lobby"
        elif kind == "room_updated":
            pass  # state already mirrored in self._online.room
        elif kind == "player_joined":
            name = (payload or {}).get("name", "Player")
            self._toast(f"{name} joined.")
        elif kind == "player_left":
            self._toast("A player left.")
        elif kind == "kicked":
            reason = payload or "You were removed."
            self._toast(f"Kicked: {reason}")
            self.state = "online_menu"
        elif kind == "game_started":
            self._enter_online_game()
        elif kind == "game_update":
            pass
        elif kind == "your_turn":
            self._toast("Your turn!")
        elif kind == "game_over":
            self._on_result_payload = payload
            self._on_winner = int((payload or {}).get("winner") or 0)
            self._on_win_reason = (payload or {}).get("reason", "")
            self._on_scores = (payload or {}).get("scores", {}) or {}
            wc = (payload or {}).get("win_cells", []) or []
            self._on_win_cells = [tuple(c) for c in wc]
            self.state = "online_gameover"
            self.flash_t = 0
            self._play(self.snd_win)
        elif kind == "error":
            code, message = payload if isinstance(payload, tuple) else ("ERR", str(payload))
            self._toast(f"{code}: {message}")

    def _start_online_game_from_room(self) -> None:
        """Prepare render state so the board renders cleanly when lobby loads."""
        # Lazy no-op; lobby doesn't need a Board until game_started.
        pass

    def _enter_online_game(self) -> None:
        """Snap local Board to match server's initial state, switch state."""
        from board import Board
        gs = self._online.game_state or {}
        self.board = Board.from_list(gs.get("board")) if gs.get("board") else Board()
        self.num_p = len(self._online.room.get("players", [])) + \
            len(self._online.room.get("ai_slots", []))
        if self.num_p not in (2, 3):
            self.num_p = self._online.room.get("max_players", 3)
        self.cur = gs.get("current_player", 1)
        self.scores = {int(k): int(v) for k, v in gs.get("scores", {}).items()} \
            or {p: 0 for p in range(1, self.num_p + 1)}
        self.winner = 0
        self.win_cells = []
        self.win_reason = ""
        self.anim = False
        self.hcol = -1
        self.ptypes = self._build_online_ptypes()
        self.ais = [None] * self.num_p
        self.state = "playing_online"

    def _build_online_ptypes(self) -> list:
        room = self._online.room or {}
        types = ["Human"] * self.num_p
        for ai in room.get("ai_slots", []) or []:
            slot = int(ai.get("slot", 0))
            if 1 <= slot <= self.num_p:
                types[slot - 1] = ai.get("ai_type", "Random")
        return types

    # ------------------------------------------------------------------
    # text input helper
    # ------------------------------------------------------------------

    def _on_text_event(self, ev, field: str, max_len: int,
                       upper: bool = False, alnum_only: bool = False) -> None:
        if ev.type != pygame.KEYDOWN:
            return
        attr = {"name": "_on_name_input",
                "server": "_on_server_url",
                "room_name": "_on_room_name",
                "code": "_on_room_code"}[field]
        cur = getattr(self, attr)
        if ev.key == pygame.K_BACKSPACE:
            setattr(self, attr, cur[:-1])
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_TAB):
            self._on_active_field = None
        elif ev.unicode and len(cur) < max_len:
            ch = ev.unicode
            if ch == "\r" or ch == "\n" or ch == "\t":
                return
            if upper:
                ch = ch.upper()
            if alnum_only and not ch.isalnum():
                return
            if ch.isprintable():
                setattr(self, attr, cur + ch)

    # ------------------------------------------------------------------
    # ONLINE MENU
    # ------------------------------------------------------------------

    def _online_menu_btns(self) -> list:
        cx = SCREEN_WIDTH // 2
        w = 280
        y0 = 310
        return [
            (pygame.Rect(cx - w // 2, y0, w, 52), "Create Room"),
            (pygame.Rect(cx - w // 2, y0 + 66, w, 52), "Join by Code"),
            (pygame.Rect(cx - w // 2, y0 + 132, w, 52), "Browse Rooms"),
            (pygame.Rect(cx - w // 2, y0 + 210, w, 46), "Back"),
        ]

    def _online_server_box(self) -> pygame.Rect:
        return pygame.Rect(SCREEN_WIDTH // 2 - 200, 230, 400, 38)

    def _online_name_box(self) -> pygame.Rect:
        return pygame.Rect(SCREEN_WIDTH // 2 - 200, 160, 400, 38)

    def _online_reconnect_btn(self) -> pygame.Rect:
        return pygame.Rect(SCREEN_WIDTH // 2 - 110, SCREEN_HEIGHT - 135, 220, 42)

    def _ev_online_menu(self, ev, mp) -> None:
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self._disconnect_online()
            self.state = "menu"
            return
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self._online_name_box().collidepoint(mp):
                self._on_active_field = "name"
                return
            if self._online_server_box().collidepoint(mp):
                self._on_active_field = "server"
                return
            self._on_active_field = None
            # Reconnect button (only when disconnected)
            if (not (self._online and self._online.is_connected())
                    and self._online_reconnect_btn().collidepoint(mp)):
                self._play(self.snd_click)
                self._start_online_connection()
                return
            for rect, label in self._online_menu_btns():
                if not rect.collidepoint(mp):
                    continue
                self._play(self.snd_click)
                if label == "Back":
                    self._disconnect_online()
                    self.state = "menu"
                    return
                if not self._online_available:
                    self._toast("Install python-socketio[client] to play online.")
                    return
                if not self._online.is_connected():
                    self._toast("Not connected. Press Reconnect.")
                    return
                self._online.set_name(self._on_name_input)
                self._navigate_online_action(label)
                return
        if self._on_active_field == "name":
            self._on_text_event(ev, "name", MAX_PLAYER_NAME_LEN)
        elif self._on_active_field == "server":
            self._on_text_event(ev, "server", 80)

    def _navigate_online_action(self, label: str) -> None:
        if label == "Create Room":
            self._on_room_name = f"{self._on_name_input}'s Room"
            self.state = "create_room"
        elif label == "Join by Code":
            self._on_room_code = ""
            self.state = "join_by_code"
        elif label == "Browse Rooms":
            self._online.request_rooms()
            self._on_last_list_refresh = time.time()
            self.state = "room_browser"

    def _start_online_connection(self) -> None:
        """Entry from main menu: kick off a connection attempt immediately."""
        if not self._online_available:
            self._toast("python-socketio client not installed.")
            self.state = "online_menu"
            return
        self._online.set_name(self._on_name_input)
        if self._online.is_connected():
            self.state = "online_menu"
            return
        self._on_connecting_since = time.time()
        self._pending_online_action = None
        self.state = "online_connecting"
        import threading
        threading.Thread(
            target=self._run_connect_attempt,
            args=(self._on_server_url,),
            daemon=True).start()

    def _run_connect_attempt(self, url: str) -> None:
        """Background thread worker that emits a 'connect_failed' event on error."""
        if not self._online:
            return
        ok = self._online.connect_to_server(url)
        if not ok:
            # Ensure the UI state moves even when connect_to_server didn't push.
            self._online._push(
                "connect_error",
                self._online.network.last_error or "Connection failed.")

    def _disconnect_online(self) -> None:
        if self._online and self._online.is_connected():
            self._online.disconnect()

    def _dr_online_menu(self, mp) -> None:
        self._draw_top_bar()
        self._shadow_text(self.f_lg, "ONLINE MULTIPLAYER",
                          SCREEN_WIDTH // 2, 70, TEXT_COLOR)
        self._draw_divider(110, 320)

        # Name + server inputs
        self._draw_text_input(self._online_name_box(),
                              self._on_name_input,
                              "Your Name",
                              active=self._on_active_field == "name",
                              placeholder="Player")
        self._draw_text_input(self._online_server_box(),
                              self._on_server_url,
                              "Server URL",
                              active=self._on_active_field == "server",
                              placeholder=DEFAULT_SERVER_URL)

        connected = bool(self._online and self._online.is_connected())
        for rect, label in self._online_menu_btns():
            # Action buttons require an active connection; Back is always enabled.
            enabled = True if label == "Back" else connected
            self._draw_button(rect, label, mp, enabled=enabled)

        # Reconnect button (only when disconnected)
        if not connected:
            self._draw_button(self._online_reconnect_btn(), "Reconnect", mp,
                              selected=True, mode_select_style=False)

        # Connection indicator with animated pulse dot
        status = "Connected" if connected else "Disconnected"
        col = (40, 150, 80) if connected else (180, 70, 70)
        pulse = 0.5 + 0.5 * math.sin(self._tick * 0.08)
        r = 6 + (2 if connected else int(2 * pulse))
        dot = pygame.Surface((20, 20), pygame.SRCALPHA)
        alpha = 255 if connected else int(180 + 70 * pulse)
        pygame.draw.circle(dot, (*col, alpha), (10, 10), r)
        t = self.f_sm.render(f"Server: {status}", True, TEXT_DIM)
        total_w = 20 + 8 + t.get_width()
        base_x = SCREEN_WIDTH // 2 - total_w // 2
        self.screen.blit(dot, (base_x, SCREEN_HEIGHT - 80))
        self.screen.blit(t, (base_x + 28, SCREEN_HEIGHT - 76))

        self._draw_toast()

    # ------------------------------------------------------------------
    # ONLINE CONNECTING
    # ------------------------------------------------------------------

    def _ev_online_connecting(self, ev, mp) -> None:
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self._disconnect_online()
            self.state = "online_menu"
        # Time-out handled in _online_update via drain_events / by user Esc

    def _dr_online_connecting(self, mp) -> None:
        self._draw_top_bar()
        self._shadow_text(self.f_lg, "CONNECTING...",
                          SCREEN_WIDTH // 2, 240, TEXT_COLOR)
        t = self.f_sm.render(self._on_server_url, True, TEXT_DIM)
        self.screen.blit(t, t.get_rect(center=(SCREEN_WIDTH // 2, 290)))
        # Spinner
        cx, cy = SCREEN_WIDTH // 2, 380
        for i in range(8):
            a = self._tick * 0.1 + i * math.pi / 4
            x = cx + math.cos(a) * 22
            y = cy + math.sin(a) * 22
            alpha = int(80 + 170 * ((i / 8)))
            s = pygame.Surface((10, 10), pygame.SRCALPHA)
            pygame.draw.circle(s, (*BTN_NORMAL, alpha), (5, 5), 5)
            self.screen.blit(s, (int(x - 5), int(y - 5)))
        t2 = self.f_sm.render("Press ESC to cancel", True, TEXT_MUTED)
        self.screen.blit(t2, t2.get_rect(center=(SCREEN_WIDTH // 2, 450)))

        # Auto-resume pending action once connected
        if (self._online and self._online.is_connected()
                and getattr(self, "_pending_online_action", None)):
            act = self._pending_online_action
            self._pending_online_action = None
            self._navigate_online_action(act)

        # Time out after 10s
        if time.time() - self._on_connecting_since > 10 and not (
                self._online and self._online.is_connected()):
            self._toast("Could not reach server.")
            self.state = "online_menu"

        self._draw_toast()

    # ------------------------------------------------------------------
    # ROOM BROWSER
    # ------------------------------------------------------------------

    def _browser_refresh_btn(self):
        return pygame.Rect(SCREEN_WIDTH // 2 - 170, 640, 150, 44)

    def _browser_back_btn(self):
        return pygame.Rect(SCREEN_WIDTH // 2 + 20, 640, 150, 44)

    def _browser_row_rects(self):
        rooms = self._online.rooms_list if self._online else []
        rects = []
        base_y = 180
        for i in range(len(rooms)):
            rects.append((pygame.Rect(120, base_y + i * 58,
                                      SCREEN_WIDTH - 240, 48), rooms[i]))
        return rects

    def _ev_room_browser(self, ev, mp) -> None:
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.state = "online_menu"
            return
        if ev.type != pygame.MOUSEBUTTONDOWN or ev.button != 1:
            return
        if self._browser_refresh_btn().collidepoint(mp):
            self._play(self.snd_click)
            if self._online:
                self._online.request_rooms()
                self._on_last_list_refresh = time.time()
            return
        if self._browser_back_btn().collidepoint(mp):
            self._play(self.snd_click)
            self.state = "online_menu"
            return
        for rect, summary in self._browser_row_rects():
            if rect.collidepoint(mp) and summary.get("status") == "waiting":
                self._play(self.snd_click)
                self._online.join_room_from_summary(summary)
                return

    def _dr_room_browser(self, mp) -> None:
        self._draw_top_bar()
        self._shadow_text(self.f_lg, "PUBLIC ROOMS",
                          SCREEN_WIDTH // 2, 70, TEXT_COLOR)
        self._draw_divider(110, 300)

        # Header row
        header_y = 140
        row_left = 120
        row_right = SCREEN_WIDTH - 120
        x_players = row_right - 330
        x_status = row_right - 210
        pygame.draw.line(self.screen, CREAM_DARK,
                         (row_left, header_y + 26), (row_right, header_y + 26), 1)
        self.screen.blit(self.f_sm.render("Name", True, TEXT_DIM),
                         (row_left + 20, header_y))
        self.screen.blit(self.f_sm.render("Players", True, TEXT_DIM),
                         (x_players, header_y))
        self.screen.blit(self.f_sm.render("Status", True, TEXT_DIM),
                         (x_status, header_y))

        rows = self._browser_row_rects()
        if not rows:
            msg = "No public rooms. Create one or refresh!"
            t = self.f_sub.render(msg, True, TEXT_DIM)
            self.screen.blit(t, t.get_rect(
                center=(SCREEN_WIDTH // 2, 300)))
        for rect, summary in rows:
            joinable = summary.get("status") == "waiting"
            hovered = rect.collidepoint(mp) and joinable
            ht = self._get_btn_hover_t(
                "room_" + summary.get("code", "?"), hovered, dt=0.14)
            # Lift + shadow on hover
            lift = int(ht * 3)
            if ht > 0.02:
                sh = pygame.Surface((rect.w + 6, rect.h + 6), pygame.SRCALPHA)
                pygame.draw.rect(sh, (0, 0, 0, int(40 + 40 * ht)),
                                 (3, 4 - lift, rect.w, rect.h), border_radius=10)
                self.screen.blit(sh, (rect.x - 3, rect.y - 2 + lift))
            draw = rect.move(0, -lift)
            if joinable:
                bg_col = _lerp(CREAM, ACCENT_SELECTED_LT, ht * 0.25)
            else:
                bg_col = CREAM_DARK
            pygame.draw.rect(self.screen, bg_col, draw, border_radius=10)
            border_col = _lerp(PANEL_BORDER, ACCENT_SELECTED_LT, ht) \
                if joinable else PANEL_BORDER
            pygame.draw.rect(self.screen, border_col, draw,
                             2 if hovered else 1, border_radius=10)
            name = summary.get("name", "(unnamed)")[:22]
            t = self.f_body.render(name, True, TEXT_COLOR)
            self.screen.blit(t, (draw.x + 20, draw.centery - t.get_height() // 2))
            pc = f"{summary.get('player_count', 0)}/{summary.get('max_players', 3)}"
            t = self.f_body.render(pc, True, TEXT_DIM)
            self.screen.blit(t, (x_players, draw.centery - t.get_height() // 2))
            st = _fmt_status(summary.get("status", "waiting"))
            col = (40, 150, 80) if joinable else TEXT_MUTED
            t = self.f_body.render(st, True, col)
            self.screen.blit(t, (x_status, draw.centery - t.get_height() // 2))
            if summary.get("has_ai"):
                ai_tag_rect = pygame.Rect(draw.right - 88, draw.centery - 11, 32, 22)
                pygame.draw.rect(self.screen, ACCENT_SELECTED, ai_tag_rect,
                                 border_radius=6)
                ai_tag = self.f_sm.render("AI", True, WHITE)
                self.screen.blit(ai_tag, ai_tag.get_rect(center=ai_tag_rect.center))
            # Hover caret ">" on the far right
            if hovered:
                caret = self.f_med.render("\u25b6", True, ACCENT_SELECTED)
                self.screen.blit(caret,
                                 (draw.right - 36,
                                  draw.centery - caret.get_height() // 2))

        self._draw_button(self._browser_refresh_btn(), "Refresh", mp)
        self._draw_button(self._browser_back_btn(), "Back", mp)

        # Auto-refresh every 5s
        if time.time() - self._on_last_list_refresh > 5:
            if self._online:
                self._online.request_rooms()
                self._on_last_list_refresh = time.time()

        self._draw_toast()

    # ------------------------------------------------------------------
    # JOIN BY CODE
    # ------------------------------------------------------------------

    def _code_box_rect(self):
        return pygame.Rect(SCREEN_WIDTH // 2 - 170, 240, 340, 52)

    def _name_box_rect(self):
        return pygame.Rect(SCREEN_WIDTH // 2 - 170, 360, 340, 42)

    def _join_btn(self):
        return pygame.Rect(SCREEN_WIDTH // 2 - 170, 460, 150, 46)

    def _join_back_btn(self):
        return pygame.Rect(SCREEN_WIDTH // 2 + 20, 460, 150, 46)

    def _ev_join_by_code(self, ev, mp) -> None:
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.state = "online_menu"
            return
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self._code_box_rect().collidepoint(mp):
                self._on_active_field = "code"
                return
            if self._name_box_rect().collidepoint(mp):
                self._on_active_field = "name"
                return
            self._on_active_field = None
            if self._join_btn().collidepoint(mp):
                self._play(self.snd_click)
                if len(self._on_room_code) == ROOM_CODE_LEN and self._online:
                    self._online.set_name(self._on_name_input)
                    self._online.join_room_by_code(self._on_room_code)
                else:
                    self._toast(f"Enter {ROOM_CODE_LEN}-char code.")
                return
            if self._join_back_btn().collidepoint(mp):
                self._play(self.snd_click)
                self.state = "online_menu"
                return
        if self._on_active_field == "code":
            self._on_text_event(ev, "code", ROOM_CODE_LEN,
                                upper=True, alnum_only=True)
        elif self._on_active_field == "name":
            self._on_text_event(ev, "name", MAX_PLAYER_NAME_LEN)

    def _dr_join_by_code(self, mp) -> None:
        self._draw_top_bar()
        self._shadow_text(self.f_lg, "JOIN BY CODE",
                          SCREEN_WIDTH // 2, 80, TEXT_COLOR)
        self._draw_divider(120, 280)

        t = self.f_sub.render("Enter Room Code", True, TEXT_DIM)
        self.screen.blit(t, t.get_rect(center=(SCREEN_WIDTH // 2, 200)))
        self._draw_text_input(self._code_box_rect(),
                              " ".join(self._on_room_code).ljust(
                                  ROOM_CODE_LEN * 2 - 1, " "),
                              None,
                              active=self._on_active_field == "code",
                              big=True,
                              placeholder="_ _ _ _ _ _")

        t = self.f_sub.render("Your Name", True, TEXT_DIM)
        self.screen.blit(t, t.get_rect(center=(SCREEN_WIDTH // 2, 330)))
        self._draw_text_input(self._name_box_rect(),
                              self._on_name_input,
                              None,
                              active=self._on_active_field == "name",
                              placeholder="Player")

        valid = len(self._on_room_code) == ROOM_CODE_LEN
        self._draw_button(self._join_btn(), "Join", mp, enabled=valid)
        self._draw_button(self._join_back_btn(), "Back", mp)
        self._draw_toast()

    # ------------------------------------------------------------------
    # CREATE ROOM
    # ------------------------------------------------------------------

    def _create_name_box(self):
        return pygame.Rect(SCREEN_WIDTH // 2 - 220, 210, 440, 42)

    def _create_public_btn(self):
        return pygame.Rect(SCREEN_WIDTH // 2 - 220, 290, 210, 46)

    def _create_private_btn(self):
        return pygame.Rect(SCREEN_WIDTH // 2 + 10, 290, 210, 46)

    def _create_2p_btn(self):
        return pygame.Rect(SCREEN_WIDTH // 2 - 220, 390, 210, 46)

    def _create_3p_btn(self):
        return pygame.Rect(SCREEN_WIDTH // 2 + 10, 390, 210, 46)

    def _create_go_btn(self):
        return pygame.Rect(SCREEN_WIDTH // 2 - 170, 500, 150, 48)

    def _create_back_btn(self):
        return pygame.Rect(SCREEN_WIDTH // 2 + 20, 500, 150, 48)

    def _ev_create_room(self, ev, mp) -> None:
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.state = "online_menu"
            return
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self._create_name_box().collidepoint(mp):
                self._on_active_field = "room_name"
                return
            self._on_active_field = None
            if self._create_public_btn().collidepoint(mp):
                self._play(self.snd_click)
                self._on_is_public = True
            elif self._create_private_btn().collidepoint(mp):
                self._play(self.snd_click)
                self._on_is_public = False
            elif self._create_2p_btn().collidepoint(mp):
                self._play(self.snd_click)
                self._on_max_players = 2
            elif self._create_3p_btn().collidepoint(mp):
                self._play(self.snd_click)
                self._on_max_players = 3
            elif self._create_go_btn().collidepoint(mp):
                self._play(self.snd_click)
                if self._online:
                    self._online.set_name(self._on_name_input)
                    self._online.create_room(
                        self._on_room_name or f"{self._on_name_input}'s Room",
                        self._on_is_public, self._on_max_players)
            elif self._create_back_btn().collidepoint(mp):
                self._play(self.snd_click)
                self.state = "online_menu"
        if self._on_active_field == "room_name":
            self._on_text_event(ev, "room_name", MAX_ROOM_NAME_LEN)

    def _dr_create_room(self, mp) -> None:
        self._draw_top_bar()
        self._shadow_text(self.f_lg, "CREATE ROOM",
                          SCREEN_WIDTH // 2, 80, TEXT_COLOR)
        self._draw_divider(120, 280)

        t = self.f_sub.render("Room Name", True, TEXT_DIM)
        self.screen.blit(t, (self._create_name_box().x, 180))
        self._draw_text_input(self._create_name_box(),
                              self._on_room_name, None,
                              active=self._on_active_field == "room_name",
                              placeholder="My awesome room")

        t = self.f_sub.render("Visibility", True, TEXT_DIM)
        self.screen.blit(t, (self._create_public_btn().x, 260))
        self._draw_button(self._create_public_btn(), "Public", mp,
                          selected=self._on_is_public, mode_select_style=True)
        self._draw_button(self._create_private_btn(), "Private", mp,
                          selected=not self._on_is_public, mode_select_style=True)

        t = self.f_sub.render("Max Players", True, TEXT_DIM)
        self.screen.blit(t, (self._create_2p_btn().x, 360))
        self._draw_button(self._create_2p_btn(), "2 Players", mp,
                          selected=self._on_max_players == 2, mode_select_style=True)
        self._draw_button(self._create_3p_btn(), "3 Players", mp,
                          selected=self._on_max_players == 3, mode_select_style=True)

        self._draw_button(self._create_go_btn(), "Create", mp)
        self._draw_button(self._create_back_btn(), "Back", mp)
        self._draw_toast()

    # ------------------------------------------------------------------
    # ROOM LOBBY
    # ------------------------------------------------------------------

    def _lobby_start_btn(self):
        return pygame.Rect(SCREEN_WIDTH // 2 - 170, 600, 150, 48)

    def _lobby_leave_btn(self):
        return pygame.Rect(SCREEN_WIDTH // 2 + 20, 600, 150, 48)

    def _lobby_slot_rect(self, i):
        return pygame.Rect(160, 200 + i * 90, SCREEN_WIDTH - 320, 72)

    def _lobby_action_rect(self, i, which):
        """which: 'kick' | 'add_ai' | 'remove_ai' | 'cycle_ai'."""
        slot_rect = self._lobby_slot_rect(i)
        if which == "kick":
            return pygame.Rect(slot_rect.right - 90, slot_rect.y + 20, 80, 32)
        if which == "add_ai":
            return pygame.Rect(slot_rect.right - 190, slot_rect.y + 20, 90, 32)
        if which == "remove_ai":
            return pygame.Rect(slot_rect.right - 90, slot_rect.y + 20, 80, 32)
        if which == "cycle_ai":
            return pygame.Rect(slot_rect.right - 280, slot_rect.y + 20, 80, 32)
        return pygame.Rect(0, 0, 0, 0)

    def _ev_room_lobby(self, ev, mp) -> None:
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            return
        if ev.type != pygame.MOUSEBUTTONDOWN or ev.button != 1:
            return
        if not self._online or not self._online.room:
            return
        room = self._online.room
        max_p = room.get("max_players", 3)
        host = self._online.am_host()

        # Start / Leave
        if self._lobby_leave_btn().collidepoint(mp):
            self._play(self.snd_click)
            self._online.leave_room()
            self.state = "online_menu"
            return
        if host and self._lobby_start_btn().collidepoint(mp):
            total = (len(room.get("players", []))
                     + len(room.get("ai_slots", [])))
            if total >= max_p:
                self._play(self.snd_click)
                self._online.start_game()
            else:
                self._toast("Room not full yet.")
            return

        # Per-slot actions
        players = {p["slot"]: p for p in room.get("players", [])}
        ais = {a["slot"]: a for a in room.get("ai_slots", [])}
        for i in range(max_p):
            slot = i + 1
            if slot in players:
                p = players[slot]
                if host and not p.get("is_host"):
                    if self._lobby_action_rect(i, "kick").collidepoint(mp):
                        self._play(self.snd_click)
                        self._online.kick(p["id"])
                        return
            elif slot in ais:
                if host:
                    if self._lobby_action_rect(i, "remove_ai").collidepoint(mp):
                        self._play(self.snd_click)
                        self._online.remove_ai(slot)
                        return
                    if self._lobby_action_rect(i, "cycle_ai").collidepoint(mp):
                        self._play(self.snd_click)
                        idx = self._on_ai_type_cycle.get(slot, 0)
                        idx = (idx + 1) % len(ONLINE_AI_TYPES)
                        self._on_ai_type_cycle[slot] = idx
                        ai_type = ONLINE_AI_TYPES[idx]
                        params = self._default_ai_params(ai_type)
                        self._online.remove_ai(slot)
                        self._online.add_ai(slot, ai_type, params)
                        return
            else:
                if host and self._lobby_action_rect(i, "add_ai").collidepoint(mp):
                    self._play(self.snd_click)
                    idx = self._on_ai_type_cycle.get(slot, 0)
                    ai_type = ONLINE_AI_TYPES[idx]
                    self._online.add_ai(slot, ai_type,
                                        self._default_ai_params(ai_type))
                    return

    def _default_ai_params(self, ai_type: str) -> dict:
        if ai_type == "MCTS":
            return {"simulations": 1000}
        if ai_type == "Minimax":
            return {"depth": 4}
        return {}

    def _dr_room_lobby(self, mp) -> None:
        self._draw_top_bar()
        room = self._online.room if self._online else None
        if not room:
            self._shadow_text(self.f_lg, "ROOM", SCREEN_WIDTH // 2, 70, TEXT_COLOR)
            return
        title = f"ROOM: {room.get('code', '------')}"
        sub = "Public" if room.get("is_public") else "Private"
        self._shadow_text(self.f_lg, title, SCREEN_WIDTH // 2, 70, TEXT_COLOR)
        t = self.f_sm.render(f"{room.get('name', '')}  •  {sub}", True, TEXT_DIM)
        self.screen.blit(t, t.get_rect(center=(SCREEN_WIDTH // 2, 110)))
        self._draw_divider(135, 260)

        max_p = room.get("max_players", 3)
        players = {p["slot"]: p for p in room.get("players", [])}
        ais = {a["slot"]: a for a in room.get("ai_slots", [])}
        host = self._online.am_host()

        count = len(players) + len(ais)
        pc = self.f_sub.render(f"Players: {count}/{max_p}", True, TEXT_COLOR)
        self.screen.blit(pc, (160, 160))

        for i in range(max_p):
            slot = i + 1
            rect = self._lobby_slot_rect(i)
            pygame.draw.rect(self.screen, CREAM, rect, border_radius=10)
            pygame.draw.rect(self.screen, PANEL_BORDER, rect, 1, border_radius=10)

            # Player disc indicator on the left
            disc = self.mini_discs.get(slot)
            if disc:
                self.screen.blit(disc, disc.get_rect(center=(rect.x + 36, rect.centery)))
            lbl = self.f_sub.render(f"Slot {slot}", True, PLAYER_COLORS.get(slot, TEXT_COLOR))
            self.screen.blit(lbl, (rect.x + 70, rect.y + 10))

            if slot in players:
                p = players[slot]
                name = p.get("name", "Player")
                tag = "  (You)" if self._is_me(p) else ""
                host_tag = "  [Host]" if p.get("is_host") else ""
                self.screen.blit(
                    self.f_body.render(name + tag + host_tag, True, TEXT_COLOR),
                    (rect.x + 70, rect.y + 40))
                if host and not p.get("is_host"):
                    self._draw_button(self._lobby_action_rect(i, "kick"),
                                      "Kick", mp)
            elif slot in ais:
                ai = ais[slot]
                param_txt = ""
                if ai.get("ai_type") == "MCTS":
                    param_txt = f" (sims {ai.get('params', {}).get('simulations', '?')})"
                elif ai.get("ai_type") == "Minimax":
                    param_txt = f" (depth {ai.get('params', {}).get('depth', '?')})"
                self.screen.blit(
                    self.f_body.render(
                        f"AI: {ai.get('ai_type')}{param_txt}", True, ACCENT_SELECTED),
                    (rect.x + 70, rect.y + 40))
                if host:
                    self._draw_button(self._lobby_action_rect(i, "cycle_ai"),
                                      "Cycle", mp)
                    self._draw_button(self._lobby_action_rect(i, "remove_ai"),
                                      "Remove", mp)
            else:
                self.screen.blit(
                    self.f_body.render("Empty", True, TEXT_MUTED),
                    (rect.x + 70, rect.y + 40))
                if host:
                    self._draw_button(self._lobby_action_rect(i, "add_ai"),
                                      "+ AI", mp)

        # Start + Leave
        total = len(players) + len(ais)
        can_start = host and total >= max_p
        self._draw_button(self._lobby_start_btn(), "Start Game", mp,
                          enabled=can_start)
        self._draw_button(self._lobby_leave_btn(), "Leave Room", mp)

        # Footer hint
        hint = ("Waiting for host to start..." if not host
                else "Fill every slot then press Start Game.")
        t = self.f_sm.render(hint, True, TEXT_MUTED)
        self.screen.blit(t, t.get_rect(center=(SCREEN_WIDTH // 2, 570)))
        self._draw_toast()

    def _is_me(self, player: dict) -> bool:
        if not self._online:
            return False
        if self._online.my_sid and player.get("id") == self._online.my_sid:
            return True
        return player.get("name") == self._online.my_name

    # ------------------------------------------------------------------
    # PLAYING ONLINE
    # ------------------------------------------------------------------

    def _ev_playing_online(self, ev, mp) -> None:
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.state = "paused_online"
            return
        if not self._online:
            return
        if not self._online.is_my_turn or self.anim:
            return
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            col = self._col_from_x(mp[0])
            if col >= 0 and self.board and self.board.is_valid(col):
                if self._online.make_move(col):
                    self._play(self.snd_drop)
                    self._start_anim(col, self.cur)

    def _dr_playing_online(self, mp) -> None:
        # Sync board with server state
        self._sync_from_server_state()
        self._draw_turn_indicator_online()
        self._draw_board()
        self._draw_scoreboard_online()
        if (self._online and self._online.is_my_turn
                and not self.anim):
            self.hcol = self._col_from_x(mp[0])
        else:
            self.hcol = -1
        if self.hcol >= 0 and not self.anim:
            self._draw_hover()
        if self.anim:
            self._draw_anim_disc()

        # Status line
        status = ("Your turn" if (self._online and self._online.is_my_turn)
                  else "Waiting for opponent...")
        t = self.f_sm.render(status, True, TEXT_DIM)
        t.set_alpha(int(180 + 75 * math.sin(self._tick * 0.08)))
        self.screen.blit(t, t.get_rect(center=(SCREEN_WIDTH // 2, 42)))

        code = self._online.room.get("code", "") if self._online and self._online.room else ""
        t = self.f_sm.render(f"Room: {code}   ESC to pause",
                             True, TEXT_MUTED)
        self.screen.blit(t, (14, SCREEN_HEIGHT - 40))
        self._draw_toast()

    def _sync_from_server_state(self) -> None:
        if not self._online or not self._online.game_state:
            return
        from board import Board
        gs = self._online.game_state
        desired_board = gs.get("board")
        if desired_board is None:
            return
        # If local board lags server (e.g. no animation running), overwrite.
        # Otherwise keep local animation.
        local = self.board.to_list() if self.board else None
        if not self.anim and desired_board != local:
            self.board = Board.from_list(desired_board)
        self.cur = gs.get("current_player", self.cur)
        s = gs.get("scores") or {}
        if s:
            self.scores = {int(k): int(v) for k, v in s.items()}

    def _draw_turn_indicator_online(self) -> None:
        if not self.board:
            return
        name = PLAYER_NAMES.get(self.cur, f"P{self.cur}")
        who = "Your" if (self._online and self._online.is_my_turn) else f"{name}'s"
        label = f"{who} Turn"
        ds = self.mini_discs.get(self.cur)
        t = self.f_med.render(label, True,
                              PLAYER_COLORS.get(self.cur, TEXT_COLOR))
        tw = t.get_width()
        dw = ds.get_width() if ds else 0
        sx = (SCREEN_WIDTH - dw - 10 - tw) // 2
        if ds:
            self.screen.blit(ds, ds.get_rect(center=(sx + dw // 2, 78)))
        self.screen.blit(t, (sx + dw + 10, 78 - t.get_height() // 2))

    def _draw_scoreboard_online(self) -> None:
        """Reuse the offline scoreboard helper (same style)."""
        if hasattr(self, "_draw_scoreboard"):
            self._draw_scoreboard()

    # ------------------------------------------------------------------
    # ONLINE GAMEOVER
    # ------------------------------------------------------------------

    def _online_over_btns(self):
        cx = SCREEN_WIDTH // 2
        w, h, gap = 180, 48, 20
        btn_y = 350 + (self.num_p or 3) * 50
        return [
            (pygame.Rect(cx - w - gap // 2, btn_y, w, h), "Leave"),
            (pygame.Rect(cx + gap // 2, btn_y, w, h), "Main Menu"),
        ]

    def _ev_online_gameover(self, ev, mp) -> None:
        if ev.type != pygame.MOUSEBUTTONDOWN or ev.button != 1:
            return
        for rect, label in self._online_over_btns():
            if rect.collidepoint(mp):
                self._play(self.snd_click)
                if label == "Leave":
                    if self._online:
                        self._online.leave_room()
                    self.state = "online_menu"
                elif label == "Main Menu":
                    if self._online:
                        self._online.leave_room()
                        self._disconnect_online()
                    self.state = "menu"

    def _dr_online_gameover(self, mp) -> None:
        # Reuse offline gameover visuals: populate self.winner/scores/win_cells/win_reason.
        self.winner = self._on_winner
        self.win_reason = self._on_win_reason
        # Scores dict may come with string keys
        self.scores = {int(k): int(v) for k, v in (self._on_scores or {}).items()}
        self.win_cells = self._on_win_cells
        # Use the offline _dr_over renderer via duck-typing
        if hasattr(self, "_dr_over"):
            self._dr_over(mp)
        # Replace default buttons with online ones
        for rect, label in self._online_over_btns():
            self._draw_button(rect, label, mp)
        self._draw_toast()

    # ------------------------------------------------------------------
    # PAUSED ONLINE (treat like offline pause with online-aware buttons)
    # ------------------------------------------------------------------

    def _ev_paused_online(self, ev, mp) -> None:
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.state = "playing_online"
            return
        if ev.type != pygame.MOUSEBUTTONDOWN or ev.button != 1:
            return
        for rect, label in self._paused_online_btns():
            if rect.collidepoint(mp):
                self._play(self.snd_click)
                if label == "Resume":
                    self.state = "playing_online"
                elif label == "Leave Room":
                    if self._online:
                        self._online.leave_room()
                    self.state = "online_menu"

    def _paused_online_btns(self):
        cx = SCREEN_WIDTH // 2
        w, h = 230, 48
        y0 = 310
        return [
            (pygame.Rect(cx - w // 2, y0, w, h), "Resume"),
            (pygame.Rect(cx - w // 2, y0 + 62, w, h), "Leave Room"),
        ]

    def _dr_paused_online(self, mp) -> None:
        # Draw underlying game first
        self._dr_playing_online(mp)
        ov = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        ov.fill((250, 245, 235, 200))
        self.screen.blit(ov, (0, 0))
        pw, ph = 340, 220
        panel_rect = pygame.Rect(SCREEN_WIDTH // 2 - pw // 2, 220, pw, ph)
        self._draw_panel(panel_rect, "PAUSED")
        for rect, label in self._paused_online_btns():
            self._draw_button(rect, label, mp)

    # ------------------------------------------------------------------
    # shared helpers
    # ------------------------------------------------------------------

    def _draw_text_input(self, rect, text, label, active=False,
                         big=False, placeholder="") -> None:
        if label:
            t = self.f_sm.render(label, True, TEXT_DIM)
            self.screen.blit(t, (rect.x, rect.y - 22))
        mp = pygame.mouse.get_pos()
        hovered = rect.collidepoint(mp) and not active
        # Glow behind the input when active
        if active:
            glow = pygame.Surface((rect.w + 14, rect.h + 14), pygame.SRCALPHA)
            pulse = 0.5 + 0.5 * math.sin(self._tick * 0.1)
            a = int(60 + 50 * pulse)
            pygame.draw.rect(glow, (*ACCENT_SELECTED_LT, a),
                             (0, 0, rect.w + 14, rect.h + 14), border_radius=12)
            self.screen.blit(glow, (rect.x - 7, rect.y - 7),
                             special_flags=pygame.BLEND_RGBA_ADD)
        bg = (255, 252, 245) if active else (CREAM if not hovered else (252, 248, 238))
        pygame.draw.rect(self.screen, bg, rect, border_radius=8)
        if active:
            border_col = ACCENT_SELECTED_LT
            border_w = 3
        elif hovered:
            border_col = _lerp(BTN_BORDER, ACCENT_SELECTED_LT, 0.5)
            border_w = 2
        else:
            border_col = BTN_BORDER
            border_w = 1
        pygame.draw.rect(self.screen, border_col, rect, border_w, border_radius=8)
        txt = text or placeholder
        col = TEXT_COLOR if text else TEXT_MUTED
        font = self.f_med if big else self.f_body
        t = font.render(txt, True, col)
        clip = self.screen.get_clip()
        self.screen.set_clip(rect.inflate(-12, -4))
        self.screen.blit(t, (rect.x + 12, rect.y + (rect.h - t.get_height()) // 2))
        self.screen.set_clip(clip)
        # Caret blink
        if active and (self._tick // 20) % 2 == 0 and text:
            x = rect.x + 12 + t.get_width() + 2
            x = min(x, rect.right - 8)
            pygame.draw.line(self.screen, TEXT_COLOR,
                             (x, rect.y + 8), (x, rect.bottom - 8), 2)

    def _draw_toast(self) -> None:
        if not self._on_toast:
            return
        msg = self._on_toast
        t = self.f_body.render(msg, True, WHITE)
        pad = 14
        w, h = t.get_width() + pad * 2, t.get_height() + pad
        rect = pygame.Rect(SCREEN_WIDTH // 2 - w // 2,
                           SCREEN_HEIGHT - h - 20, w, h)
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(s, (*BOARD_COLOR, 230), (0, 0, w, h), border_radius=10)
        pygame.draw.rect(s, (*CREAM, 200), (0, 0, w, h), 1, border_radius=10)
        self.screen.blit(s, rect.topleft)
        self.screen.blit(t, (rect.x + pad, rect.y + pad // 2))


# --- local helper ---------------------------------------------------------------

def _lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
