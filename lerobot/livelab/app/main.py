from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import subprocess
from pathlib import Path
import logging
import glob
import json
import asyncio
from typing import List, Dict, Any
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import queue

# Import our custom recording functionality
from .recording import (
    RecordingRequest,
    handle_start_recording,
    handle_stop_recording,
    handle_exit_early,
    handle_rerecord_episode,
    handle_recording_status
)

# Import our custom teleoperation/calibrating functionality
from .calibrating import (
    TeleoperateRequest,
    handle_start_teleoperation,
    handle_stop_teleoperation,
    handle_teleoperation_status,
    handle_get_joint_positions
)


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global variables for WebSocket connections
connected_websockets: List[WebSocket] = []


app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Create static directory if it doesn't exist
os.makedirs("app/static", exist_ok=True)

# Mount the static directory
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Get the path to the lerobot root directory (3 levels up from this script)
LEROBOT_PATH = str(Path(__file__).parent.parent.parent.parent)
logger.info(f"LeRobot path: {LEROBOT_PATH}")

# Import shared configuration constants
from .config import (
    CALIBRATION_BASE_PATH_TELEOP,
    CALIBRATION_BASE_PATH_ROBOTS,
    LEADER_CONFIG_PATH,
    FOLLOWER_CONFIG_PATH
)


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.broadcast_queue = queue.Queue()
        self.broadcast_thread = None
        self.is_running = False

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(
            f"WebSocket connected. Total connections: {len(self.active_connections)}"
        )

        # Start broadcast thread if not running
        if not self.is_running:
            self.start_broadcast_thread()

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(
                f"WebSocket disconnected. Total connections: {len(self.active_connections)}"
            )

        # Stop broadcast thread if no connections
        if not self.active_connections and self.is_running:
            self.stop_broadcast_thread()

    def start_broadcast_thread(self):
        """Start the background thread for broadcasting data"""
        if self.is_running:
            return

        self.is_running = True
        self.broadcast_thread = threading.Thread(
            target=self._broadcast_worker, daemon=True
        )
        self.broadcast_thread.start()
        logger.info("📡 Broadcast thread started")

    def stop_broadcast_thread(self):
        """Stop the background thread"""
        self.is_running = False
        if self.broadcast_thread:
            self.broadcast_thread.join(timeout=1.0)
            logger.info("📡 Broadcast thread stopped")

    def _broadcast_worker(self):
        """Background worker thread for broadcasting WebSocket data"""
        import asyncio

        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            while self.is_running:
                try:
                    # Get data from queue with timeout
                    data = self.broadcast_queue.get(timeout=0.1)
                    if data is None:  # Poison pill to stop
                        break

                    # Broadcast to all connections
                    if self.active_connections:
                        loop.run_until_complete(self._send_to_all_connections(data))

                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"Error in broadcast worker: {e}")

        finally:
            loop.close()

    async def _send_to_all_connections(self, data: Dict[str, Any]):
        """Send data to all active WebSocket connections"""
        if not self.active_connections:
            return

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception as e:
                logger.error(f"Error sending data to WebSocket: {e}")
                disconnected.append(connection)

        # Remove disconnected connections
        for connection in disconnected:
            self.disconnect(connection)

    def broadcast_joint_data_sync(self, data: Dict[str, Any]):
        """Thread-safe method to queue data for broadcasting"""
        if self.is_running and self.active_connections:
            try:
                self.broadcast_queue.put_nowait(data)
            except queue.Full:
                logger.warning("Broadcast queue is full, dropping data")


manager = ConnectionManager()





@app.get("/")
def read_root():
    return FileResponse("app/static/index.html")


@app.get("/get-configs")
def get_configs():
    # Get all available calibration configs
    leader_configs = [
        os.path.basename(f)
        for f in glob.glob(os.path.join(LEADER_CONFIG_PATH, "*.json"))
    ]
    follower_configs = [
        os.path.basename(f)
        for f in glob.glob(os.path.join(FOLLOWER_CONFIG_PATH, "*.json"))
    ]

    return {"leader_configs": leader_configs, "follower_configs": follower_configs}


@app.post("/move-arm")
def teleoperate_arm(request: TeleoperateRequest):
    """Start teleoperation of the robot arm"""
    return handle_start_teleoperation(request, manager)


@app.post("/stop-teleoperation")
def stop_teleoperation():
    """Stop the current teleoperation session"""
    return handle_stop_teleoperation()


@app.get("/teleoperation-status")
def teleoperation_status():
    """Get the current teleoperation status"""
    return handle_teleoperation_status()


@app.get("/joint-positions")
def get_joint_positions():
    """Get current robot joint positions"""
    return handle_get_joint_positions()


@app.get("/health")
def health_check():
    """Simple health check endpoint to verify server is running"""
    return {"status": "ok", "message": "FastAPI server is running"}


@app.get("/ws-test")
def websocket_test():
    """Test endpoint to verify WebSocket support"""
    return {"websocket_endpoint": "/ws/joint-data", "status": "available"}


@app.websocket("/ws/joint-data")
async def websocket_endpoint(websocket: WebSocket):
    logger.info("🔗 New WebSocket connection attempt")
    try:
        await manager.connect(websocket)
        logger.info("✅ WebSocket connection established")

        while True:
            # Keep the connection alive and wait for messages
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                # Handle any incoming messages if needed
                logger.debug(f"Received WebSocket message: {data}")
            except asyncio.TimeoutError:
                # No message received, continue
                pass
            except WebSocketDisconnect:
                logger.info("🔌 WebSocket client disconnected")
                break

            # Small delay to prevent excessive CPU usage
            await asyncio.sleep(0.01)

    except WebSocketDisconnect:
        logger.info("🔌 WebSocket disconnected normally")
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
    finally:
        manager.disconnect(websocket)
        logger.info("🧹 WebSocket connection cleaned up")


@app.post("/start-recording")
def start_recording(request: RecordingRequest):
    """Start a dataset recording session"""
    return handle_start_recording(request, manager)


@app.post("/stop-recording")
def stop_recording():
    """Stop the current recording session"""
    return handle_stop_recording()


@app.get("/recording-status")
def recording_status():
    """Get the current recording status"""
    return handle_recording_status()


@app.post("/recording-exit-early")
def recording_exit_early():
    """Skip to next episode (replaces right arrow key)"""
    return handle_exit_early()


@app.post("/recording-rerecord-episode")
def recording_rerecord_episode():
    """Re-record current episode (replaces left arrow key)"""
    return handle_rerecord_episode()


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources when FastAPI shuts down"""
    logger.info("🔄 FastAPI shutting down, cleaning up...")
    
    # Stop any active recording - handled by recording module cleanup
    
    if manager:
        manager.stop_broadcast_thread()
    logger.info("✅ Cleanup completed")
