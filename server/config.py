"""Server configuration loaded from environment variables with safe defaults."""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SERVER_HOST = os.getenv("HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("PORT", "8000"))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")

MAX_ROOMS = int(os.getenv("MAX_ROOMS", "100"))
ROOM_CODE_LENGTH = int(os.getenv("ROOM_CODE_LENGTH", "6"))
ROOM_CLEANUP_INTERVAL = int(os.getenv("ROOM_CLEANUP_INTERVAL", "300"))
EMPTY_ROOM_TIMEOUT = int(os.getenv("EMPTY_ROOM_TIMEOUT", "600"))

TURN_TIMEOUT = int(os.getenv("TURN_TIMEOUT", "60"))
AI_MOVE_DELAY = float(os.getenv("AI_MOVE_DELAY", "1.0"))

ROOM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
