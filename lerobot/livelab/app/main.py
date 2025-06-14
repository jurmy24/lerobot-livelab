from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
import subprocess
from pathlib import Path
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Create static directory if it doesn't exist
os.makedirs("app/static", exist_ok=True)

# Mount the static directory
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Get the path to the lerobot root directory (3 levels up from this script)
LEROBOT_PATH = str(Path(__file__).parent.parent.parent)
logger.info(f"LeRobot path: {LEROBOT_PATH}")

# Get conda executable path
CONDA_EXE = os.environ.get("CONDA_EXE", "conda")
logger.info(f"Using conda executable: {CONDA_EXE}")


class MoveArmRequest(BaseModel):
    pass  # Empty model since we don't need any parameters for now


@app.get("/")
def read_root():

    return FileResponse("app/static/index.html")


@app.post("/move-arm")
def move_arm(request: MoveArmRequest):
    try:
        # Construct the command with all parameters
        cmd = [
            CONDA_EXE,
            "run",
            "-n",
            "lerobot",  # Use the lerobot environment
            "python",
            "-m",  # Run as module
            "lerobot.teleoperate",  # Use module path
            "--robot.type=so101_follower",
            "--robot.port=/dev/tty.usbmodem58760431541",
            '--robot.cameras={"front":{"type":"opencv","index_or_path":0,"width":1920,"height":1080,"fps":30}}',
            "--robot.id=black",
            "--teleop.type=so101_leader",
            "--teleop.port=/dev/tty.usbmodem58760431551",
            "--teleop.id=blue",
            "--display_data=false",
        ]

        logger.info(f"Running command: {' '.join(cmd)}")

        # Run the command
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
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
