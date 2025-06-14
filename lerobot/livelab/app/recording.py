import logging
import os
import shutil
from typing import Dict, Any, Callable
from concurrent.futures import ThreadPoolExecutor
from pydantic import BaseModel

# Import the main record functionality to reuse it
from lerobot.record import record, RecordConfig, DatasetRecordConfig
from lerobot.common.robots.so101_follower import SO101FollowerConfig
from lerobot.common.teleoperators.so101_leader import SO101LeaderConfig
from lerobot.common.datasets.lerobot_dataset import LeRobotDataset

# Import for patching the keyboard listener
from lerobot.common.utils import control_utils
import functools

logger = logging.getLogger(__name__)

# Import calibration paths from config (shared constants)
from .config import (
    CALIBRATION_BASE_PATH_TELEOP,
    CALIBRATION_BASE_PATH_ROBOTS,
    LEADER_CONFIG_PATH,
    FOLLOWER_CONFIG_PATH
)

# Global variables for recording state
recording_active = False
recording_thread = None
recording_events = None  # Events dict for controlling recording session


class RecordingRequest(BaseModel):
    leader_port: str
    follower_port: str
    leader_config: str
    follower_config: str
    dataset_repo_id: str
    single_task: str
    num_episodes: int = 5
    episode_time_s: int = 30
    reset_time_s: int = 10
    fps: int = 30
    video: bool = True
    push_to_hub: bool = False
    resume: bool = False


def setup_calibration_files(leader_config: str, follower_config: str):
    """Setup calibration files in the correct locations"""
    # Extract config names from file paths (remove .json extension)
    leader_config_name = os.path.splitext(leader_config)[0]
    follower_config_name = os.path.splitext(follower_config)[0]

    # Log the full paths to check if files exist
    leader_config_full_path = os.path.join(LEADER_CONFIG_PATH, leader_config)
    follower_config_full_path = os.path.join(FOLLOWER_CONFIG_PATH, follower_config)

    logger.info(f"Leader config path: {leader_config_full_path}")
    logger.info(f"Follower config path: {follower_config_full_path}")
    logger.info(f"Leader config exists: {os.path.exists(leader_config_full_path)}")
    logger.info(f"Follower config exists: {os.path.exists(follower_config_full_path)}")

    # Create calibration directories if they don't exist
    leader_calibration_dir = os.path.join(CALIBRATION_BASE_PATH_TELEOP, "so101_leader")
    follower_calibration_dir = os.path.join(CALIBRATION_BASE_PATH_ROBOTS, "so101_follower")
    os.makedirs(leader_calibration_dir, exist_ok=True)
    os.makedirs(follower_calibration_dir, exist_ok=True)

    # Copy calibration files to the correct locations if they're not already there
    leader_target_path = os.path.join(leader_calibration_dir, f"{leader_config_name}.json")
    follower_target_path = os.path.join(follower_calibration_dir, f"{follower_config_name}.json")

    if not os.path.exists(leader_target_path):
        shutil.copy2(leader_config_full_path, leader_target_path)
        logger.info(f"Copied leader calibration to {leader_target_path}")

    if not os.path.exists(follower_target_path):
        shutil.copy2(follower_config_full_path, follower_target_path)
        logger.info(f"Copied follower calibration to {follower_target_path}")

    return leader_config_name, follower_config_name


def create_record_config(request: RecordingRequest) -> RecordConfig:
    """Create a RecordConfig from the recording request"""
    # Setup calibration files
    leader_config_name, follower_config_name = setup_calibration_files(
        request.leader_config, request.follower_config
    )

    # Create robot config
    robot_config = SO101FollowerConfig(
        port=request.follower_port,
        id=follower_config_name,
    )

    # Create teleop config
    teleop_config = SO101LeaderConfig(
        port=request.leader_port,
        id=leader_config_name,
    )

    # Create dataset config
    dataset_config = DatasetRecordConfig(
        repo_id=request.dataset_repo_id,
        single_task=request.single_task,
        num_episodes=request.num_episodes,
        episode_time_s=request.episode_time_s,
        reset_time_s=request.reset_time_s,
        fps=request.fps,
        video=request.video,
        push_to_hub=request.push_to_hub,
    )

    # Create the main record config
    record_config = RecordConfig(
        robot=robot_config,
        teleop=teleop_config,
        dataset=dataset_config,
        resume=request.resume,
        display_data=False,  # Don't display data in API mode
        play_sounds=False,   # Don't play sounds in API mode
    )

    return record_config


def handle_start_recording(request: RecordingRequest, websocket_manager=None) -> Dict[str, Any]:
    """Handle start recording request by using the existing record() function"""
    global recording_active, recording_thread, recording_events

    if recording_active:
        return {"success": False, "message": "Recording is already active"}

    try:
        logger.info(f"Starting recording for dataset: {request.dataset_repo_id}")
        logger.info(f"Task: {request.single_task}")

        # Initialize recording events for web control (replaces keyboard controls)
        recording_events = {
            "exit_early": False,      # Right arrow key -> "Skip to next episode" button
            "stop_recording": False,  # ESC key -> "Stop recording" button
            "rerecord_episode": False # Left arrow key -> "Re-record episode" button
        }

        # Create the record configuration
        record_config = create_record_config(request)

        # Start recording in a separate thread
        def recording_worker():
            global recording_active
            recording_active = True
            try:
                # Use the original record() function but with web-controlled events
                dataset = record_with_web_events(record_config, recording_events)
                logger.info(f"Recording completed successfully. Dataset has {dataset.num_episodes} episodes")
                return {"success": True, "episodes": dataset.num_episodes}
            except Exception as e:
                logger.error(f"Error during recording: {e}")
                return {"success": False, "error": str(e)}
            finally:
                recording_active = False

        recording_thread = ThreadPoolExecutor(max_workers=1)
        future = recording_thread.submit(recording_worker)

        return {
            "success": True,
            "message": "Recording started successfully",
            "dataset_id": request.dataset_repo_id,
            "num_episodes": request.num_episodes
        }

    except Exception as e:
        recording_active = False
        logger.error(f"Failed to start recording: {e}")
        return {"success": False, "message": f"Failed to start recording: {str(e)}"}


def handle_stop_recording() -> Dict[str, Any]:
    """Handle stop recording request - replaces ESC key"""
    global recording_active, recording_thread, recording_events

    if not recording_active or recording_events is None:
        return {"success": False, "message": "No recording session is active"}

    try:
        # Trigger the stop recording event (replaces ESC key)
        recording_events["stop_recording"] = True
        recording_events["exit_early"] = True
        
        logger.info("Stop recording triggered from web interface")

        return {
            "success": True,
            "message": "Recording stop requested successfully",
        }

    except Exception as e:
        logger.error(f"Error stopping recording: {e}")
        return {"success": False, "message": f"Failed to stop recording: {str(e)}"}


def handle_exit_early() -> Dict[str, Any]:
    """Handle exit early request - replaces right arrow key"""
    global recording_events

    if not recording_active or recording_events is None:
        return {"success": False, "message": "No recording session is active"}

    try:
        # Trigger the exit early event (replaces right arrow key)
        recording_events["exit_early"] = True
        
        logger.info("Exit early (skip to next episode) triggered from web interface")

        return {
            "success": True,
            "message": "Skip to next episode requested successfully",
        }

    except Exception as e:
        logger.error(f"Error triggering exit early: {e}")
        return {"success": False, "message": f"Failed to trigger exit early: {str(e)}"}


def handle_rerecord_episode() -> Dict[str, Any]:
    """Handle rerecord episode request - replaces left arrow key"""
    global recording_events

    if not recording_active or recording_events is None:
        return {"success": False, "message": "No recording session is active"}

    try:
        # Trigger the rerecord episode event (replaces left arrow key)
        recording_events["rerecord_episode"] = True
        recording_events["exit_early"] = True
        
        logger.info("Re-record episode triggered from web interface")

        return {
            "success": True,
            "message": "Re-record episode requested successfully",
        }

    except Exception as e:
        logger.error(f"Error triggering rerecord episode: {e}")
        return {"success": False, "message": f"Failed to trigger rerecord episode: {str(e)}"}


def handle_recording_status() -> Dict[str, Any]:
    """Handle recording status request"""
    return {
        "recording_active": recording_active,
        "available_controls": {
            "stop_recording": recording_active,      # ESC key replacement
            "exit_early": recording_active,          # Right arrow key replacement
            "rerecord_episode": recording_active     # Left arrow key replacement
        },
        "message": "Recording status retrieved successfully"
    }


# For backward compatibility, in case we want to add frame modifications later
def add_custom_frame_modifier(modifier_func: Callable[[Dict[str, Any]], Dict[str, Any]]):
    """Placeholder for future custom frame modifications"""
    logger.info("Custom frame modifier registered (not yet implemented in simplified version)")


def add_timestamp_modifier():
    """Placeholder for timestamp modifier"""
    logger.info("Timestamp modifier registered (not yet implemented in simplified version)")


def add_debug_info_modifier():
    """Placeholder for debug info modifier"""
    logger.info("Debug info modifier registered (not yet implemented in simplified version)")


def record_with_web_events(cfg: RecordConfig, web_events: dict) -> LeRobotDataset:
    """
    Use the original record() function but replace keyboard events with web events.
    This approach reuses 100% of the original record.py logic by monkey-patching the keyboard listener.
    """
    # Store the original init_keyboard_listener function
    original_init_keyboard_listener = control_utils.init_keyboard_listener
    
    # Create a replacement function that returns our web events instead of keyboard events
    def web_init_keyboard_listener():
        # Return None for listener (no keyboard needed) and our web events
        return None, web_events
    
    # Temporarily replace the keyboard listener function
    control_utils.init_keyboard_listener = web_init_keyboard_listener
    
    try:
        # Call the original record() function - it will use our web events instead of keyboard
        dataset = record(cfg)
        return dataset
    finally:
        # Restore the original keyboard listener function
        control_utils.init_keyboard_listener = original_init_keyboard_listener 
