# SPECIFICATION UPDATE: SCORING SYSTEM & WIN CONDITION MECHANICS (CONNECT 4 - 3 PLAYERS)

## 1. Design Philosophy

**Core Value:** A sequence of 4 pieces (Connect 4) is the highest achievement. Its score must significantly exceed the total points accumulated from regular small sequences.

**Fairness:** In a 3-player game, being "ganged up on" or blocked is very common. The scoring system compensates players who execute excellent strategy but have their Connect 4 line broken at the last moment by an opponent.

**Win Ratio:** A Connect 4 sequence grants ~1000 points, whereas the maximum possible points from smaller sequences typically fall within the range of 100-300 points.

## 2. Detailed Scoring Matrix

The scoring system will be applied by scanning the entire board at the end of the match (when the board is full or when a player meets the stop condition).

| Action / Condition             | Points       | Explanation                                                                |
| :----------------------------- | :----------- | :------------------------------------------------------------------------- |
| **Connect 2** (Sequence of 2)  | 2 points     | Encourages creating foundational threats.                                   |
| **Connect 3** (Sequence of 3)  | 15 points    | Reward for creating a dangerous board state.                                |
| **Connect 4** (Grand Slam)     | **1000 points** | The decisive milestone for victory.                                         |
| **Block a Connect 3**          | 30 points    | Bonus awarded for placing a piece that breaks an opponent's existing 3-in-a-row. |
| **Combo** (Multi-line)         | x1.5 points  | Applied if a single piece creates multiple sequences simultaneously (e.g., vertical and diagonal). |

**Note on Calculation:**  
> * Sequence points do **not** stack incrementally (e.g., a Connect 4 does **not** equal Connect 3 points + Connect 2 points).  
> The system will scan and only count points for the **longest sequence** within a specific cluster of pieces.

## 3. End Conditions & Determining the Winner

To prevent the game from resulting in a stalemate at high skill levels, the rules are updated as follows:

**Immediate Termination (Sudden Victory):**  
If a single player creates **two distinct Connect 4 lines** on the board, that player wins immediately, regardless of the other players' current scores.

**Board Exhaustion (Full Board):**  
This is the most common scenario at high-level play. When no empty cells remain:
- Total points are calculated for each player.
- The player with the **highest score** wins.

*Outcome Probability:* With the 1000-point bonus for Connect 4, any player achieving a 4-in-a-row is almost guaranteed victory (99%), unless the remaining opponent(s) have demonstrated exceptional skill by creating dozens of Connect 3 lines while simultaneously blocking all other moves.

## 4. Implementation Logic Suggestions for Developers

### A. Connect 4 Check (The 99% Factor)
In the `checkWin()` function, instead of returning a Boolean value, **return a Score**.
- Every time a player drops a piece, scan the 8 directional vectors.
- If a sequence of 4 is detected: `CurrentPlayer.Score += 1000`.

### B. Handling a "Tie" in Points
If, after the board is full, two or more players have an identical score (a rare edge case):
1.  **Priority 1:** The player with the **longest continuous sequence** wins.
2.  **Priority 2:** The player with the **most pieces located in the center columns** (Columns 4 and 5) wins.