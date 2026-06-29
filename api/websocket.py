"""
PaperMind — WebSocket Manager
Source: docs/architecture.md (lines 263-294)

Handles real-time UI updates via WebSocket connections.

Events:
    ingestion_complete   — after Agent 2 completes
    ingestion_status     — during Agent 1 loop retry
    gap_detection_complete — after Agent 4
"""

import json
import logging
from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("papermind.websocket")


class ConnectionManager:
    """
    Manages WebSocket connections per user_id.
    Enables user-scoped broadcasting for real-time updates.
    """

    def __init__(self):
        # user_id → list of active WebSocket connections
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        """Accept and register a WebSocket connection for a user."""
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        logger.info(f"WebSocket connected: user={user_id}, total={len(self.active_connections[user_id])}")

    def disconnect(self, websocket: WebSocket, user_id: str) -> None:
        """Remove a WebSocket connection."""
        if user_id in self.active_connections:
            self.active_connections[user_id] = [
                ws for ws in self.active_connections[user_id] if ws != websocket
            ]
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        logger.info(f"WebSocket disconnected: user={user_id}")

    async def broadcast(self, user_id: str, message: dict) -> None:
        """
        Send a message to all WebSocket connections for a user.

        Message types from architecture.md:
            ingestion_complete:
                {type, paper_id, paper_title, nodes_created, nodes_merged,
                 cross_paper_edges, contradictions_detected, new_gaps}

            ingestion_status:
                {type, paper_id, status, attempt, reason}

            gap_detection_complete:
                {type, gap_count, critical_gaps, top_gap}
        """
        if user_id not in self.active_connections:
            return

        disconnected = []
        for websocket in self.active_connections[user_id]:
            try:
                await websocket.send_json(message)
            except Exception:
                disconnected.append(websocket)

        # Clean up disconnected sockets
        for ws in disconnected:
            self.disconnect(ws, user_id)

    async def send_personal(self, websocket: WebSocket, message: dict) -> None:
        """Send a message to a specific WebSocket connection."""
        try:
            await websocket.send_json(message)
        except Exception:
            pass

    def get_connected_users(self) -> list[str]:
        """Return list of user_ids with active connections."""
        return list(self.active_connections.keys())


# Singleton instance — imported by all API modules and Celery tasks
ws_manager = ConnectionManager()


async def ws_broadcast_callback(user_id: str):
    """
    Returns a callback function for agent_loop to send WebSocket updates.
    Used by ingest_paper_task and other Celery tasks.
    """
    async def callback(message: dict):
        await ws_manager.broadcast(user_id, message)
    return callback
