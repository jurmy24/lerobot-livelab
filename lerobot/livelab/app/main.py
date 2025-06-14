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
from lerobot.common.teleoperators.so101_leader import SO101LeaderConfig, SO101Leader
from lerobot.common.robots.so101_follower import SO101FollowerConfig, SO101Follower
from lerobot.teleoperate import teleoperate, TeleoperateConfig
import json
import shutil
import select
import sys
import termios
import tty
import asyncio
from typing import List, Dict, Any
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import queue


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global variables for WebSocket connections and robot state
connected_websockets: List[WebSocket] = []
current_robot = None
current_teleop = None
teleoperation_active = False


def setup_keyboard():
    """Set up keyboard for non-blocking input"""
    old_settings = termios.tcgetattr(sys.stdin)
    tty.setraw(sys.stdin.fileno())
    return old_settings


def restore_keyboard(old_settings):
    """Restore keyboard settings"""
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


def check_quit_key():
    """Check if 'q' key was pressed"""
    if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
        key = sys.stdin.read(1)
        return key.lower() == "q"
    return False


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

# Define the calibration config paths
CALIBRATION_BASE_PATH_TELEOP = os.path.expanduser(
    "~/.cache/huggingface/lerobot/calibration/teleoperators"
)
CALIBRATION_BASE_PATH_ROBOTS = os.path.expanduser(
    "~/.cache/huggingface/lerobot/calibration/robots"
)
LEADER_CONFIG_PATH = os.path.join(CALIBRATION_BASE_PATH_TELEOP, "so101_leader")
FOLLOWER_CONFIG_PATH = os.path.join(CALIBRATION_BASE_PATH_ROBOTS, "so101_follower")


class TeleoperateRequest(BaseModel):
    leader_port: str
    follower_port: str
    leader_config: str
    follower_config: str


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


def get_joint_positions_from_robot(robot) -> Dict[str, float]:
    """
    Extract current joint positions from the robot and convert to URDF joint format.

    Args:
        robot: The robot instance (SO101Follower)

    Returns:
        Dictionary mapping URDF joint names to radian values
    """
    try:
        # Get the current observation from the robot
        observation = robot.get_observation()

        # Map robot motor names to URDF joint names
        # Based on the motor configuration in SO101Follower and URDF joint names
        motor_to_urdf_mapping = {
            "shoulder_pan": "Rotation",  # Base rotation
            "shoulder_lift": "Pitch",  # Shoulder pitch
            "elbow_flex": "Elbow",  # Elbow flexion
            "wrist_flex": "Wrist_Pitch",  # Wrist pitch
            "wrist_roll": "Wrist_Roll",  # Wrist roll
            "gripper": "Jaw",  # Gripper/jaw
        }

        joint_positions = {}

        # Extract joint positions and convert degrees to radians
        for motor_name, urdf_joint_name in motor_to_urdf_mapping.items():
            motor_key = f"{motor_name}.pos"
            if motor_key in observation:
                # Convert degrees to radians for the URDF viewer
                angle_degrees = observation[motor_key]
                angle_radians = angle_degrees * (3.14159 / 180.0)
                joint_positions[urdf_joint_name] = angle_radians
            else:
                logger.warning(f"Motor {motor_key} not found in observation")
                joint_positions[urdf_joint_name] = 0.0

        return joint_positions

    except Exception as e:
        logger.error(f"Error getting joint positions: {e}")
        return {
            "Rotation": 0.0,
            "Pitch": 0.0,
            "Elbow": 0.0,
            "Wrist_Pitch": 0.0,
            "Wrist_Roll": 0.0,
            "Jaw": 0.0,
        }


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
    try:
        # Extract config names from file paths (remove .json extension)
        leader_config_name = os.path.splitext(request.leader_config)[0]
        follower_config_name = os.path.splitext(request.follower_config)[0]

        # Log the full paths to check if files exist
        leader_config_full_path = os.path.join(
            LEADER_CONFIG_PATH, request.leader_config
        )
        follower_config_full_path = os.path.join(
            FOLLOWER_CONFIG_PATH, request.follower_config
        )

        logger.info(f"Checking calibration files:")
        logger.info(f"Leader config path: {leader_config_full_path}")
        logger.info(f"Follower config path: {follower_config_full_path}")
        logger.info(f"Leader config exists: {os.path.exists(leader_config_full_path)}")
        logger.info(
            f"Follower config exists: {os.path.exists(follower_config_full_path)}"
        )

        # Create calibration directories if they don't exist
        leader_calibration_dir = os.path.join(
            CALIBRATION_BASE_PATH_TELEOP, "so101_leader"
        )
        follower_calibration_dir = os.path.join(
            CALIBRATION_BASE_PATH_ROBOTS, "so101_follower"
        )
        os.makedirs(leader_calibration_dir, exist_ok=True)
        os.makedirs(follower_calibration_dir, exist_ok=True)

        # Copy calibration files to the correct locations if they're not already there
        leader_target_path = os.path.join(
            leader_calibration_dir, f"{leader_config_name}.json"
        )
        follower_target_path = os.path.join(
            follower_calibration_dir, f"{follower_config_name}.json"
        )

        if not os.path.exists(leader_target_path):
            shutil.copy2(leader_config_full_path, leader_target_path)
            logger.info(f"Copied leader calibration to {leader_target_path}")
        else:
            logger.info(f"Leader calibration already exists at {leader_target_path}")

        if not os.path.exists(follower_target_path):
            shutil.copy2(follower_config_full_path, follower_target_path)
            logger.info(f"Copied follower calibration to {follower_target_path}")
        else:
            logger.info(
                f"Follower calibration already exists at {follower_target_path}"
            )

        logger.info(
            f"Setting up robot with port: {request.follower_port} and config: {follower_config_name}"
        )
        robot_config = SO101FollowerConfig(
            port=request.follower_port,
            id=follower_config_name,
        )

        logger.info(
            f"Setting up teleop device with port: {request.leader_port} and config: {leader_config_name}"
        )
        teleop_config = SO101LeaderConfig(
            port=request.leader_port,
            id=leader_config_name,
        )

        logger.info("Initializing robot and teleop device...")
        robot = SO101Follower(robot_config)
        teleop_device = SO101Leader(teleop_config)

        logger.info("Connecting to devices...")
        robot.bus.connect()
        teleop_device.bus.connect()

        # Write calibration to motors' memory
        logger.info("Writing calibration to motors...")
        robot.bus.write_calibration(robot.calibration)
        teleop_device.bus.write_calibration(teleop_device.calibration)

        # Connect cameras and configure motors
        logger.info("Connecting cameras and configuring motors...")
        for cam in robot.cameras.values():
            cam.connect()
        robot.configure()
        teleop_device.configure()
        logger.info("Successfully connected to both devices")

        logger.info("Starting teleoperation loop...")
        logger.info("Press 'q' to quit teleoperation")

        # Set up keyboard for non-blocking input
        old_settings = setup_keyboard()

        # teleoperate_config = TeleoperateConfig(
        #     teleop=teleop_config,
        #     robot=robot_config,
        # )

        # teleoperate(
        #     teleoperate_config,
        # )
        try:
            want_to_disconnect = False
            last_broadcast_time = 0
            broadcast_interval = 0.05  # Broadcast every 50ms (20 FPS)

            while not want_to_disconnect:
                action = teleop_device.get_action()
                robot.send_action(action)

                # Broadcast joint positions to connected WebSocket clients
                current_time = time.time()
                if current_time - last_broadcast_time >= broadcast_interval:
                    try:
                        joint_positions = get_joint_positions_from_robot(robot)
                        joint_data = {
                            "type": "joint_update",
                            "joints": joint_positions,
                            "timestamp": current_time,
                        }

                        # Use asyncio to broadcast the data
                        if manager.active_connections:
                            manager.broadcast_joint_data_sync(joint_data)

                        last_broadcast_time = current_time
                    except Exception as e:
                        logger.error(f"Error broadcasting joint data: {e}")

                # Check for keyboard input
                if check_quit_key():
                    want_to_disconnect = True
                    logger.info("Quit key pressed, stopping teleoperation...")
        finally:
            # Always restore keyboard settings
            restore_keyboard(old_settings)
            robot.disconnect()
            teleop_device.disconnect()
            logger.info("Teleoperation stopped")

            # Clean up broadcast thread
            manager.stop_broadcast_thread()

        return {"message": "Teleoperation completed successfully"}

    except Exception as e:
        logger.error(f"Exception occurred: {str(e)}")
        # Clean up broadcast thread on error
        manager.stop_broadcast_thread()
        return {"message": f"Error executing command: {str(e)}"}, 500


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


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources when FastAPI shuts down"""
    logger.info("🔄 FastAPI shutting down, cleaning up...")
    if manager:
        manager.stop_broadcast_thread()
    logger.info("✅ Cleanup completed")
