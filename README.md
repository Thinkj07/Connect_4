# Connect Four · 3 Players

A polished, turn-based board game for **2–3 players** built with
**Python 3** and **Pygame**. Three coloured discs (Red, Yellow, Blue) compete
on an **8 × 7** grid. The first to connect four in a row usually wins, but
when the board fills up, the highest-scoring player takes it.

Supports three game modes: **SinglePlayer vs AI**, **Local Multiplayer**, and
full **Online Multiplayer** over WebSocket (FastAPI + Socket.IO server).

---

## Requirements

| Dependency               | Version | Purpose              |
| ------------------------ | ------- | -------------------- |
| Python                   | 3.9 +   | Runtime              |
| Pygame                   | 2.0 +   | Game UI              |
| python-socketio[client]  | 5.8 +   | Online multiplayer   |

## Installation

Install the client-side dependencies:

```bash
pip install -r requirements.txt
```

Or manually:

```bash
pip install pygame python-socketio[client]
```

## Running the game

```bash
python main.py
```

---

## Game Modes

### SinglePlayer

Play alone against AI opponents. Choose to face **1 or 2 AI bots**.

- 1 AI → 2-player game (You vs AI)
- 2 AI → 3-player game (You vs AI vs AI)

### Multiplayer (Local)

Play with friends on the same device. Add **1 or 2 extra players**.

- +1 Player → 2-player game
- +2 Players → 3-player game

### Online Multiplayer

Play with friends across the internet using a WebSocket connection.

**Features:**

- Create public or private rooms with unique 6-character codes
- Browse the list of public rooms and join with one click
- Join any room (public or private) with its room code
- 2–3 players per room, any mix of humans and AI bots
- Host controls: kick players, add/remove/cycle AI type, start game
- Authoritative server, real-time game-state synchronization
- Automatic lobby updates when players join/leave

**How to Play Online:**

1. **Connect**
   - Select *Online* from the main menu.
   - Type a display name and (optionally) change the server URL.
   - Pick *Create Room*, *Join by Code*, or *Browse Rooms* — the client
     connects to the server automatically the first time you click any option.

2. **Create a Room**
   - *Online → Create Room*.
   - Choose a room name, visibility (Public / Private), and max players (2 or 3).
   - Share the 6-character room code with friends.

3. **Join by Code**
   - *Online → Join by Code*.
   - Type the room code (A–Z / 2–9, 6 characters) and your name.

4. **Browse Public Rooms**
   - *Online → Browse Rooms*.
   - The list auto-refreshes every 5 s; click a waiting room to join.

**Host Controls (in Room Lobby):**

- **Kick** any non-host player.
- **+ AI** to fill an empty slot with an AI opponent.
- **Cycle** rotates that AI slot between Random, MCTS, and Minimax.
- **Remove** turns an AI slot back to *Empty*.
- **Start Game** becomes active once every slot is filled.

Non-host players see a *"Waiting for host to start…"* hint until the match
begins.

## Game rules

1. Players take turns dropping a disc into one of the 8 columns.
2. The disc falls to the lowest empty cell in that column.
3. **Connect 4** (4 in a row, horizontal / vertical / diagonal) is the main win.
4. Scores accumulate for every 2-in-a-row and 3-in-a-row you own.
5. Two distinct Connect-4 lines by the same player = **Sudden Victory**.
6. If the board fills with no winner, the **highest score** wins.
   Tie-breakers: longest continuous sequence, then number of pieces in the
   centre columns.

### Scoring

| Action / Condition           | Points |
| ---------------------------- | ------ |
| Connect 2                    | 2      |
| Connect 3                    | 15     |
| Connect 4 (Grand Slam)       | 1000   |

Only the longest sequence in each line is counted — the scores do not stack.

## AI opponents

Three AI strategies are available in every mode that allows bots:

| AI          | Description                                                                                      |
| ----------- | ------------------------------------------------------------------------------------------------ |
| **Random**  | Picks a legal column uniformly at random.                                                        |
| **MCTS**    | Monte-Carlo Tree Search (UCT). Configurable simulation count (200 – 5 000).                      |
| **Minimax** | Multiplayer Max^n / paranoid search. Configurable depth (2 – 6) with a windowed heuristic.       |

In **SinglePlayer** and **Local Multiplayer**, pick the type and difficulty on
the configuration screen. In **Online** rooms, the host cycles through AI
types with the *Cycle* button on each AI slot.

## Controls

| Action              | Control                             |
| ------------------- | ----------------------------------- |
| Drop a disc         | Left-click on a column              |
| Pause               | `Esc` key (offline or online game)  |
| Resume              | `Esc` key or *Resume* button        |
| Save & Quit         | Pause menu → *Save & Quit* (offline)|
| Continue saved game | Main menu → *Continue*              |
| Leave online room   | Room lobby / pause menu → *Leave Room* |
| Confirm text input  | `Enter` or click outside the field  |

## Running the Server (Online Mode)

A lightweight FastAPI + Socket.IO server handles matchmaking and the
authoritative game state.

```bash
cd server
pip install -r requirements.txt
python main.py                    # development
# or:
uvicorn server.main:socket_app --host 0.0.0.0 --port 8000
```

The server exposes:

- `GET /healthz` – health check
- `GET /` – server stats (active rooms / games)
- Socket.IO endpoint on the same port

Environment variables (see `server/config.py`):

| Variable               | Default    | Description                                 |
| ---------------------- | ---------- | ------------------------------------------- |
| `HOST`                 | `0.0.0.0`  | Bind address                                |
| `PORT`                 | `8000`     | Bind port                                   |
| `CORS_ORIGINS`         | `*`        | CORS allow-list for the WebSocket endpoint  |
| `MAX_ROOMS`            | `100`      | Maximum concurrent rooms                    |
| `ROOM_CODE_LENGTH`     | `6`        | Length of generated room codes              |
| `TURN_TIMEOUT`         | `60`       | Seconds per turn (reserved for future use)  |
| `AI_MOVE_DELAY`        | `1.0`      | Seconds the server waits before AI plays    |

The client's default server URL is `http://localhost:8000` — edit the URL
field on the *Online* screen to point at a remote server. Deploy the server
to Render, Railway, Fly.io, or any ASGI-compatible host for public access.

### Share your local server with ngrok

Use ngrok when you want **two computers on different networks** to play
online without router port-forwarding.

1. Start the server on your machine (host):

```bash
cd server
pip install -r requirements.txt
python main.py
# or:
uvicorn server.main:socket_app --host 0.0.0.0 --port 8000
```

2. In a second terminal, start ngrok:

```bash
ngrok http 8000
```

3. Copy the **Forwarding** URL that ngrok prints (prefer the `https://...`
one), for example: `https://abc123.ngrok-free.app`.

4. On every client PC: open the game → *Online* → set **Server URL** to that
ngrok URL (no trailing path).

Notes:

- The free ngrok URL changes every time you restart ngrok.
- Keep both `uvicorn` and `ngrok` running while you play.

## Save / Load

Offline games (SinglePlayer / Local Multiplayer) persist to `savegame.json`
via the **Save & Quit** option in the pause menu. Select **Continue** from
the main menu to resume where you left off. Online games are not saved
locally — their state lives on the server while the room is active.

## UI Design

The interface uses a **60-30-10** colour rule:

- **60 % Cream / Off-white** – background and panels
- **30 % Dark Teal** – board, buttons, borders
- **10 % Player Colours** – Red, Yellow, Blue for disc highlights

## Project structure

```
boardgame_3/
├── main.py                 # Entry point
├── app.py                  # Pygame App: offline menus, rendering, game loop
├── online_ui.py            # Mixin with online screens (menu, lobby, browser…)
├── board.py                # Board logic, win detection, scoring
├── ai.py                   # AI algorithms (Random, MCTS, Minimax)
├── constants.py            # All game & online constants
├── savegame.json           # Auto-generated save file
├── requirements.txt        # Client dependencies
├── Dockerfile              # Container image for the online server (Fly.io / any host)
├── fly.toml                # Fly.io app config (edit `app` name before deploy)
├── .dockerignore           # Keeps Docker build context small
├── README.md               # This file
│
├── server/                 # Online server (FastAPI + Socket.IO)
│   ├── __init__.py
│   ├── main.py             # ASGI entry point (uvicorn server.main:socket_app)
│   ├── config.py           # Environment-driven configuration
│   ├── models.py           # Room / Player / AISlot dataclasses
│   ├── room_manager.py     # Room CRUD + host operations
│   ├── game_session.py     # Authoritative game state, AI integration
│   ├── events.py           # Socket.IO event handlers
│   └── requirements.txt    # Server dependencies
│
├── client/                 # Online client modules
│   ├── __init__.py
│   ├── network.py          # socketio.Client wrapper + event callbacks
│   └── online_manager.py   # Thread-safe state bridge between net & UI
│
└── shared/
    ├── __init__.py
    └── protocol.py         # Event names, error codes, DTO dataclasses
```

## Socket.IO protocol (reference)

### Client → Server

`list_rooms`, `create_room`, `join_room`, `leave_room`, `kick_player`,
`add_ai`, `remove_ai`, `set_ready`, `start_game`, `make_move`,
`request_rematch`, `chat_message`.

### Server → Client

`rooms_list`, `room_created`, `room_joined`, `room_updated`, `player_joined`,
`player_left`, `player_kicked`, `game_started`, `game_update`, `your_turn`,
`game_over`, `error`, `chat_received`.

Error codes: `ROOM_NOT_FOUND`, `ROOM_FULL`, `ROOM_IN_PROGRESS`, `NOT_HOST`,
`NOT_YOUR_TURN`, `INVALID_MOVE`, `ALREADY_IN_ROOM`, `SLOT_OCCUPIED`,
`INVALID_AI`, `CONNECTION_LOST`.

See `shared/protocol.py` for the full set of constants and payload
dataclasses.

Terminal 1
ngrok config add-authtoken 3CZyobh3IOkKB7OBcmrtefJvVRc_4a6VEPDLfNpgNarD6C33m
python -m uvicorn server.main:socket_app --host 0.0.0.0 --port 8000        

Terminal 2
ngrok http 8000