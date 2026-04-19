"""Pygame app: menus, tinted bitmap board, disc sprites, game loop, save/load."""

import pygame
import sys
import os
import json
import math
import array

from constants import *
from board import Board
from ai import RandomAI, MCTSAI, MinimaxAI
from online_ui import OnlineUIMixin


def _ease_out_quad(t):
    """Quadratic ease-out: decelerates smoothly."""
    return t * (2 - t)


def _ease_out_bounce(t):
    """Gentle bounce at end of animation."""
    if t < 1 / 2.75:
        return 7.5625 * t * t
    elif t < 2 / 2.75:
        t -= 1.5 / 2.75
        return 7.5625 * t * t + 0.75
    elif t < 2.5 / 2.75:
        t -= 2.25 / 2.75
        return 7.5625 * t * t + 0.9375
    else:
        t -= 2.625 / 2.75
        return 7.5625 * t * t + 0.984375


def _lerp_color(c1, c2, t):
    """Linearly interpolate between two RGB colors."""
    t = max(0.0, min(1.0, t))
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(len(c1)))


def _gradient_surface(w, h, top, bot):
    """Vertical linear gradient."""
    surf = pygame.Surface((w, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        c = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
        pygame.draw.line(surf, c, (0, y), (w, y))
    return surf


def _load_disc_template():
    """Load 12×12 disc PNG; try DISC_PATH then disc.png."""
    base = os.path.dirname(os.path.abspath(__file__))
    for rel in (DISC_PATH, "assets/sprite/disc.png"):
        path = os.path.join(base, rel)
        if os.path.isfile(path):
            return pygame.image.load(path).convert_alpha()
    return None


def _colorize_disc_template(src: pygame.Surface, player: int) -> pygame.Surface:
    """Map grayscale / B&W pixels to PLAYER_DARK → PLAYER_LIGHT gradient."""
    w, h = src.get_size()
    out = pygame.Surface((w, h), pygame.SRCALPHA)
    dk = PLAYER_DARK[player]
    lt = PLAYER_LIGHT[player]
    for y in range(h):
        for x in range(w):
            r, g, b, a = src.get_at((x, y))
            if a < 8:
                continue
            lum = (r + g + b) / 765.0
            lum = max(0.0, min(1.0, lum))
            c = tuple(int(dk[i] + (lt[i] - dk[i]) * lum) for i in range(3))
            out.set_at((x, y), (*c, a))
    return out


def _disc_surface_procedural(player, radius):
    """Fallback glossy disc if no disc sprite file."""
    sz = radius * 2 + 14
    sz2 = sz * 2
    s = pygame.Surface((sz2, sz2), pygame.SRCALPHA)
    cx = cy = sz2 // 2
    r2 = radius * 2
    col = PLAYER_COLORS[player]
    lt = PLAYER_LIGHT[player]
    dk = PLAYER_DARK[player]

    pygame.draw.circle(s, (0, 0, 0, 25), (cx + 4, cy + 6), r2)
    pygame.draw.circle(s, col, (cx, cy), r2)
    pygame.draw.circle(s, dk, (cx, cy), r2, 3)

    hl = pygame.Surface((sz2, sz2), pygame.SRCALPHA)
    hr = max(r2 * 2 // 5, 1)
    hx, hy = cx - r2 // 4, cy - r2 // 4
    for i in range(hr, 0, -1):
        a = int(80 * (1 - i / hr))
        pygame.draw.circle(hl, (*lt, a), (hx, hy), i)
    s.blit(hl, (0, 0))

    pygame.draw.circle(s, (255, 255, 255, 180), (cx - r2 // 3, cy - r2 // 3), 5)
    pygame.draw.circle(s, (255, 255, 255, 50), (cx - r2 // 3, cy - r2 // 3), 10)

    return pygame.transform.smoothscale(s, (sz, sz))


def _disc_surface(player, radius, raw_template: pygame.Surface | None,
                  disc_px: int | None = None):
    """Disc sprite scaled with nearest-neighbor. disc_px=CELL_SIZE fits board cells."""
    sz = disc_px if disc_px is not None else (radius * 2 + 14)
    if raw_template is not None:
        tinted = _colorize_disc_template(raw_template, player)
        return pygame.transform.scale(tinted, (sz, sz))
    return _disc_surface_procedural(player, radius)


def _prepare_board_scaled() -> pygame.Surface:
    """B&W board: opaque black → BOARD_COLOR, transparent holes → SLOT_COLOR; nearest scale."""
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, BOARD_PATH)
    raw = pygame.image.load(path).convert_alpha()
    w, h = raw.get_size()
    out = pygame.Surface((w, h))
    out.fill(SLOT_COLOR)
    for y in range(h):
        for x in range(w):
            if raw.get_at((x, y))[3] > 128:
                out.set_at((x, y), BOARD_COLOR)
    return pygame.transform.scale(out, (BOARD_BLIT_W, BOARD_BLIT_H))


def _make_tone(freq, dur, vol=0.25):
    """Generate a short sine-wave tone using the *array* module."""
    sr = 44100
    n = int(sr * dur)
    buf = array.array("h")
    amp = int(32767 * vol)
    for i in range(n):
        env = min(i / 200, 1.0) * min((n - i) / 200, 1.0)
        buf.append(int(amp * env * math.sin(2 * math.pi * freq * i / sr)))
    return pygame.mixer.Sound(buffer=buf)


def _cell_center(row, col):
    """Screen center of the cell at (*row*, *col*)."""
    return (BOARD_X + col * CELL_STRIDE + CELL_CENTER_OFF,
            BOARD_Y + row * CELL_STRIDE + CELL_CENTER_OFF)


class App(OnlineUIMixin):
    """State machine: menu → config → play; rendering and persistence."""

    def __init__(self):
        pygame.mixer.pre_init(44100, -16, 1, 512)
        pygame.init()
        pygame.display.set_caption(TITLE)
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()

        icon = pygame.Surface((32, 32), pygame.SRCALPHA)
        for i, p in enumerate((1, 2, 3)):
            pygame.draw.circle(icon, PLAYER_COLORS[p], (8 + i * 8, 16), 6)
        pygame.display.set_icon(icon)

        _base = os.path.dirname(os.path.abspath(__file__))
        _font_file = os.path.join(_base, FONT_PATH)
        if os.path.isfile(_font_file):
            _F = lambda sz: pygame.font.Font(_font_file, sz)
            self.f_title = _F(50)
            self.f_sub = _F(24)
            self.f_btn = _F(22)
            self.f_sm = _F(18)
            self.f_med = _F(28)
            self.f_lg = _F(40)
            self.f_xl = _F(56)
            self.f_body = _F(20)
        else:
            _fn = "segoeui,arial,helvetica,dejavusans"
            self.f_title = pygame.font.SysFont(_fn, 50, bold=True)
            self.f_sub = pygame.font.SysFont(_fn, 24)
            self.f_btn = pygame.font.SysFont(_fn, 22)
            self.f_sm = pygame.font.SysFont(_fn, 18)
            self.f_med = pygame.font.SysFont(_fn, 28, bold=True)
            self.f_lg = pygame.font.SysFont(_fn, 40, bold=True)
            self.f_xl = pygame.font.SysFont(_fn, 56, bold=True)
            self.f_body = pygame.font.SysFont(_fn, 20)

        self.bg = _gradient_surface(SCREEN_WIDTH, SCREEN_HEIGHT, BG_TOP, BG_BOT)
        _disc_raw = _load_disc_template()
        self.discs = {
            p: _disc_surface(p, PIECE_RADIUS, _disc_raw, CELL_SIZE)
            for p in (1, 2, 3)}
        self.mini_discs = {
            p: _disc_surface(p, 12, _disc_raw, 36) for p in (1, 2, 3)}
        self._board_scaled = _prepare_board_scaled()

        self.sound_ok = False
        try:
            self.snd_drop = _make_tone(200, 0.10)
            self.snd_win = _make_tone(523, 0.35, 0.20)
            self.snd_click = _make_tone(420, 0.05, 0.15)
            self.sound_ok = True
        except Exception:
            pass

        self.state = "menu"
        self.game_mode = MODE_MULTI
        self.board: Board | None = None
        self.cur = 1
        self.num_p = 3
        self.ptypes = ["Human"] * 3
        self.ais: list = [None, None, None]
        self.winner = 0
        self.win_cells: list = []
        self.scores = {1: 0, 2: 0, 3: 0}
        self.win_reason = ""  # "connect4", "sudden_victory", "board_full", "tie"

        self.cfg_type = [0, 0, 0]
        self.cfg_mcts = [2, 2, 2]
        self.cfg_mm = [2, 2, 2]

        self.sp_ai_count = 1
        self.mp_extra = 1

        self.anim = False
        self.anim_col = 0
        self.anim_p = 0
        self.anim_y = 0.0
        self.anim_target = 0
        self.anim_row = 0
        self.anim_start_y = 0.0
        self.anim_speed = 0.0     
        self.anim_bounce = 0      
        self.anim_bounce_dy = 0.0

        self.ai_wait = 0

        self.hcol = -1

        self.flash_t = 0

        self.has_save = os.path.exists(SAVE_FILE)

        self._tick = 0

        self._btn_hovers = {}
        self._htp_drag = False        
        self._htp_drag_start_y = 0   
        self._htp_drag_start_s = 0   

        self._htp_scroll = 0

        self._pending_online_action = None
        self._online_init()


    def _play(self, snd):
        if self.sound_ok:
            try:
                snd.play()
            except Exception:
                pass

    def _shadow_text(self, font, txt, cx, cy, color, shadow=None):
        if shadow is None:
            shadow = (0, 0, 0, 25)
        sc = shadow[:3] if len(shadow) > 3 else shadow
        s = font.render(txt, True, sc)
        if len(shadow) > 3:
            s.set_alpha(shadow[3])
        self.screen.blit(s, s.get_rect(center=(cx + 1, cy + 1)))
        t = font.render(txt, True, color)
        self.screen.blit(t, t.get_rect(center=(cx, cy)))

    @staticmethod
    def _rounded_rect(surf, color, rect, radius=12):
        pygame.draw.rect(surf, color, rect, border_radius=radius)

    def _get_btn_hover_t(self, btn_id, hovered, dt=0.12):
        """Smooth interpolation for button hover state."""
        cur = self._btn_hovers.get(btn_id, 0.0)
        target = 1.0 if hovered else 0.0
        if cur < target:
            cur = min(cur + dt, target)
        elif cur > target:
            cur = max(cur - dt, target)
        self._btn_hovers[btn_id] = cur
        return cur

    def _draw_button(self, rect, text, mp, enabled=True, selected=False,
                     mode_select_style=False):
        hovered = rect.collidepoint(mp) and enabled
        ht = self._get_btn_hover_t(text + str(rect.x), hovered)

        if not enabled:
            col = BTN_DISABLED
            tc = BTN_TEXT_DISABLED
        elif selected:
            col = _lerp_color(ACCENT_SELECTED, ACCENT_SELECTED_LT, ht)
            tc = BTN_TEXT
        else:
            col = _lerp_color(BTN_NORMAL, BTN_HOVER, ht)
            tc = BTN_TEXT

        lift = int(ht * 3)
        shadow_surf = pygame.Surface((rect.w + 8, rect.h + 8), pygame.SRCALPHA)
        sa = int(35 + ht * 30)
        if selected and enabled:
            sa = int(45 + ht * 30)
        pygame.draw.rect(shadow_surf, (0, 0, 0, sa),
                         (4, 5 - lift, rect.w, rect.h), border_radius=12)
        self.screen.blit(shadow_surf, (rect.x - 4, rect.y - 3 + lift))

        draw_rect = rect.move(0, -lift)

        if selected and enabled:
            glow = pygame.Surface((rect.w + 12, rect.h + 12), pygame.SRCALPHA)
            glow_alpha = int(70 + ht * 60)
            pygame.draw.rect(glow, (*ACCENT_SELECTED_LT, glow_alpha),
                             (0, 0, rect.w + 12, rect.h + 12), border_radius=16)
            self.screen.blit(glow, (draw_rect.x - 6, draw_rect.y - 6),
                             special_flags=pygame.BLEND_RGBA_ADD)

        self._rounded_rect(self.screen, col, draw_rect, 12)
        if enabled and not selected:
            border_col = _lerp_color(BTN_BORDER, (60, 90, 110), ht)
            border_w = 2 if hovered else 1
            pygame.draw.rect(self.screen, border_col, draw_rect, border_w,
                             border_radius=12)
        elif selected:
            b = (MODE_SELECT_SELECTED_BORDER if mode_select_style
                 else ACCENT_SELECTED_LT)
            pygame.draw.rect(self.screen, b, draw_rect, 3, border_radius=12)
            inner = draw_rect.inflate(-6, -6)
            pygame.draw.rect(self.screen, (255, 255, 255, 40), inner,
                             1, border_radius=10)

        if selected and enabled:
            cx = draw_rect.x + 14
            cy = draw_rect.centery
            pygame.draw.circle(self.screen, ACCENT_SELECTED, (cx, cy), 5, 1)

        t = self.f_btn.render(text, True, tc)
        self.screen.blit(t, t.get_rect(center=draw_rect.center))

    def _draw_selector(self, rect, text, mp):
        hovered = rect.collidepoint(mp)
        ht = self._get_btn_hover_t("sel" + str(rect.x) + str(rect.y), hovered)
        col = _lerp_color(BTN_NORMAL, BTN_HOVER, ht)
        self._rounded_rect(self.screen, col, rect, 8)
        border_col = _lerp_color(BTN_BORDER, (60, 90, 110), ht)
        pygame.draw.rect(self.screen, border_col, rect, 1, border_radius=8)
        label = f"\u25c4  {text}  \u25ba"
        tc = _lerp_color(BTN_TEXT, WHITE, ht)
        t = self.f_sm.render(label, True, tc)
        self.screen.blit(t, t.get_rect(center=rect.center))

    def _draw_panel(self, rect, title=None):
        """Draw a cream panel with teal border and subtle shadow."""
        shadow = pygame.Surface((rect.w + 8, rect.h + 8), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 22), (4, 5, rect.w, rect.h), border_radius=16)
        self.screen.blit(shadow, (rect.x - 4, rect.y - 3))

        pygame.draw.rect(self.screen, CREAM, rect, border_radius=14)
        pygame.draw.rect(self.screen, PANEL_BORDER, rect, 2, border_radius=14)

        if title:
            bar = pygame.Rect(rect.x, rect.y, rect.w, 50)
            pygame.draw.rect(self.screen, BTN_NORMAL, bar,
                             border_top_left_radius=14, border_top_right_radius=14)
            t = self.f_med.render(title, True, BTN_TEXT)
            self.screen.blit(t, t.get_rect(center=(bar.centerx, bar.centery)))

    def _draw_divider(self, y, w=200):
        """Draw a subtle horizontal divider line centered on screen."""
        lx = SCREEN_WIDTH // 2 - w // 2
        surf = pygame.Surface((w, 2), pygame.SRCALPHA)
        for x in range(w):
            dist = min(x, w - x) / (w / 2)
            a = int(80 * dist)
            surf.set_at((x, 0), (*CREAM_DARK[:3], a))
            surf.set_at((x, 1), (*CREAM_DARK[:3], a // 2))
        self.screen.blit(surf, (lx, y))

    def _draw_top_bar(self):
        """Decorative gradient top bar."""
        bar_h = 5
        for y in range(bar_h):
            t = y / bar_h
            c = _lerp_color(BTN_NORMAL, BOARD_EDGE, t)
            pygame.draw.line(self.screen, c, (0, y), (SCREEN_WIDTH, y))

    def run(self):
        """Run the main loop until quit."""
        while True:
            mp = pygame.mouse.get_pos()
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                self._event(ev, mp)
            self._update(mp)
            self._draw(mp)
            pygame.display.flip()
            self.clock.tick(FPS)

    def _event(self, ev, mp):
        """Route pygame events to the handler for *self.state*."""
        if self._online_event(ev, mp):
            return
        if self.state == "paused_online":
            self._ev_paused_online(ev, mp)
            return
        h = {"menu": self._ev_menu, "modeselect": self._ev_modeselect,
             "howtoplay": self._ev_howtoplay, "config": self._ev_config,
             "playing": self._ev_play, "paused": self._ev_pause,
             "gameover": self._ev_over}.get(self.state)
        if h:
            h(ev, mp)


    def _menu_btns(self):
        x = SCREEN_WIDTH // 2 - 120
        y0 = 350
        return [
            (pygame.Rect(x, y0, 240, 50), "New Game", True),
            (pygame.Rect(x, y0 + 62, 240, 50), "Continue", self.has_save),
            (pygame.Rect(x, y0 + 124, 240, 50), "Online", True),
            (pygame.Rect(x, y0 + 186, 240, 50), "How to Play", True),
            (pygame.Rect(x, y0 + 248, 240, 50), "Quit", True),
        ]

    def _ev_menu(self, ev, mp):
        if ev.type != pygame.MOUSEBUTTONDOWN or ev.button != 1:
            return
        for rect, label, ok in self._menu_btns():
            if rect.collidepoint(mp) and ok:
                self._play(self.snd_click)
                if label == "New Game":
                    self.state = "modeselect"
                elif label == "Continue":
                    self._load_game()
                elif label == "Online":
                    self._start_online_connection()
                elif label == "How to Play":
                    self._htp_scroll = 0
                    self.state = "howtoplay"
                elif label == "Quit":
                    pygame.quit()
                    sys.exit()


    def _htp_back_btn(self):
        return pygame.Rect(SCREEN_WIDTH // 2 - 80, 670, 160, 46)

    def _htp_inner_rect(self):
        panel = pygame.Rect(100, 100, SCREEN_WIDTH - 200, 550)
        return pygame.Rect(panel.x + 20, panel.y + 15, panel.w - 58, panel.h - 30)

    def _htp_scrollbar_rects(self):
        """Return (track_rect, thumb_rect) for the scrollbar."""
        panel = pygame.Rect(100, 100, SCREEN_WIDTH - 200, 550)
        track_x = panel.right - 28
        track_y = panel.y + 14
        track_h = panel.h - 28
        track = pygame.Rect(track_x, track_y, 10, track_h)
        max_scroll = self._htp_max_scroll()
        if max_scroll <= 0:
            return track, pygame.Rect(track_x, track_y, 10, track_h)
        inner_h = self._htp_inner_rect().h
        content_h = inner_h + max_scroll
        ratio = inner_h / content_h
        thumb_h = max(28, int(track_h * ratio))
        thumb_travel = track_h - thumb_h
        thumb_y = track_y + int(thumb_travel * self._htp_scroll / max_scroll)
        thumb = pygame.Rect(track_x, thumb_y, 10, thumb_h)
        return track, thumb

    def _htp_rules(self):
        return [
            ("OBJECTIVE", [
                "Connect 4 discs in a row (horizontal, vertical, or diagonal)",
                "to score 1000 points. Highest score wins!",
            ]),
            ("SCORING SYSTEM", [
                "• Connect 2: 2 points",
                "• Connect 3: 15 points",
                "• Connect 4: 1000 points (Grand Slam!)",
                "Note: Only the longest sequence in each line counts.",
            ]),
            ("WIN CONDITIONS", [
                "• Sudden Victory: Create 2+ Connect 4 lines = instant win!",
                "• Regular Win: First Connect 4 usually wins (~99%).",
                "• Board Full: Player with highest score wins.",
                "• Tie-breaker: Longest sequence, then center control.",
            ]),
            ("GAMEPLAY", [
                "• Players take turns dropping a disc into one of the 8 columns.",
                "• The disc falls to the lowest empty cell.",
                "• Scores update in real-time after each move.",
            ]),
            ("GAME MODES", [
                "• SinglePlayer: 1 or 2 AI opponents; Player 1 can be",
                "  Human or AI (Random, MCTS, Minimax).",
                "• Multiplayer: Play with 1 or 2 friends on the same device.",
            ]),
            ("CONTROLS", [
                "• Left-click a column to drop your disc.",
                "• Press ESC to pause the game.",
                "• Use the pause menu to save & quit or return to the main menu.",
            ]),
            ("AI DIFFICULTY", [
                "• Random: Easy - picks any valid column.",
                "• MCTS: Medium - uses Monte Carlo simulation.",
                "  More simulations = harder (200 - 5000).",
                "• Minimax: Hard - thinks several moves ahead.",
                "  Higher depth = harder (2 - 6).",
            ]),
        ]

    def _htp_max_scroll(self):
        inner = self._htp_inner_rect()
        tail = 5 + sum(
            34 + len(lines) * 24 + 14 for _, lines in self._htp_rules())
        return max(0, tail - inner.h)

    def _ev_howtoplay(self, ev, mp):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.state = "menu"
            return
        _, thumb = self._htp_scrollbar_rects()
        max_scroll = self._htp_max_scroll()
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self._htp_back_btn().collidepoint(mp):
                self._play(self.snd_click)
                self.state = "menu"
            elif thumb.collidepoint(mp) and max_scroll > 0:
                self._htp_drag = True
                self._htp_drag_start_y = mp[1]
                self._htp_drag_start_s = self._htp_scroll
        if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            self._htp_drag = False
        if ev.type == pygame.MOUSEMOTION and self._htp_drag and max_scroll > 0:
            track, _ = self._htp_scrollbar_rects()
            thumb_h = max(28, int(track.h * self._htp_inner_rect().h /
                                  (self._htp_inner_rect().h + max_scroll)))
            thumb_travel = track.h - thumb_h
            if thumb_travel > 0:
                dy = mp[1] - self._htp_drag_start_y
                self._htp_scroll = self._htp_drag_start_s + int(dy * max_scroll / thumb_travel)
                self._htp_scroll = max(0, min(self._htp_scroll, max_scroll))
        if ev.type == pygame.MOUSEWHEEL:
            self._htp_scroll = max(0, self._htp_scroll - ev.y * 20)
            self._htp_scroll = min(self._htp_scroll, max_scroll)


    def _mode_btns(self):
        cx = SCREEN_WIDTH // 2
        w = 320
        return [
            (pygame.Rect(cx - w // 2, 290, w, 54), "SinglePlayer"),
            (pygame.Rect(cx - w // 2, 364, w, 54), "Multiplayer"),
            (pygame.Rect(cx - w // 2, 520, w, 48), "Back"),
        ]

    def _mode_sub_btns_sp(self):
        cx = SCREEN_WIDTH // 2
        w = 145
        y = 445
        return [
            (pygame.Rect(cx - 160, y, w, 42), "+ 1 AI", 1),
            (pygame.Rect(cx + 15, y, w, 42), "+ 2 AI", 2),
        ]

    def _mode_sub_btns_mp(self):
        cx = SCREEN_WIDTH // 2
        w = 145
        y = 445
        return [
            (pygame.Rect(cx - 160, y, w, 42), "+ 1 Player", 1),
            (pygame.Rect(cx + 15, y, w , 42), "+ 2 Players", 2),
        ]

    def _ev_modeselect(self, ev, mp):
        if ev.type != pygame.MOUSEBUTTONDOWN or ev.button != 1:
            return
        for rect, label in self._mode_btns():
            if rect.collidepoint(mp):
                self._play(self.snd_click)
                if label == "SinglePlayer":
                    self.game_mode = MODE_SINGLE
                elif label == "Multiplayer":
                    self.game_mode = MODE_MULTI
                elif label == "Back":
                    self.state = "menu"
                    return

        if self.game_mode == MODE_SINGLE:
            for rect, label, count in self._mode_sub_btns_sp():
                if rect.collidepoint(mp):
                    self._play(self.snd_click)
                    self.sp_ai_count = count
                    self._setup_config_for_mode()
                    self.state = "config"
                    return
        elif self.game_mode == MODE_MULTI:
            for rect, label, count in self._mode_sub_btns_mp():
                if rect.collidepoint(mp):
                    self._play(self.snd_click)
                    self.mp_extra = count
                    self._setup_config_for_mode()
                    self.state = "config"
                    return

    def _setup_config_for_mode(self):
        if self.game_mode == MODE_SINGLE:
            n = 1 + self.sp_ai_count
            self.num_p = n
            self.cfg_type = [0] * n
            for i in range(1, n):
                self.cfg_type[i] = 1
            self.cfg_mcts = [2] * n
            self.cfg_mm = [2] * n
        else:
            n = 1 + self.mp_extra
            self.num_p = n
            self.cfg_type = [0] * n
            self.cfg_mcts = [2] * n
            self.cfg_mm = [2] * n


    def _cfg_type_rect(self, i):
        return pygame.Rect(435, 230 + i * 95, 170, 40)

    def _cfg_param_rect(self, i):
        return pygame.Rect(620, 230 + i * 95, 170, 40)

    def _cfg_btns(self):
        return [
            (pygame.Rect(345, 570, 160, 48), "Start Game"),
            (pygame.Rect(525, 570, 130, 48), "Back"),
        ]

    def _ev_config(self, ev, mp):
        if ev.type != pygame.MOUSEBUTTONDOWN or ev.button != 1:
            return
        for i in range(self.num_p):
            if self._cfg_type_rect(i).collidepoint(mp):
                self._play(self.snd_click)
                if self.game_mode == MODE_SINGLE and i == 0:
                    self.cfg_type[i] = (self.cfg_type[i] + 1) % len(AI_TYPES)
                elif self.game_mode == MODE_SINGLE and i > 0:
                    cur_type = AI_TYPES[self.cfg_type[i]]
                    if cur_type in AI_TYPES_SP:
                        idx = AI_TYPES_SP.index(cur_type)
                        next_idx = (idx + 1) % len(AI_TYPES_SP)
                        self.cfg_type[i] = AI_TYPES.index(AI_TYPES_SP[next_idx])
                    else:
                        self.cfg_type[i] = AI_TYPES.index(AI_TYPES_SP[0])
                elif self.game_mode == MODE_MULTI:
                    pass
                else:
                    self.cfg_type[i] = (self.cfg_type[i] + 1) % len(AI_TYPES)

            tp = AI_TYPES[self.cfg_type[i]]
            if tp == "MCTS" and self._cfg_param_rect(i).collidepoint(mp):
                self._play(self.snd_click)
                self.cfg_mcts[i] = (self.cfg_mcts[i] + 1) % len(MCTS_OPTIONS)
            if tp == "Minimax" and self._cfg_param_rect(i).collidepoint(mp):
                self._play(self.snd_click)
                self.cfg_mm[i] = (self.cfg_mm[i] + 1) % len(MINIMAX_DEPTHS)

        for rect, label in self._cfg_btns():
            if rect.collidepoint(mp):
                self._play(self.snd_click)
                if label == "Start Game":
                    self._start_game()
                elif label == "Back":
                    self.state = "modeselect"


    def _ev_play(self, ev, mp):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.state = "paused"
            return
        if self.anim or not self._is_human():
            return
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            col = self._col_from_x(mp[0])
            if col >= 0 and self.board.is_valid(col):
                self._play(self.snd_drop)
                self._start_anim(col, self.cur)


    def _pause_btns(self):
        cx = SCREEN_WIDTH // 2
        w, h = 230, 48
        y0 = 310
        return [
            (pygame.Rect(cx - w // 2, y0, w, h), "Resume"),
            (pygame.Rect(cx - w // 2, y0 + 62, w, h), "Save & Quit"),
            (pygame.Rect(cx - w // 2, y0 + 124, w, h), "Quit to Menu"),
        ]

    def _ev_pause(self, ev, mp):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.state = "playing"
            return
        if ev.type != pygame.MOUSEBUTTONDOWN or ev.button != 1:
            return
        for rect, label in self._pause_btns():
            if rect.collidepoint(mp):
                self._play(self.snd_click)
                if label == "Resume":
                    self.state = "playing"
                elif label == "Save & Quit":
                    self._save_game()
                    self.state = "menu"
                elif label == "Quit to Menu":
                    self.state = "menu"


    def _over_btns(self):
        cx = SCREEN_WIDTH // 2
        w, h, gap = 180, 48, 20
        # Adjust Y position based on number of players
        btn_y = 350 + self.num_p * 50
        return [
            (pygame.Rect(cx - w - gap // 2, btn_y, w, h), "Play Again"),
            (pygame.Rect(cx + gap // 2, btn_y, w, h), "Main Menu"),
        ]

    def _ev_over(self, ev, mp):
        if ev.type != pygame.MOUSEBUTTONDOWN or ev.button != 1:
            return
        for rect, label in self._over_btns():
            if rect.collidepoint(mp):
                self._play(self.snd_click)
                if label == "Play Again":
                    self.state = "config"
                elif label == "Main Menu":
                    self.state = "menu"

    def _update(self, mp):
        """Advance frame timer and playing-state logic."""
        self._tick += 1
        self._online_update()
        if self.state == "playing":
            self._update_play(mp)
        elif self.state == "playing_online":
            self._update_play_online(mp)
        elif self.state == "gameover" or self.state == "online_gameover":
            self.flash_t += 1

    def _update_play_online(self, mp):
        """Advance drop animation for online play; server applies authoritative move."""
        if not self.anim:
            return
        self.anim_speed += DROP_ACCEL
        self.anim_y += self.anim_speed
        if self.anim_bounce > 0:
            self.anim_bounce -= 1
            self.anim_bounce_dy *= -0.4
            self.anim_y = self.anim_target + self.anim_bounce_dy
            if abs(self.anim_bounce_dy) < 0.5:
                self.anim_bounce = 0
                self.anim_y = self.anim_target
        if self.anim_y >= self.anim_target and self.anim_bounce == 0:
            if self.anim_speed > 5:
                self.anim_bounce = 6
                self.anim_bounce_dy = -self.anim_speed * 0.2
                self.anim_y = self.anim_target
                self.anim_speed = 0
            else:
                self.anim_y = self.anim_target
                self.anim = False

    def _update_play(self, mp):
        """Drop animation, win/draw checks, hover column, AI moves."""
        if self.anim:
            self.anim_speed += DROP_ACCEL
            self.anim_y += self.anim_speed

            if self.anim_bounce > 0:
                self.anim_bounce -= 1
                self.anim_bounce_dy *= -0.4
                self.anim_y = self.anim_target + self.anim_bounce_dy
                if abs(self.anim_bounce_dy) < 0.5:
                    self.anim_bounce = 0
                    self.anim_y = self.anim_target

            if self.anim_y >= self.anim_target and self.anim_bounce == 0:
                if self.anim_speed > 5:
                    self.anim_bounce = 6
                    self.anim_bounce_dy = -self.anim_speed * 0.2
                    self.anim_y = self.anim_target
                    self.anim_speed = 0
                else:
                    self.anim_y = self.anim_target
                    self.anim = False
                    row = self.board.drop(self.anim_col, self.anim_p)
                    
                    # Update scores after each move
                    self.scores = self.board.calculate_scores(self.num_p)
                    
                    # Check for Sudden Victory (2+ Connect 4 lines)
                    if self.board.check_sudden_victory(self.anim_p):
                        self.winner = self.anim_p
                        self.win_cells = self.board.winning_cells_at(row, self.anim_col)
                        self.win_reason = "sudden_victory"
                        self.state = "gameover"
                        self.flash_t = 0
                        self._play(self.snd_win)
                        return
                    
                    # Check for regular Connect 4 win
                    w = self.board.check_win_at(row, self.anim_col)
                    if w:
                        self.winner = w
                        self.win_cells = self.board.winning_cells_at(row, self.anim_col)
                        self.win_reason = "connect4"
                        self.state = "gameover"
                        self.flash_t = 0
                        self._play(self.snd_win)
                        return
                    
                    # Check if board is full - determine winner by score
                    if self.board.is_full():
                        winner, scores, tie_info = self.board.determine_winner_by_score(self.num_p)
                        self.scores = scores
                        self.winner = winner
                        self.win_cells = []
                        self.win_reason = "board_full" if winner else "tie"
                        self.state = "gameover"
                        self.flash_t = 0
                        if winner:
                            self._play(self.snd_win)
                        return
                    
                    self.cur = self.cur % self.num_p + 1
                    self.ai_wait = 0
            return

        if self._is_human():
            self.hcol = self._col_from_x(mp[0])
        else:
            self.hcol = -1

        if not self._is_human():
            self.ai_wait += 1
            if self.ai_wait >= 8:
                ai = self.ais[self.cur - 1]
                if ai:
                    mv = ai.get_move(self.board, self.cur, self.num_p)
                    if mv >= 0:
                        self._play(self.snd_drop)
                        self._start_anim(mv, self.cur)
                self.ai_wait = 0

    def _draw(self, mp):
        """Clear with background and dispatch draw by *self.state*."""
        self.screen.blit(self.bg, (0, 0))
        if self._online_draw(mp):
            return
        if self.state == "paused_online":
            self._dr_paused_online(mp)
            return
        {"menu": self._dr_menu, "modeselect": self._dr_modeselect,
         "howtoplay": self._dr_howtoplay, "config": self._dr_config,
         "playing": self._dr_game, "paused": self._dr_paused,
         "gameover": self._dr_over}.get(self.state, lambda m: None)(mp)


    def _dr_menu(self, mp):
        self._draw_top_bar()

        ty = 180 + math.sin(self._tick * 0.025) * 3
        self._shadow_text(self.f_title, TITLE, SCREEN_WIDTH // 2, ty, TEXT_COLOR)

        for i, p in enumerate((1, 2, 3)):
            x = SCREEN_WIDTH // 2 + (i - 1) * 55
            bob = math.sin(self._tick * 0.03 + i * 1.2) * 2
            self.screen.blit(self.mini_discs[p],
                             self.mini_discs[p].get_rect(center=(x, 250 + bob)))

        t = self.f_sm.render("A strategic board game", True, TEXT_DIM)
        self.screen.blit(t, t.get_rect(center=(SCREEN_WIDTH // 2, 295)))

        self._draw_divider(330)

        for rect, label, ok in self._menu_btns():
            self._draw_button(rect, label, mp, ok)

    def _draw_htp_scrollbar(self, mp):
        """Draw scrollbar track + thumb with hover highlight."""
        track, thumb = self._htp_scrollbar_rects()
        max_scroll = self._htp_max_scroll()
        if max_scroll <= 0:
            return

        track_surf = pygame.Surface((track.w, track.h), pygame.SRCALPHA)
        track_surf.fill((0, 0, 0, 0))
        pygame.draw.rect(track_surf, (*CREAM_DARK[:3], 120), (0, 0, track.w, track.h), border_radius=5)
        self.screen.blit(track_surf, (track.x, track.y))

        hovered = thumb.collidepoint(mp) or self._htp_drag
        thumb_col = BTN_HOVER if hovered else BTN_NORMAL
        pygame.draw.rect(self.screen, thumb_col, thumb, border_radius=5)

        highlight_rect = pygame.Rect(thumb.x + 2, thumb.y + 4, 2, thumb.h - 8)
        hl_surf = pygame.Surface((highlight_rect.w, highlight_rect.h), pygame.SRCALPHA)
        hl_surf.fill((*WHITE[:3], 80))
        self.screen.blit(hl_surf, (highlight_rect.x, highlight_rect.y))


    def _dr_howtoplay(self, mp):
        self._draw_top_bar()
        self._shadow_text(self.f_lg, "HOW TO PLAY", SCREEN_WIDTH // 2, 50, TEXT_COLOR)
        self._draw_divider(80)

        panel = pygame.Rect(100, 100, SCREEN_WIDTH - 200, 550)
        self._draw_panel(panel)

        inner = self._htp_inner_rect()
        rules = self._htp_rules()
        max_scroll = self._htp_max_scroll()
        self._htp_scroll = max(0, min(self._htp_scroll, max_scroll))

        prev_clip = self.screen.get_clip()
        self.screen.set_clip(inner)
        y = inner.y + 5 - self._htp_scroll
        for section_title, lines in rules:
            if y > inner.bottom:
                break
            st = self.f_med.render(section_title, True, TEXT_COLOR)
            self.screen.blit(st, (inner.x, y))
            y += 34
            for line in lines:
                if y > inner.bottom:
                    break
                lt = self.f_body.render(line, True, TEXT_DIM)
                self.screen.blit(lt, (inner.x + 10, y))
                y += 24
            y += 14
        self.screen.set_clip(prev_clip)
        self._draw_htp_scrollbar(mp)

        self._draw_button(self._htp_back_btn(), "Back", mp)


    def _dr_modeselect(self, mp):
        self._draw_top_bar()
        self._shadow_text(self.f_lg, "SELECT MODE", SCREEN_WIDTH // 2, 100, TEXT_COLOR)

        t = self.f_sm.render("Choose your game mode", True, TEXT_DIM)
        self.screen.blit(t, t.get_rect(center=(SCREEN_WIDTH // 2, 148)))

        self._draw_divider(185)

        desc_y = 218
        if self.game_mode == MODE_SINGLE:
            desc = "Configure Player 1 as Human or AI — add 1 or 2 AI opponents"
        else:
            desc = "Play with friends — add 1 or 2 players"
        dt = self.f_sm.render(desc, True, TEXT_DIM)
        self.screen.blit(dt, dt.get_rect(center=(SCREEN_WIDTH // 2, desc_y)))

        for rect, label in self._mode_btns():
            is_selected = ((label == "SinglePlayer" and self.game_mode == MODE_SINGLE) or
                           (label == "Multiplayer" and self.game_mode == MODE_MULTI))
            if label == "Back":
                self._draw_button(rect, label, mp, mode_select_style=True)
            else:
                self._draw_button(rect, label, mp, selected=is_selected,
                                  mode_select_style=True)

        if self.game_mode == MODE_SINGLE:
            for rect, label, count in self._mode_sub_btns_sp():
                is_sel = (self.sp_ai_count == count)
                self._draw_button(rect, label, mp, selected=is_sel,
                                  mode_select_style=True)
        elif self.game_mode == MODE_MULTI:
            for rect, label, count in self._mode_sub_btns_mp():
                is_sel = (self.mp_extra == count)
                self._draw_button(rect, label, mp, selected=is_sel,
                                  mode_select_style=True)


    def _dr_config(self, mp):
        self._draw_top_bar()

        mode_label = "SINGLEPLAYER" if self.game_mode == MODE_SINGLE else "MULTIPLAYER"
        self._shadow_text(self.f_lg, mode_label, SCREEN_WIDTH // 2, 68, TEXT_COLOR)
        t = self.f_sm.render("Click options to cycle through choices", True, TEXT_DIM)
        self.screen.blit(t, t.get_rect(center=(SCREEN_WIDTH // 2, 118)))

        self._draw_divider(150, 300)

        for i in range(self.num_p):
            p = i + 1
            y = 230 + i * 95

            badge = pygame.Rect(175, y - 2, 220, 44)
            badge_surf = pygame.Surface((badge.w, badge.h), pygame.SRCALPHA)
            pygame.draw.rect(badge_surf, (*PLAYER_COLORS[p], 18),
                             (0, 0, badge.w, badge.h), border_radius=8)
            self.screen.blit(badge_surf, badge.topleft)
            pygame.draw.rect(self.screen, PLAYER_COLORS[p], badge, 1, border_radius=8)

            self.screen.blit(self.mini_discs[p],
                             self.mini_discs[p].get_rect(center=(195, y + 20)))
            lbl = self.f_sub.render(f"Player {p}", True,
                                    PLAYER_COLORS[p])
            self.screen.blit(lbl, (220, y + 8))

            self._draw_selector(self._cfg_type_rect(i),
                                AI_TYPES[self.cfg_type[i]], mp)

            tp = AI_TYPES[self.cfg_type[i]]
            if tp == "MCTS":
                self._draw_selector(
                    self._cfg_param_rect(i),
                    f"Sims: {MCTS_OPTIONS[self.cfg_mcts[i]]}", mp)
            elif tp == "Minimax":
                self._draw_selector(
                    self._cfg_param_rect(i),
                    f"Depth: {MINIMAX_DEPTHS[self.cfg_mm[i]]}", mp)

        for rect, label in self._cfg_btns():
            self._draw_button(rect, label, mp)


    def _dr_game(self, mp):
        self._draw_turn_indicator()
        self._draw_board()
        self._draw_scoreboard()
        if self.hcol >= 0 and not self.anim:
            self._draw_hover()
        if self.anim:
            self._draw_anim_disc()
        if not self._is_human() and not self.anim:
            pulse = 0.5 + 0.5 * math.sin(self._tick * 0.08)
            alpha = int(100 + 155 * pulse)
            t = self.f_sm.render("AI is thinking\u2026", True, TEXT_DIM)
            t.set_alpha(alpha)
            self.screen.blit(t, t.get_rect(center=(SCREEN_WIDTH // 2, 42)))
        t = self.f_sm.render("ESC to pause", True, TEXT_MUTED)
        self.screen.blit(t, (14, SCREEN_HEIGHT - 40))

    def _dr_paused(self, mp):
        self._dr_game(mp)
        ov = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        ov.fill((250, 245, 235, 200))
        self.screen.blit(ov, (0, 0))

        pw, ph = 340, 280
        panel_rect = pygame.Rect(SCREEN_WIDTH // 2 - pw // 2, 220, pw, ph)
        self._draw_panel(panel_rect, "PAUSED")

        for rect, label in self._pause_btns():
            self._draw_button(rect, label, mp)

    def _dr_over(self, mp, draw_buttons=True):
        self._draw_turn_indicator()
        self._draw_board(highlight=True)
        ov = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        ov.fill((250, 245, 235, 180))
        self.screen.blit(ov, (0, 0))
        
        # Main result message
        if self.winner:
            msg = f"{PLAYER_NAMES[self.winner]} Wins!"
            col = PLAYER_COLORS[self.winner]
        else:
            msg = "It's a Draw!"
            col = TEXT_COLOR
        self._shadow_text(self.f_xl, msg, SCREEN_WIDTH // 2, 200, col)
        
        # Win reason subtitle
        reason_text = ""
        if self.win_reason == "sudden_victory":
            reason_text = "Sudden Victory! (2+ Connect 4 lines)"
        elif self.win_reason == "connect4":
            reason_text = "Connect 4!"
        elif self.win_reason == "board_full":
            reason_text = "Board Full - Highest Score Wins!"
        elif self.win_reason == "tie":
            reason_text = "Board Full - Complete Tie!"
        
        if reason_text:
            rt = self.f_sub.render(reason_text, True, TEXT_DIM)
            self.screen.blit(rt, rt.get_rect(center=(SCREEN_WIDTH // 2, 248)))
        
        # Final scores panel
        self._draw_final_scores()
        
        if draw_buttons:
            for rect, label in self._over_btns():
                self._draw_button(rect, label, mp)

    def _draw_final_scores(self):
        """Draw final scores panel in game over screen."""
        # Panel dimensions
        panel_w = 400
        panel_h = 50 + self.num_p * 50
        panel_x = (SCREEN_WIDTH - panel_w) // 2
        panel_y = 280
        
        panel_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)
        
        # Shadow
        shadow = pygame.Surface((panel_w + 6, panel_h + 6), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 25), (3, 4, panel_w, panel_h), border_radius=12)
        self.screen.blit(shadow, (panel_x - 3, panel_y - 2))
        
        # Panel background
        pygame.draw.rect(self.screen, CREAM, panel_rect, border_radius=12)
        pygame.draw.rect(self.screen, PANEL_BORDER, panel_rect, 2, border_radius=12)
        
        # Title
        title = self.f_sub.render("FINAL SCORES", True, TEXT_COLOR)
        self.screen.blit(title, title.get_rect(center=(panel_x + panel_w // 2, panel_y + 22)))
        
        # Divider
        pygame.draw.line(self.screen, CREAM_DARK, 
                        (panel_x + 15, panel_y + 42), 
                        (panel_x + panel_w - 15, panel_y + 42), 1)
        
        # Sort players by score descending
        sorted_players = sorted(range(1, self.num_p + 1), 
                               key=lambda p: self.scores.get(p, 0), 
                               reverse=True)
        
        for idx, p in enumerate(sorted_players):
            row_y = panel_y + 55 + idx * 50
            
            # Rank indicator
            rank = idx + 1
            rank_colors = {1: (255, 215, 0), 2: (192, 192, 192), 3: (205, 127, 50)}
            rank_col = rank_colors.get(rank, TEXT_DIM)
            rank_text = self.f_sm.render(f"#{rank}", True, rank_col)
            self.screen.blit(rank_text, (panel_x + 20, row_y + 8))
            
            # Mini disc
            disc = self.mini_discs[p]
            self.screen.blit(disc, disc.get_rect(center=(panel_x + 70, row_y + 16)))
            
            # Player name
            name_text = self.f_sub.render(PLAYER_NAMES[p], True, PLAYER_COLORS[p])
            self.screen.blit(name_text, (panel_x + 95, row_y + 4))
            
            # Score
            score = self.scores.get(p, 0)
            score_text = self.f_med.render(str(score), True, PLAYER_COLORS[p])
            self.screen.blit(score_text, score_text.get_rect(right=panel_x + panel_w - 20, centery=row_y + 16))
            
            # Highlight winner
            if p == self.winner:
                hl_rect = pygame.Rect(panel_x + 8, row_y - 6, panel_w - 16, 44)
                hl_surf = pygame.Surface((hl_rect.w, hl_rect.h), pygame.SRCALPHA)
                pygame.draw.rect(hl_surf, (*PLAYER_COLORS[p], 30), (0, 0, hl_rect.w, hl_rect.h), border_radius=8)
                self.screen.blit(hl_surf, hl_rect.topleft)

    def _draw_board(self, highlight=False):
        """Bitmap board, shadows, and placed pieces (optional win glow)."""
        bx, by = BOARD_BLIT_X, BOARD_BLIT_Y
        bw, bh = BOARD_BLIT_W, BOARD_BLIT_H

        for i in range(3):
            shadow = pygame.Surface((bw + 10, bh + 10), pygame.SRCALPHA)
            sa = 18 - i * 5
            off = 4 + i
            pygame.draw.rect(shadow, (0, 0, 0, sa),
                             (off, off + 1, bw, bh), border_radius=16)
            self.screen.blit(shadow, (bx - 5, by - 4))

        self.screen.blit(self._board_scaled, (bx, by))

        for r in range(ROWS):
            for c in range(COLS):
                cx, cy = _cell_center(r, c)
                p = self.board.grid[r][c] if self.board else 0
                if p > 0:
                    if highlight and (r, c) in self.win_cells:
                        pulse = 0.5 + 0.5 * math.sin(self.flash_t * 0.12)
                        glow = pygame.Surface((CELL_SIZE, CELL_SIZE),
                                              pygame.SRCALPHA)
                        ga = int(100 * pulse)
                        pygame.draw.circle(glow, (*PLAYER_LIGHT[p], ga),
                                           (CELL_CENTER_OFF, CELL_CENTER_OFF),
                                           PIECE_RADIUS + 6)
                        self.screen.blit(glow,
                                         (cx - CELL_CENTER_OFF,
                                          cy - CELL_CENTER_OFF))
                    self.screen.blit(self.discs[p],
                                     self.discs[p].get_rect(center=(cx, cy)))

    def _draw_hover(self):
        """Column highlight and ghost piece for human aiming."""
        if self.hcol < 0 or not self.board or not self.board.is_valid(self.hcol):
            return
        cx = BOARD_X + self.hcol * CELL_STRIDE + CELL_CENTER_OFF 

        hl = pygame.Surface((CELL_STRIDE, BOARD_GRID_PX_H), pygame.SRCALPHA)
        hl.fill((255, 255, 255, 20))
        hl_x = (BOARD_X + self.hcol * CELL_STRIDE - 12)
        self.screen.blit(hl, (hl_x, BOARD_Y))

        bob = math.sin(self._tick * HOVER_BOB_SPEED) * HOVER_BOB_AMP
        ghost = self.discs[self.cur].copy()
        ghost.set_alpha(140)
        gy = BOARD_Y - CELL_CENTER_OFF - 8 + bob
        self.screen.blit(ghost, ghost.get_rect(center=(cx, gy)))

    def _draw_anim_disc(self):
        """Falling piece during drop animation."""
        cx = BOARD_X + self.anim_col * CELL_STRIDE + CELL_CENTER_OFF
        self.screen.blit(self.discs[self.anim_p],
                         self.discs[self.anim_p].get_rect(
                             center=(cx, int(self.anim_y))))

    def _draw_turn_indicator(self):
        """Mini disc and label above the board."""
        if not self.board:
            return
        ds = self.mini_discs[self.cur]
        name = PLAYER_NAMES[self.cur]
        tp = self.ptypes[self.cur - 1]
        label = f"{name}'s Turn" if tp == "Human" else f"{name}'s Turn ({tp})"
        t = self.f_med.render(label, True, PLAYER_COLORS[self.cur])
        tw, dw = t.get_width(), ds.get_width()
        sx = (SCREEN_WIDTH - dw - 10 - tw) // 2
        self.screen.blit(ds, ds.get_rect(center=(sx + dw // 2, 78)))
        self.screen.blit(t, (sx + dw + 10, 78 - t.get_height() // 2))

    def _draw_scoreboard(self):
        """Draw scoreboard panel showing all players' scores."""
        if not self.board:
            return
        
        # Scoreboard position - right side of the board
        sb_x = BOARD_BLIT_X + BOARD_BLIT_W + 20
        sb_y = BOARD_BLIT_Y + 10
        sb_w = SCREEN_WIDTH - sb_x - 20
        sb_h = 60 + self.num_p * 58
        
        # Draw panel background
        panel_rect = pygame.Rect(sb_x, sb_y, sb_w, sb_h)
        
        # Shadow
        shadow = pygame.Surface((sb_w + 6, sb_h + 6), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 20), (3, 4, sb_w, sb_h), border_radius=12)
        self.screen.blit(shadow, (sb_x - 3, sb_y - 2))
        
        # Panel
        pygame.draw.rect(self.screen, CREAM, panel_rect, border_radius=12)
        pygame.draw.rect(self.screen, PANEL_BORDER, panel_rect, 2, border_radius=12)
        
        # Title
        title = self.f_sub.render("SCORES", True, TEXT_COLOR)
        self.screen.blit(title, title.get_rect(center=(sb_x + sb_w // 2, sb_y + 24)))
        
        # Divider
        div_y = sb_y + 44
        pygame.draw.line(self.screen, CREAM_DARK, (sb_x + 10, div_y), (sb_x + sb_w - 10, div_y), 1)
        
        # Player scores
        for i in range(self.num_p):
            p = i + 1
            row_y = sb_y + 58 + i * 58
            
            # Mini disc
            disc = self.mini_discs[p]
            self.screen.blit(disc, disc.get_rect(center=(sb_x + 28, row_y + 18)))
            
            # Score
            score = self.scores.get(p, 0)
            score_text = self.f_med.render(str(score), True, PLAYER_COLORS[p])
            self.screen.blit(score_text, score_text.get_rect(right=sb_x + sb_w - 15, centery=row_y + 18))
            
            # Highlight current player
            if p == self.cur:
                highlight_rect = pygame.Rect(sb_x + 4, row_y - 4, sb_w - 8, 48)
                hl_surf = pygame.Surface((highlight_rect.w, highlight_rect.h), pygame.SRCALPHA)
                pygame.draw.rect(hl_surf, (*PLAYER_COLORS[p], 25), (0, 0, highlight_rect.w, highlight_rect.h), border_radius=8)
                self.screen.blit(hl_surf, highlight_rect.topleft)

    def _is_human(self):
        """True if the current player is human-controlled."""
        return self.ptypes[self.cur - 1] == "Human"

    def _col_from_x(self, x):
        """Column index from mouse x, or -1."""
        if BOARD_X <= x < BOARD_X + BOARD_GRID_PX_W:
            return (x - BOARD_X) // CELL_STRIDE
        return -1

    def _start_anim(self, col, player):
        """Begin animating a disc drop into *col* for *player*."""
        row = self.board.drop_row(col)
        if row < 0:
            return
        self.anim = True
        self.anim_col = col
        self.anim_p = player
        self.anim_row = row
        self.anim_y = float(BOARD_Y - CELL_CENTER_OFF - 10)
        self.anim_start_y = self.anim_y
        self.anim_speed = DROP_SPEED * 0.3 
        self.anim_bounce = 0
        self.anim_bounce_dy = 0.0
        _, ty = _cell_center(row, col)
        self.anim_target = ty

    def _start_game(self):
        """Reset board and AI from config; enter playing state."""
        self.board = Board()
        self.cur = 1
        self.winner = 0
        self.win_cells = []
        self.win_reason = ""
        self.scores = {p: 0 for p in range(1, self.num_p + 1)}
        self.anim = False
        self.ai_wait = 0
        self.hcol = -1
        self.ptypes = [AI_TYPES[self.cfg_type[i]] for i in range(self.num_p)]
        self.ais = [None] * self.num_p
        for i in range(self.num_p):
            tp = self.ptypes[i]
            if tp == "Random":
                self.ais[i] = RandomAI()
            elif tp == "MCTS":
                self.ais[i] = MCTSAI(MCTS_OPTIONS[self.cfg_mcts[i]])
            elif tp == "Minimax":
                self.ais[i] = MinimaxAI(MINIMAX_DEPTHS[self.cfg_mm[i]])
        self.state = "playing"


    def _save_game(self):
        """Persist current match to SAVE_FILE."""
        data = {
            "board": self.board.to_list(),
            "current": self.cur,
            "num_p": self.num_p,
            "ptypes": self.ptypes,
            "cfg_type": self.cfg_type,
            "cfg_mcts": self.cfg_mcts,
            "cfg_mm": self.cfg_mm,
            "game_mode": self.game_mode,
        }
        try:
            with open(SAVE_FILE, "w") as f:
                json.dump(data, f)
            self.has_save = True
        except OSError:
            pass

    def _load_game(self):
        """Restore match from SAVE_FILE or clear has_save on error."""
        try:
            with open(SAVE_FILE, "r") as f:
                data = json.load(f)
            self.board = Board.from_list(data["board"])
            self.cur = data["current"]
            self.num_p = data.get("num_p", 3)
            self.ptypes = data["ptypes"]
            self.cfg_type = data.get("cfg_type", [0, 0, 0])
            self.cfg_mcts = data.get("cfg_mcts", [2, 2, 2])
            self.cfg_mm = data.get("cfg_mm", [2, 2, 2])
            self.game_mode = data.get("game_mode", MODE_MULTI)
            self.ais = [None] * self.num_p
            for i in range(self.num_p):
                tp = self.ptypes[i]
                if tp == "Random":
                    self.ais[i] = RandomAI()
                elif tp == "MCTS":
                    self.ais[i] = MCTSAI(MCTS_OPTIONS[self.cfg_mcts[i]])
                elif tp == "Minimax":
                    self.ais[i] = MinimaxAI(MINIMAX_DEPTHS[self.cfg_mm[i]])
            self.winner = 0
            self.win_cells = []
            self.win_reason = ""
            # Recalculate scores from current board state
            self.scores = self.board.calculate_scores(self.num_p)
            self.anim = False
            self.ai_wait = 0
            self.hcol = -1
            self.state = "playing"
        except Exception:
            self.has_save = False
