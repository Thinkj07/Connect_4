"""Server-authoritative game session: move validation, scoring, AI turns."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from ai import MCTSAI, MinimaxAI, RandomAI
from board import Board
from constants import MCTS_OPTIONS, MINIMAX_DEPTHS
from shared.protocol import GameStateDTO, RoomStatus

from .models import Room


def _slot_order(room: Room) -> list:
    """Return sorted list of (slot, kind, controller) for turn iteration."""
    slots = []
    for p in room.players:
        slots.append((p.slot, "human", p.id))
    for a in room.ai_slots:
        slots.append((a.slot, "ai", a.ai_type))
    slots.sort(key=lambda x: x[0])
    return slots


def _build_ai(ai_type: str, params: dict):
    """Construct an AI from a type name and parameter dict."""
    if ai_type == "Random":
        return RandomAI()
    if ai_type == "MCTS":
        sims = int((params or {}).get("simulations", 1000))
        if sims not in MCTS_OPTIONS:
            sims = min(MCTS_OPTIONS, key=lambda x: abs(x - sims))
        return MCTSAI(sims)
    if ai_type == "Minimax":
        depth = int((params or {}).get("depth", 4))
        if depth not in MINIMAX_DEPTHS:
            depth = max(2, min(6, depth))
        return MinimaxAI(depth)
    return RandomAI()


class GameSession:
    """Authoritative game state for one room; methods return fresh DTO snapshots."""

    def __init__(self, room: Room):
        self.room = room
        self.board = Board()
        self.num_players = room.max_players
        self.current_player = 1
        self.scores: Dict[int, int] = {i: 0 for i in range(1, self.num_players + 1)}
        self.winner: Optional[int] = None
        self.win_reason: str = ""
        self.win_cells: list = []
        self.last_move: Optional[Tuple[int, int]] = None

        self.ais: Dict[int, object] = {}
        self.slot_is_ai: Dict[int, bool] = {}
        self.slot_player_id: Dict[int, str] = {}
        for p in room.players:
            self.slot_is_ai[p.slot] = False
            self.slot_player_id[p.slot] = p.id
        for a in room.ai_slots:
            self.slot_is_ai[a.slot] = True
            self.ais[a.slot] = _build_ai(a.ai_type, a.params)

    # --- queries --------------------------------------------------------------

    def initialize_game(self) -> GameStateDTO:
        self.room.status = RoomStatus.PLAYING
        state = self.get_state()
        self.room.game_state = state
        return state

    def is_ai_turn(self) -> bool:
        return self.slot_is_ai.get(self.current_player, False)

    def is_player_turn(self, player_slot: int) -> bool:
        return (self.current_player == player_slot and
                not self.slot_is_ai.get(player_slot, True))

    def get_player_slot(self, player_id: str) -> Optional[int]:
        for slot, pid in self.slot_player_id.items():
            if pid == player_id:
                return slot
        return None

    def get_state(self) -> GameStateDTO:
        return GameStateDTO(
            board=self.board.to_list(),
            current_player=self.current_player,
            scores={int(k): int(v) for k, v in self.scores.items()},
            winner=self.winner,
            win_reason=self.win_reason,
            last_move=list(self.last_move) if self.last_move else None,
            win_cells=[list(c) for c in self.win_cells],
            status=self.room.status.value,
        )

    # --- move handling --------------------------------------------------------

    def _advance_current(self) -> None:
        self.current_player = self.current_player % self.num_players + 1

    def _finalize_if_over(self, row: int, col: int) -> bool:
        """Apply win detection / score-based outcome; return True if game ended."""
        self.scores = self.board.calculate_scores(self.num_players)
        p = self.board.grid[row][col] if 0 <= row < len(self.board.grid) else 0
        if p and self.board.check_sudden_victory(p):
            self.winner = p
            self.win_reason = "sudden_victory"
            self.win_cells = self.board.winning_cells_at(row, col)
            self.room.status = RoomStatus.FINISHED
            return True

        w = self.board.check_win_at(row, col)
        if w:
            self.winner = w
            self.win_reason = "connect4"
            self.win_cells = self.board.winning_cells_at(row, col)
            self.room.status = RoomStatus.FINISHED
            return True

        if self.board.is_full():
            winner, scores, reason = self.board.determine_winner_by_score(
                self.num_players)
            self.scores = scores
            self.winner = winner or 0
            self.win_reason = "board_full" if winner else "tie"
            self.win_cells = []
            self.room.status = RoomStatus.FINISHED
            return True

        return False

    def make_move(self, player_slot: int, col: int) -> Tuple[bool, GameStateDTO, str]:
        """Validate and apply a move. Returns (ok, state, error_msg)."""
        if self.room.status != RoomStatus.PLAYING:
            return False, self.get_state(), "Game not in progress."
        if player_slot != self.current_player:
            return False, self.get_state(), "Not your turn."
        if not self.board.is_valid(col):
            return False, self.get_state(), "Invalid move."

        row = self.board.drop(col, player_slot)
        if row < 0:
            return False, self.get_state(), "Invalid move."
        self.last_move = (row, col)

        if not self._finalize_if_over(row, col):
            self._advance_current()

        state = self.get_state()
        self.room.game_state = state
        return True, state, ""

    def process_ai_turn(self) -> Tuple[Optional[int], GameStateDTO]:
        """If current player is AI, pick and play a column; return (col, state)."""
        if self.room.status != RoomStatus.PLAYING:
            return None, self.get_state()
        if not self.is_ai_turn():
            return None, self.get_state()
        ai = self.ais.get(self.current_player)
        if ai is None:
            return None, self.get_state()
        col = ai.get_move(self.board, self.current_player, self.num_players)
        if col < 0 or not self.board.is_valid(col):
            return None, self.get_state()

        slot = self.current_player
        row = self.board.drop(col, slot)
        self.last_move = (row, col)

        if not self._finalize_if_over(row, col):
            self._advance_current()

        state = self.get_state()
        self.room.game_state = state
        return col, state

    def check_game_over(self) -> Tuple[bool, Optional[int], str]:
        return self.room.status == RoomStatus.FINISHED, self.winner, self.win_reason
