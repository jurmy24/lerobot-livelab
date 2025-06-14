from fastapi import FastAPI
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


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
            while not want_to_disconnect:
                action = teleop_device.get_action()
                # TODO: Setup websockets to update the frontend robot here
                robot.send_action(action)

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

        return {"message": "Teleoperation completed successfully"}

    except Exception as e:
        logger.error(f"Exception occurred: {str(e)}")
        return {"message": f"Error executing command: {str(e)}"}, 500
