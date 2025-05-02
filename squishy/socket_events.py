"""WebSocket event handlers for Squishy."""

import logging

from squishy.app import socketio


@socketio.on("connect")
def handle_connect():
    """Handle client connection."""
    logging.debug("Client connected to WebSocket")


@socketio.on("disconnect")
def handle_disconnect():
    """Handle client disconnection."""
    logging.debug("Client disconnected from WebSocket")


def emit_scan_status(status):
    """Emit scan status to all connected clients."""
    socketio.emit("scan_status", status)


def emit_job_update(job_data):
    """Emit job update to all connected clients."""
    socketio.emit("job_update", job_data)
