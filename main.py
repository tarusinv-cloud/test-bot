#!/usr/bin/env python3
"""
Server-side cursor management application.

The cursor state (position, visibility, style) lives entirely on the server.
Clients connect via WebSocket to receive real-time updates and send control
commands.  A REST API is also available for programmatic access.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

# ---------------------------------------------------------------------------
# Cursor state (server-authoritative)
# ---------------------------------------------------------------------------

@dataclass
class CursorState:
    x: float = 400.0
    y: float = 300.0
    visible: bool = True
    color: str = "#e74c3c"
    size: int = 18
    label: str = ""
    last_updated: float = field(default_factory=time.time)

    def move(self, x: float, y: float) -> None:
        self.x = x
        self.y = y
        self.last_updated = time.time()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


cursor = CursorState()

# ---------------------------------------------------------------------------
# Connected WebSocket clients
# ---------------------------------------------------------------------------

connected_clients: set[WebSocket] = set()


async def broadcast(message: dict[str, Any]) -> None:
    """Send a JSON message to every connected WebSocket client."""
    payload = json.dumps(message)
    stale: list[WebSocket] = []
    for ws in connected_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            stale.append(ws)
    for ws in stale:
        connected_clients.discard(ws)

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    connected_clients.clear()


app = FastAPI(
    title="Server-Side Cursor Manager",
    description="Cursor state lives on the server; clients observe and control it via WebSocket / REST.",
    lifespan=lifespan,
)


STATIC_DIR = Path(__file__).resolve().parent / "static"


# ---- REST endpoints -------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the single-page web interface."""
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/api/cursor")
async def get_cursor():
    """Return current cursor state."""
    return cursor.to_dict()


@app.post("/api/cursor/move")
async def move_cursor(x: float, y: float):
    """Move cursor to (x, y) and broadcast the update."""
    cursor.move(x, y)
    await broadcast({"type": "cursor_update", "state": cursor.to_dict()})
    return cursor.to_dict()


@app.post("/api/cursor/toggle")
async def toggle_visibility():
    """Toggle cursor visibility."""
    cursor.visible = not cursor.visible
    cursor.last_updated = time.time()
    await broadcast({"type": "cursor_update", "state": cursor.to_dict()})
    return cursor.to_dict()


@app.post("/api/cursor/style")
async def set_style(color: str | None = None, size: int | None = None, label: str | None = None):
    """Update cursor appearance."""
    if color is not None:
        cursor.color = color
    if size is not None:
        cursor.size = max(4, min(size, 64))
    if label is not None:
        cursor.label = label
    cursor.last_updated = time.time()
    await broadcast({"type": "cursor_update", "state": cursor.to_dict()})
    return cursor.to_dict()


# ---- WebSocket endpoint ---------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.add(ws)
    try:
        await ws.send_text(json.dumps({
            "type": "cursor_update",
            "state": cursor.to_dict(),
        }))
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            action = msg.get("action")
            if action == "move":
                cursor.move(float(msg["x"]), float(msg["y"]))
            elif action == "toggle":
                cursor.visible = not cursor.visible
                cursor.last_updated = time.time()
            elif action == "style":
                if "color" in msg:
                    cursor.color = msg["color"]
                if "size" in msg:
                    cursor.size = max(4, min(int(msg["size"]), 64))
                if "label" in msg:
                    cursor.label = msg["label"]
                cursor.last_updated = time.time()
            else:
                continue

            await broadcast({"type": "cursor_update", "state": cursor.to_dict()})
    except WebSocketDisconnect:
        pass
    finally:
        connected_clients.discard(ws)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
