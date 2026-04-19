# SPECIFICATION: ONLINE MULTIPLAYER SYSTEM (CONNECT 4 - 3 PLAYERS)

## 1. Overview

This document describes the implementation of an online multiplayer system for the Connect Four 3-Player game. The system uses a **client-server architecture** with **WebSocket** for real-time communication, allowing players to compete across different networks.

### Key Features

- Create public/private rooms with unique codes
- Browse and join public rooms
- Join any room (public or private) via room code
- Support 2-3 players per room (human or AI)
- Host controls: kick players, add/remove AI, start game
- Real-time game state synchronization

---

## 2. Architecture

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│    Client 1     │         │     Server      │         │    Client 2     │
│    (Pygame)     │◄───────►│   (FastAPI +    │◄───────►│    (Pygame)     │
│                 │   WS    │  SocketIO)      │   WS    │                 │
└─────────────────┘         └─────────────────┘         └─────────────────┘
                                    │
                                    │ WS
                                    ▼
                            ┌─────────────────┐
                            │    Client 3     │
                            │    (Pygame)     │
                            └─────────────────┘
```

### Technology Stack

| Component  | Technology                         | Purpose                           |
| ---------- | ---------------------------------- | --------------------------------- |
| Server     | Python + FastAPI + python-socketio | WebSocket server, room management |
| Client     | Pygame + python-socketio[client]   | Game UI, network communication    |
| Protocol   | Socket.IO (WebSocket)              | Real-time bidirectional events    |
| Deployment | Render.com / Railway / Fly.io      | Cloud hosting for public access   |

---

## 3. Project Structure

```
boardgame_3/
├── server/
│   ├── __init__.py
│   ├── main.py              # Server entry point (FastAPI + SocketIO)
│   ├── room_manager.py      # Room CRUD operations
│   ├── game_session.py      # Server-side game logic
│   ├── models.py            # Data classes (Room, Player, GameState)
│   ├── events.py            # Socket event handlers
│   └── config.py            # Server configuration
│
├── client/
│   ├── __init__.py
│   ├── network.py           # WebSocket client wrapper
│   └── online_manager.py    # Online state management
│
├── shared/
│   └── protocol.py          # Shared event names and data structures
│
├── app.py                   # Updated with online states
├── board.py                 # Reused by both client and server
├── constants.py             # Add online-related constants
└── requirements.txt         # Add socketio dependencies
```

---

## 4. Data Models

### 4.1 Room

```python
@dataclass
class Room:
    code: str                    # Unique 6-character code (e.g., "ABC123")
    name: str                    # Display name (e.g., "Player1's Room")
    host_id: str                 # Socket ID of the room creator
    is_public: bool              # Visible in room browser
    max_players: int             # 2 or 3
    players: List[Player]        # Connected human players
    ai_slots: List[AISlot]       # AI players in the room
    status: RoomStatus           # "waiting", "playing", "finished"
    created_at: datetime
    game_state: Optional[GameState]
```

### 4.2 Player

```python
@dataclass
class Player:
    id: str                      # Socket ID
    name: str                    # Display name
    slot: int                    # Player slot (1, 2, or 3)
    is_host: bool                # Room creator flag
    is_ready: bool               # Ready to start
    connected: bool              # Connection status
```

### 4.3 AISlot

```python
@dataclass
class AISlot:
    slot: int                    # Player slot (1, 2, or 3)
    ai_type: str                 # "Random", "MCTS", "Minimax"
    params: dict                 # {"simulations": 1000} or {"depth": 4}
```

### 4.4 GameState

```python
@dataclass
class GameState:
    board: List[List[int]]       # 7x8 grid
    current_player: int          # 1, 2, or 3
    scores: Dict[int, int]       # {1: 0, 2: 15, 3: 1000}
    winner: Optional[int]        # None, 0 (draw), or winner slot
    win_reason: str              # "connect4", "sudden_victory", "board_full"
    last_move: Optional[Tuple[int, int]]  # (row, col)
```

### 4.5 RoomStatus Enum

```python
class RoomStatus(str, Enum):
    WAITING = "waiting"          # In lobby, waiting for players
    PLAYING = "playing"          # Game in progress
    FINISHED = "finished"        # Game ended, showing results
```

---

## 5. Socket.IO Protocol

### 5.1 Client → Server Events

| Event             | Payload                                          | Description                  |
| ----------------- | ------------------------------------------------ | ---------------------------- |
| `list_rooms`      | `{}`                                             | Request list of public rooms |
| `create_room`     | `{name: str, is_public: bool, max_players: int}` | Create a new room            |
| `join_room`       | `{room_code: str, player_name: str}`             | Join existing room           |
| `leave_room`      | `{}`                                             | Leave current room           |
| `kick_player`     | `{player_id: str}`                               | Host kicks a player          |
| `add_ai`          | `{slot: int, ai_type: str, params: dict}`        | Host adds AI to slot         |
| `remove_ai`       | `{slot: int}`                                    | Host removes AI from slot    |
| `set_ready`       | `{ready: bool}`                                  | Toggle ready status          |
| `start_game`      | `{}`                                             | Host starts the game         |
| `make_move`       | `{col: int}`                                     | Player makes a move          |
| `request_rematch` | `{}`                                             | Request to play again        |
| `chat_message`    | `{message: str}`                                 | Send chat message (optional) |

### 5.2 Server → Client Events

| Event           | Payload                                    | Description              |
| --------------- | ------------------------------------------ | ------------------------ |
| `rooms_list`    | `{rooms: List[RoomSummary]}`               | List of public rooms     |
| `room_created`  | `{room: Room}`                             | Room creation success    |
| `room_joined`   | `{room: Room}`                             | Successfully joined room |
| `room_updated`  | `{room: Room}`                             | Room state changed       |
| `player_joined` | `{player: Player}`                         | New player joined        |
| `player_left`   | `{player_id: str, slot: int}`              | Player left/disconnected |
| `player_kicked` | `{reason: str}`                            | You were kicked          |
| `game_started`  | `{game_state: GameState}`                  | Game has begun           |
| `game_update`   | `{game_state: GameState}`                  | Board/score updated      |
| `your_turn`     | `{timeout_seconds: int}`                   | It's your turn           |
| `game_over`     | `{winner: int, reason: str, scores: dict}` | Game ended               |
| `error`         | `{code: str, message: str}`                | Error occurred           |
| `chat_received` | `{player_name: str, message: str}`         | Chat message             |

### 5.3 RoomSummary (for room browser)

```python
@dataclass
class RoomSummary:
    code: str
    name: str
    player_count: int            # Current players
    max_players: int             # 2 or 3
    status: RoomStatus
    has_ai: bool
```

---

## 6. Server Implementation

### 6.1 Room Manager (`server/room_manager.py`)

```python
class RoomManager:
    def __init__(self):
        self.rooms: Dict[str, Room] = {}
        self.player_room_map: Dict[str, str] = {}  # player_id -> room_code

    def create_room(self, host_id: str, name: str, is_public: bool, max_players: int) -> Room
    def join_room(self, room_code: str, player_id: str, player_name: str) -> Room
    def leave_room(self, player_id: str) -> Optional[str]  # Returns room_code
    def get_room(self, room_code: str) -> Optional[Room]
    def get_public_rooms(self) -> List[RoomSummary]
    def kick_player(self, room_code: str, host_id: str, target_id: str) -> bool
    def add_ai(self, room_code: str, slot: int, ai_type: str, params: dict) -> bool
    def remove_ai(self, room_code: str, slot: int) -> bool
    def cleanup_empty_rooms(self) -> None  # Periodic cleanup
```

### 6.2 Game Session (`server/game_session.py`)

```python
class GameSession:
    def __init__(self, room: Room):
        self.room = room
        self.board = Board()
        self.current_player = 1
        self.scores = {1: 0, 2: 0, 3: 0}
        self.ais = {}  # slot -> AI instance

    def initialize_game(self) -> GameState
    def make_move(self, player_slot: int, col: int) -> Tuple[bool, GameState]
    def process_ai_turn(self) -> Optional[Tuple[int, GameState]]  # Returns (col, state)
    def is_player_turn(self, player_slot: int) -> bool
    def get_state(self) -> GameState
    def check_game_over(self) -> Tuple[bool, Optional[int], str]
```

### 6.3 Main Server (`server/main.py`)

```python
from fastapi import FastAPI
import socketio

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI()
socket_app = socketio.ASGIApp(sio, app)

room_manager = RoomManager()
game_sessions: Dict[str, GameSession] = {}

@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")

@sio.event
async def disconnect(sid):
    # Handle player disconnect, notify room
    room_code = room_manager.leave_room(sid)
    if room_code:
        await sio.emit('player_left', {'player_id': sid}, room=room_code)

@sio.event
async def create_room(sid, data):
    room = room_manager.create_room(
        host_id=sid,
        name=data['name'],
        is_public=data['is_public'],
        max_players=data['max_players']
    )
    await sio.enter_room(sid, room.code)
    await sio.emit('room_created', {'room': asdict(room)}, to=sid)

@sio.event
async def join_room(sid, data):
    try:
        room = room_manager.join_room(data['room_code'], sid, data['player_name'])
        await sio.enter_room(sid, room.code)
        await sio.emit('room_joined', {'room': asdict(room)}, to=sid)
        await sio.emit('player_joined', {'player': asdict(room.players[-1])},
                       room=room.code, skip_sid=sid)
    except Exception as e:
        await sio.emit('error', {'code': 'JOIN_FAILED', 'message': str(e)}, to=sid)

@sio.event
async def make_move(sid, data):
    room_code = room_manager.player_room_map.get(sid)
    session = game_sessions.get(room_code)
    if session:
        player_slot = get_player_slot(sid, session.room)
        success, state = session.make_move(player_slot, data['col'])
        if success:
            await sio.emit('game_update', {'game_state': asdict(state)}, room=room_code)
            # Check for AI turn
            await process_ai_turns(room_code, session)

# ... more event handlers
```

---

## 7. Client Implementation

### 7.1 Network Manager (`client/network.py`)

```python
import socketio

class NetworkManager:
    def __init__(self):
        self.sio = socketio.Client()
        self.connected = False
        self.current_room: Optional[Room] = None
        self.callbacks = {}  # event -> callback function

        self._setup_handlers()

    def _setup_handlers(self):
        @self.sio.event
        def connect():
            self.connected = True
            self._trigger('on_connect')

        @self.sio.event
        def disconnect():
            self.connected = False
            self._trigger('on_disconnect')

        @self.sio.on('room_joined')
        def on_room_joined(data):
            self.current_room = Room(**data['room'])
            self._trigger('on_room_joined', self.current_room)

        @self.sio.on('game_update')
        def on_game_update(data):
            self._trigger('on_game_update', data['game_state'])

        # ... more handlers

    def connect(self, server_url: str) -> bool
    def disconnect(self) -> None
    def create_room(self, name: str, is_public: bool, max_players: int) -> None
    def join_room(self, room_code: str, player_name: str) -> None
    def leave_room(self) -> None
    def make_move(self, col: int) -> None
    def request_rooms_list(self) -> None
    def set_callback(self, event: str, callback: Callable) -> None
    def _trigger(self, event: str, *args) -> None
```

### 7.2 Online Manager (`client/online_manager.py`)

```python
class OnlineManager:
    """Manages online game state and UI coordination."""

    def __init__(self, network: NetworkManager):
        self.network = network
        self.state = "disconnected"  # disconnected, lobby, in_room, playing
        self.room: Optional[Room] = None
        self.game_state: Optional[GameState] = None
        self.my_slot: int = 0
        self.is_my_turn: bool = False
        self.rooms_list: List[RoomSummary] = []

        self._setup_callbacks()

    def _setup_callbacks(self):
        self.network.set_callback('on_room_joined', self._on_room_joined)
        self.network.set_callback('on_game_update', self._on_game_update)
        self.network.set_callback('on_rooms_list', self._on_rooms_list)
        # ... more callbacks

    def connect_to_server(self, url: str) -> bool
    def create_room(self, name: str, is_public: bool, max_players: int) -> None
    def join_room_by_code(self, code: str) -> None
    def join_room_from_list(self, room_summary: RoomSummary) -> None
    def make_move(self, col: int) -> bool  # Returns False if not your turn
    def is_connected(self) -> bool
    def get_my_player(self) -> Optional[Player]
```

---

## 8. App.py Updates

### 8.1 New States

```python
# Add to state machine
ONLINE_STATES = [
    "online_menu",       # Choose: Create Room / Join Room / Browse Rooms
    "online_connecting", # Connecting to server
    "room_browser",      # List of public rooms
    "join_by_code",      # Enter room code manually
    "create_room",       # Room creation options
    "room_lobby",        # Waiting room (host controls, player list)
    "playing_online",    # Online gameplay
    "online_gameover",   # Results with rematch option
]
```

### 8.2 New UI Screens

#### Online Menu Screen

```
┌────────────────────────────────────┐
│         ONLINE MULTIPLAYER         │
│                                    │
│    ┌──────────────────────────┐    │
│    │      Create Room         │    │
│    └──────────────────────────┘    │
│    ┌──────────────────────────┐    │
│    │      Join by Code        │    │
│    └──────────────────────────┘    │
│    ┌──────────────────────────┐    │
│    │      Browse Rooms        │    │
│    └──────────────────────────┘    │
│    ┌──────────────────────────┐    │
│    │          Back            │    │
│    └──────────────────────────┘    │
│                                    │
│    Server: ● Connected             │
└────────────────────────────────────┘
```

#### Room Browser Screen

```
┌────────────────────────────────────┐
│           PUBLIC ROOMS             │
├────────────────────────────────────┤
│  Room Name       Players   Status  │
│ ┌────────────────────────────────┐ │
│ │ Alice's Room    2/3    Waiting │ │
│ └────────────────────────────────┘ │
│ ┌────────────────────────────────┐ │
│ │ Pro Players     1/2    Waiting │ │
│ └────────────────────────────────┘ │
│ ┌────────────────────────────────┐ │
│ │ Fun Game        3/3    Playing │ │
│ └────────────────────────────────┘ │
│                                    │
│  [Refresh]              [Back]     │
└────────────────────────────────────┘
```

#### Room Lobby Screen (Host View)

```
┌────────────────────────────────────┐
│     ROOM: ABC123 (Public)          │
├────────────────────────────────────┤
│  Players (2/3):                    │
│                                    │
│  🔴 Slot 1: You (Host)      [---]  │
│  🟡 Slot 2: Player2         [Kick] │
│  🔵 Slot 3: Empty     [+AI] [+Human]│
│                                    │
│  AI Options: Random / MCTS / Minimax│
│                                    │
│  ┌──────────────────────────────┐  │
│  │        START GAME            │  │
│  └──────────────────────────────┘  │
│  ┌──────────────────────────────┐  │
│  │        LEAVE ROOM            │  │
│  └──────────────────────────────┘  │
└────────────────────────────────────┘
```

#### Join by Code Screen

```
┌────────────────────────────────────┐
│          JOIN BY CODE              │
│                                    │
│     Enter Room Code:               │
│    ┌────────────────────────┐      │
│    │  A B C 1 2 3           │      │
│    └────────────────────────┘      │
│                                    │
│    Your Name:                      │
│    ┌────────────────────────┐      │
│    │  Player                │      │
│    └────────────────────────┘      │
│                                    │
│    [Join]              [Back]      │
│                                    │
└────────────────────────────────────┘
```

---

## 9. Implementation Phases

### Phase 1: Server Foundation (2-3 days)

- [ ] Set up FastAPI + python-socketio server
- [ ] Implement RoomManager (create, join, leave, list)
- [ ] Basic event handlers (connect, disconnect, create_room, join_room)
- [ ] Test with simple Python client script

### Phase 2: Game Logic on Server (2-3 days)

- [ ] Implement GameSession class
- [ ] Move validation on server side
- [ ] Turn management and player slot assignment
- [ ] AI integration on server
- [ ] Game over detection and scoring

### Phase 3: Client Network Layer (2-3 days)

- [ ] Implement NetworkManager class
- [ ] Implement OnlineManager class
- [ ] Connection handling and reconnection logic
- [ ] Event callbacks and state synchronization

### Phase 4: Pygame UI Integration (3-4 days)

- [ ] Add online menu state and UI
- [ ] Implement room browser with scrollable list
- [ ] Implement join by code screen with text input
- [ ] Implement create room screen
- [ ] Implement room lobby screen
- [ ] Adapt playing state for online mode
- [ ] Online game over screen with rematch

### Phase 5: Polish & Edge Cases (2-3 days)

- [ ] Handle disconnections gracefully
- [ ] Add reconnection logic
- [ ] Timeout for inactive players
- [ ] Error messages and user feedback
- [ ] Loading indicators

### Phase 6: Deployment (1-2 days)

- [ ] Choose hosting platform (Render/Railway/Fly.io)
- [ ] Configure environment variables
- [ ] Deploy server
- [ ] Update client with production server URL
- [ ] Test across different networks

---

## 10. Configuration

### 10.1 Server Config (`server/config.py`)

```python
import os

SERVER_HOST = os.getenv("HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("PORT", 8000))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")

# Room settings
MAX_ROOMS = 100
ROOM_CODE_LENGTH = 6
ROOM_CLEANUP_INTERVAL = 300  # seconds
EMPTY_ROOM_TIMEOUT = 600     # seconds

# Game settings
TURN_TIMEOUT = 60            # seconds per turn
AI_MOVE_DELAY = 1.0          # seconds before AI moves
```

### 10.2 Client Config (`constants.py` additions)

```python
# Online settings
DEFAULT_SERVER_URL = "http://localhost:8000"  # Development
PRODUCTION_SERVER_URL = "https://your-server.onrender.com"  # Production
CONNECTION_TIMEOUT = 10  # seconds
RECONNECT_ATTEMPTS = 3
DEFAULT_PLAYER_NAME = "Player"
```

---

## 11. Dependencies

### Server (`server/requirements.txt`)

```
fastapi>=0.100.0
uvicorn[standard]>=0.23.0
python-socketio>=5.8.0
python-dotenv>=1.0.0
```

### Client (add to main `requirements.txt`)

```
python-socketio[client]>=5.8.0
```

---

## 12. Error Handling

### Error Codes

| Code               | Description                       |
| ------------------ | --------------------------------- |
| `ROOM_NOT_FOUND`   | Room code doesn't exist           |
| `ROOM_FULL`        | Room has reached max players      |
| `ROOM_IN_PROGRESS` | Cannot join, game already started |
| `NOT_HOST`         | Action requires host privileges   |
| `NOT_YOUR_TURN`    | Attempted move out of turn        |
| `INVALID_MOVE`     | Column full or out of bounds      |
| `ALREADY_IN_ROOM`  | Must leave current room first     |
| `CONNECTION_LOST`  | Server connection dropped         |

---

## 13. Security Considerations

1. **Input Validation**: Validate all client inputs on server
2. **Rate Limiting**: Limit room creation and join attempts
3. **Room Code Generation**: Use cryptographically random codes
4. **No Sensitive Data**: Don't expose internal IDs or server details
5. **Timeout Handling**: Auto-kick inactive players

---

## 14. Testing Strategy

### Unit Tests

- RoomManager operations
- GameSession logic
- Move validation

### Integration Tests

- Full game flow with multiple clients
- Disconnect/reconnect scenarios
- AI player integration

### Manual Testing

- Cross-network play (different WiFi)
- Mobile hotspot testing
- High latency simulation

---

## 15. Future Enhancements (Optional)

- [ ] In-game chat
- [ ] Player profiles and statistics
- [ ] Matchmaking system
- [ ] Spectator mode
- [ ] Tournament brackets
- [ ] Leaderboards
