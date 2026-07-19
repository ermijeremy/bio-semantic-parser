"""Shared in-memory state for active pipeline runs."""
import asyncio
from typing import Dict
from fastapi import WebSocket

_connections: Dict[str, WebSocket] = {}
_queues:      Dict[str, asyncio.Queue] = {}
_stop_flags:  Dict[str, bool] = {}
