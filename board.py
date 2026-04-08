"""Grid logic, O(1) drops, win detection, and scoring for 8×7 three-player Connect Four."""

import random as _rng
from constants import (ROWS, COLS, SCORE_CONNECT_2, SCORE_CONNECT_3, 
                       SCORE_CONNECT_4, SCORE_COMBO_MULTIPLIER, CENTER_COLS)

_zrng = _rng.Random(314159)
_ZOBRIST = [[[_zrng.getrandbits(64) for _ in range(4)]
             for _ in range(COLS)] for _ in range(ROWS)]


class Board:
    """Game grid, move validation, win checks, and Zobrist hash for transpositions."""

    __slots__ = ['grid', '_heights', '_hash', '_move_count']

    _DIRS = ((0, 1), (1, 0), (1, 1), (1, -1))

    def __init__(self):
        self.grid = [[0] * COLS for _ in range(ROWS)]
        self._heights = [ROWS - 1] * COLS
        self._hash = 0
        self._move_count = 0

    def copy(self):
        """Independent copy of the board state."""
        b = Board.__new__(Board)
        b.grid = [row[:] for row in self.grid]
        b._heights = self._heights[:]
        b._hash = self._hash
        b._move_count = self._move_count
        return b

    def is_valid(self, col):
        """True if *col* can accept a piece."""
        return 0 <= col < COLS and self._heights[col] >= 0

    def valid_moves(self):
        """List of columns that are not full."""
        return [c for c in range(COLS) if self._heights[c] >= 0]

    def drop_row(self, col):
        """Row index where a piece would land, or -1 if column full."""
        return self._heights[col]

    def drop(self, col, player):
        """Place *player* in *col*; return landing row or -1 if invalid."""
        r = self._heights[col]
        if r >= 0:
            self.grid[r][col] = player
            self._heights[col] = r - 1
            self._hash ^= _ZOBRIST[r][col][player]
            self._move_count += 1
        return r

    def undo(self, col):
        """Remove top piece from *col* (inverse of drop)."""
        r = self._heights[col] + 1
        if r < ROWS:
            p = self.grid[r][col]
            self._hash ^= _ZOBRIST[r][col][p]
            self.grid[r][col] = 0
            self._heights[col] = r
            self._move_count -= 1

    def check_win_at(self, r, c):
        """Winning player if piece at (r,c) completes four in a row, else 0."""
        p = self.grid[r][c]
        if p == 0:
            return 0
        g = self.grid
        for dr, dc in Board._DIRS:
            count = 1
            nr, nc = r + dr, c + dc
            while 0 <= nr < ROWS and 0 <= nc < COLS and g[nr][nc] == p:
                count += 1
                if count >= 4:
                    return p
                nr += dr
                nc += dc
            nr, nc = r - dr, c - dc
            while 0 <= nr < ROWS and 0 <= nc < COLS and g[nr][nc] == p:
                count += 1
                if count >= 4:
                    return p
                nr -= dr
                nc -= dc
        return 0

    def winning_cells_at(self, r, c):
        """Four cells forming a win through (r,c), or empty list."""
        p = self.grid[r][c]
        if p == 0:
            return []
        g = self.grid
        for dr, dc in Board._DIRS:
            cells = [(r, c)]
            nr, nc = r + dr, c + dc
            while 0 <= nr < ROWS and 0 <= nc < COLS and g[nr][nc] == p:
                cells.append((nr, nc))
                nr += dr
                nc += dc
            nr, nc = r - dr, c - dc
            while 0 <= nr < ROWS and 0 <= nc < COLS and g[nr][nc] == p:
                cells.append((nr, nc))
                nr -= dr
                nc -= dc
            if len(cells) >= 4:
                return cells[:4]
        return []

    def winner(self):
        """Any winning player on the full board (O(rows×cols)); prefer check_win_at after moves."""
        for r in range(ROWS):
            for c in range(COLS):
                p = self.grid[r][c]
                if p and self._line(r, c, p):
                    return p
        return 0

    def _line(self, r, c, p):
        for dr, dc in self._DIRS:
            ok = True
            for i in range(1, 4):
                nr, nc = r + dr * i, c + dc * i
                if not (0 <= nr < ROWS and 0 <= nc < COLS) or self.grid[nr][nc] != p:
                    ok = False
                    break
            if ok:
                return True
        return False

    def winning_cells(self):
        """Coordinates of one winning line of four, or empty."""
        for r in range(ROWS):
            for c in range(COLS):
                p = self.grid[r][c]
                if not p:
                    continue
                for dr, dc in self._DIRS:
                    cells = [(r + dr * i, c + dc * i) for i in range(4)]
                    if all(
                        0 <= cr < ROWS and 0 <= cc < COLS and self.grid[cr][cc] == p
                        for cr, cc in cells
                    ):
                        return cells
        return []

    def is_full(self):
        """No empty cells remain."""
        return self._move_count >= ROWS * COLS

    def is_terminal(self):
        """Win or draw."""
        return self.winner() != 0 or self.is_full()

    def to_list(self):
        """Grid as list of rows (for JSON)."""
        return [row[:] for row in self.grid]

    @classmethod
    def from_list(cls, data):
        """Rebuild board, heights, hash, and move count from saved rows."""
        b = cls()
        b.grid = [row[:] for row in data]
        b._move_count = 0
        b._hash = 0
        for c in range(COLS):
            b._heights[c] = -1
            for r in range(ROWS):
                if data[r][c] != 0:
                    b._move_count += 1
                    b._hash ^= _ZOBRIST[r][c][data[r][c]]
            for r in range(ROWS - 1, -1, -1):
                if data[r][c] == 0:
                    b._heights[c] = r
                    break
        return b

    def _get_all_lines(self):
        """Generate all possible lines (horizontal, vertical, diagonal) on the board."""
        lines = []
        # Horizontal lines
        for r in range(ROWS):
            for c in range(COLS - 3):
                lines.append([(r, c + i) for i in range(4)])
        # Vertical lines
        for r in range(ROWS - 3):
            for c in range(COLS):
                lines.append([(r + i, c) for i in range(4)])
        # Diagonal down-right
        for r in range(ROWS - 3):
            for c in range(COLS - 3):
                lines.append([(r + i, c + i) for i in range(4)])
        # Diagonal down-left
        for r in range(ROWS - 3):
            for c in range(3, COLS):
                lines.append([(r + i, c - i) for i in range(4)])
        return lines

    def _count_sequences_for_player(self, player):
        """
        Count sequences of 2, 3, and 4 for a player.
        Only counts the longest sequence within each cluster (no stacking).
        Returns dict: {2: count, 3: count, 4: count, 'connect4_lines': list of lines}
        """
        counted_cells = set()
        result = {2: 0, 3: 0, 4: 0, 'connect4_lines': []}
        
        g = self.grid
        
        # Scan all directions for each cell
        for r in range(ROWS):
            for c in range(COLS):
                if g[r][c] != player:
                    continue
                    
                for dr, dc in Board._DIRS:
                    # Check if this is the start of a new sequence
                    pr, pc = r - dr, c - dc
                    if 0 <= pr < ROWS and 0 <= pc < COLS and g[pr][pc] == player:
                        continue  # Not the start
                    
                    # Count the sequence length
                    length = 0
                    cells = []
                    nr, nc = r, c
                    while 0 <= nr < ROWS and 0 <= nc < COLS and g[nr][nc] == player:
                        cells.append((nr, nc))
                        length += 1
                        nr += dr
                        nc += dc
                    
                    # Only count if length >= 2 and cells not already counted for longer seq
                    if length >= 2:
                        # Create a unique key for this line direction
                        line_key = (tuple(cells), (dr, dc))
                        if line_key not in counted_cells:
                            counted_cells.add(line_key)
                            if length >= 4:
                                result[4] += 1
                                result['connect4_lines'].append(cells[:4])
                            elif length == 3:
                                result[3] += 1
                            elif length == 2:
                                result[2] += 1
        
        return result

    def calculate_scores(self, num_players=3):
        """
        Calculate scores for all players based on their sequences.
        Returns dict: {player_id: score}
        """
        scores = {p: 0 for p in range(1, num_players + 1)}
        
        for player in range(1, num_players + 1):
            seq = self._count_sequences_for_player(player)
            
            # Base scores for sequences
            scores[player] += seq[2] * SCORE_CONNECT_2
            scores[player] += seq[3] * SCORE_CONNECT_3
            scores[player] += seq[4] * SCORE_CONNECT_4
        
        return scores

    def count_connect4_lines(self, player):
        """Count distinct Connect 4 lines for a player."""
        seq = self._count_sequences_for_player(player)
        return seq[4]

    def check_sudden_victory(self, player):
        """Check if player has achieved Sudden Victory (2+ distinct Connect 4 lines)."""
        return self.count_connect4_lines(player) >= 2

    def get_longest_sequence(self, player):
        """Get the length of the longest continuous sequence for a player."""
        g = self.grid
        max_len = 0
        
        for r in range(ROWS):
            for c in range(COLS):
                if g[r][c] != player:
                    continue
                    
                for dr, dc in Board._DIRS:
                    # Check if this is the start
                    pr, pc = r - dr, c - dc
                    if 0 <= pr < ROWS and 0 <= pc < COLS and g[pr][pc] == player:
                        continue
                    
                    length = 0
                    nr, nc = r, c
                    while 0 <= nr < ROWS and 0 <= nc < COLS and g[nr][nc] == player:
                        length += 1
                        nr += dr
                        nc += dc
                    
                    max_len = max(max_len, length)
        
        return max_len

    def count_center_pieces(self, player):
        """Count pieces in center columns for tie-breaker."""
        count = 0
        for r in range(ROWS):
            for c in CENTER_COLS:
                if self.grid[r][c] == player:
                    count += 1
        return count

    def determine_winner_by_score(self, num_players=3):
        """
        Determine winner when board is full.
        Returns (winner_player, scores_dict, tie_info) where:
        - winner_player: 0 for true tie, else winning player id
        - scores_dict: {player: score}
        - tie_info: str explaining how winner was determined
        """
        scores = self.calculate_scores(num_players)
        
        # Find max score
        max_score = max(scores.values())
        top_players = [p for p, s in scores.items() if s == max_score]
        
        if len(top_players) == 1:
            return top_players[0], scores, "highest_score"
        
        # Tie-breaker 1: Longest sequence
        longest = {p: self.get_longest_sequence(p) for p in top_players}
        max_len = max(longest.values())
        top_by_length = [p for p in top_players if longest[p] == max_len]
        
        if len(top_by_length) == 1:
            return top_by_length[0], scores, "longest_sequence"
        
        # Tie-breaker 2: Center control
        center = {p: self.count_center_pieces(p) for p in top_by_length}
        max_center = max(center.values())
        top_by_center = [p for p in top_by_length if center[p] == max_center]
        
        if len(top_by_center) == 1:
            return top_by_center[0], scores, "center_control"
        
        # True tie - return first player (or could be 0 for draw)
        return top_by_center[0], scores, "true_tie"

    def get_sequence_details(self, player):
        """Get detailed sequence info for display."""
        return self._count_sequences_for_player(player)
