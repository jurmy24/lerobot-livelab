from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
import subprocess
from pathlib import Path
import logging
import glob

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Create static directory if it doesn't exist
os.makedirs("app/static", exist_ok=True)

# Mount the static directory
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Get the path to the lerobot root directory (3 levels up from this script)
LEROBOT_PATH = str(Path(__file__).parent.parent.parent.parent)
logger.info(f"LeRobot path: {LEROBOT_PATH}")

# Define the calibration config paths
CALIBRATION_BASE_PATH = os.path.expanduser(
    "~/.cache/huggingface/lerobot/calibration/teleoperators"
)
LEADER_CONFIG_PATH = os.path.join(CALIBRATION_BASE_PATH, "so101_leader")
FOLLOWER_CONFIG_PATH = os.path.join(CALIBRATION_BASE_PATH, "so101_follower")


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
        # Construct the command with all parameters
        env = os.environ.copy()
        env["PYTHONPATH"] = (
            "../../"  # Adjust this to point to the root directory where `lerobot` lives
        )

        # Get the full paths to the config files
        leader_config_path = os.path.join(LEADER_CONFIG_PATH, request.leader_config)
        follower_config_path = os.path.join(
            FOLLOWER_CONFIG_PATH, request.follower_config
        )

        cmd = [
            "python",
            "-m",  # Run as module
            "lerobot.teleoperate",
            "--robot.type=so101_follower",
            f"--robot.port={request.follower_port}",
            f"--robot.config={follower_config_path}",
            "--teleop.type=so101_leader",
            f"--teleop.port={request.leader_port}",
            f"--teleop.config={leader_config_path}",
        ]

        logger.info(f"Running command: {' '.join(cmd)}")

        # Run the command
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
        )

        # Wait for the process to complete
        stdout, stderr = process.communicate()

        logger.info(f"Command stdout: {stdout}")
        if stderr:
            logger.error(f"Command stderr: {stderr}")

        if process.returncode == 0:
            return {"message": "Teleoperation started successfully!", "output": stdout}
        else:
            return {"message": "Error starting teleoperation", "error": stderr}, 500

    except Exception as e:
        logger.error(f"Exception occurred: {str(e)}")
        return {"message": f"Error executing command: {str(e)}"}, 500
