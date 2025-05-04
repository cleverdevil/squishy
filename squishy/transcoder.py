"""Media transcoding functionality."""

import os
import uuid
import threading
import logging
import subprocess
import re
import json
import datetime
import signal
import time
from typing import Dict, Optional, List, Callable, Any

from squishy.config import load_config
from squishy.models import TranscodeJob, MediaItem, Movie, Episode
from squishy.scanner import get_media
from squishy.effeffmpeg.effeffmpeg import transcode as effeff_transcode, detect_capabilities, TranscodeProcess

# Configure logging
logger = logging.getLogger(__name__)

# In-memory job store
JOBS: Dict[str, TranscodeJob] = {}
JOBS_LOCK = threading.RLock()  # Use RLock to allow re-entry from the same thread

# Job queue for pending jobs
JOB_QUEUE: List[Dict] = []
JOB_QUEUE_LOCK = threading.RLock()

# Currently running jobs
RUNNING_JOBS = set()
RUNNING_JOBS_LOCK = threading.RLock()


def create_job(media_item: MediaItem, preset_name: str) -> TranscodeJob:
    """Create a new transcoding job."""
    logger.debug(
        f"Creating transcoding job for media_id={media_item.id} with preset={preset_name}"
    )
    job_id = str(uuid.uuid4())
    job = TranscodeJob(
        id=job_id,
        media_id=media_item.id,
        preset_name=preset_name,
        status="pending",
    )
    with JOBS_LOCK:
        JOBS[job_id] = job
    logger.debug(f"Created job with id={job_id}")
    return job


def get_job(job_id: str) -> Optional[TranscodeJob]:
    """Get a job by ID."""
    logger.debug(f"Getting job with id={job_id}")
    with JOBS_LOCK:
        return JOBS.get(job_id)


def get_running_job_count():
    """Get the number of currently running jobs."""
    with JOBS_LOCK:
        return len([j for j in JOBS.values() if j.status == "processing"])


def get_pending_jobs():
    """Get a list of all pending jobs from the JOBS dictionary."""
    with JOBS_LOCK:
        return [j for j in JOBS.values() if j.status == "pending"]


def process_job_queue():
    """Process the job queue based on the concurrency limit."""
    config = load_config()
    max_jobs = config.max_concurrent_jobs

    # Check if we can start more jobs
    current_running = get_running_job_count()
    available_slots = max(0, max_jobs - current_running)

    # Get queue length with thread safety
    with JOB_QUEUE_LOCK:
        queue_length = len(JOB_QUEUE)

    logger.debug(
        f"Processing job queue: current_running={current_running}, max_jobs={max_jobs}, available_slots={available_slots}, queue_length={queue_length}"
    )

    # Also check for any pending jobs in the JOBS dictionary that might not be in the queue
    pending_jobs = get_pending_jobs()
    logger.debug(f"Found {len(pending_jobs)} pending jobs in the JOBS dictionary")

    # First handle jobs in the JOB_QUEUE
    jobs_to_process = []  # Initialize outside the conditional to avoid UnboundLocalError

    if available_slots > 0:
        with JOB_QUEUE_LOCK:
            if JOB_QUEUE:
                logger.debug(f"Starting up to {available_slots} jobs from queue")
                # Get the next job(s) from the queue
                jobs_to_start = min(available_slots, len(JOB_QUEUE))

                # Get jobs from queue while holding the lock
                for _ in range(jobs_to_start):
                    if not JOB_QUEUE:
                        break
                    # Pop job data from the queue
                    jobs_to_process.append(JOB_QUEUE.pop(0))

        # Process jobs outside the lock to avoid holding it for too long
        for job_data in jobs_to_process:
            job_id = job_data["job_id"]
            media_item = job_data["media_item"]
            preset_name = job_data["preset_name"]
            output_dir = job_data["output_dir"]

            job = get_job(job_id)
            if job and job.status == "pending":
                # Start the job
                _start_transcode_job(job, media_item, preset_name, output_dir)
                logger.debug(
                    f"Started queued job {job_id}, jobs remaining in queue"
                )
                available_slots -= 1
            else:
                logger.warning(
                    f"Job {job_id} in queue is not in pending state or doesn't exist anymore"
                )

    # If we still have available slots and there are pending jobs not in the queue,
    # we need to find the media items and presets to start them
    if available_slots > 0 and pending_jobs:
        logger.debug(
            f"Looking for pending jobs not in the queue: available_slots={available_slots}, pending_jobs={len(pending_jobs)}"
        )

        # Get the list of job IDs already in the queue
        with JOB_QUEUE_LOCK:
            queued_job_ids = [job_data["job_id"] for job_data in JOB_QUEUE]

        # Find the pending jobs not in the queue
        for job in pending_jobs:
            # Skip if job is already in the queue
            if job.id in queued_job_ids:
                continue

            # Get the media item and preset
            config = load_config()

            media_item = get_media(job.media_id)
            if not media_item:
                logger.warning(
                    f"Media item {job.media_id} for pending job {job.id} not found"
                )
                continue

            preset_name = job.preset_name
            if preset_name not in config.presets:
                logger.warning(
                    f"Preset {preset_name} for pending job {job.id} not found"
                )
                continue

            output_dir = config.transcode_path

            # Start the job
            _start_transcode_job(job, media_item, preset_name, output_dir)
            logger.debug(f"Started pending job {job.id} that was not in queue")

            available_slots -= 1
            if available_slots <= 0:
                break


def start_transcode(
    job: TranscodeJob, media_item: MediaItem, preset_name: str, output_dir: str
):
    """Start or queue a transcoding job based on concurrency limits."""
    logger.debug(
        f"Starting transcode job={job.id} for media={media_item.id}, preset={preset_name}"
    )

    config = load_config()

    if preset_name in config.presets:
        preset = config.presets[preset_name]
        logger.debug(
            f"Preset settings: scale={preset.get('scale')}, codec={preset.get('codec')}, "
            f"container={preset.get('container')}, crf={preset.get('crf')}, bitrate={preset.get('bitrate')}"
        )
    else:
        logger.warning(f"Preset {preset_name} not found in configuration")

    max_jobs = config.max_concurrent_jobs

    # Check if we can start the job immediately
    current_running = get_running_job_count()

    if current_running < max_jobs:
        # Start the job immediately
        _start_transcode_job(job, media_item, preset_name, output_dir)
        logger.debug(f"Started job {job.id} immediately")
    else:
        # Queue the job with thread safety
        with JOB_QUEUE_LOCK:
            JOB_QUEUE.append(
                {
                    "job_id": job.id,
                    "media_item": media_item,
                    "preset_name": preset_name,
                    "output_dir": output_dir,
                }
            )
            queue_position = len(JOB_QUEUE)

        logger.debug(f"Queued job {job.id}, position in queue: {queue_position}")


def _start_transcode_job(
    job: TranscodeJob, media_item: MediaItem, preset_name: str, output_dir: str
):
    """Internal function to start a transcoding job."""
    # Add to running jobs set with thread safety
    with RUNNING_JOBS_LOCK:
        RUNNING_JOBS.add(job.id)

    # Define a callback for when the job finishes
    def job_finished_callback():
        # Remove from running jobs with thread safety
        with RUNNING_JOBS_LOCK:
            if job.id in RUNNING_JOBS:
                RUNNING_JOBS.remove(job.id)

        # Process the queue to see if we can start more jobs
        process_job_queue()

    # Start the job in a thread
    threading.Thread(
        target=transcode_thread,
        args=(job, media_item, preset_name, output_dir, job_finished_callback),
        daemon=True,
    ).start()

    logger.debug(f"Started transcoding thread for job {job.id}")


def transcode_thread(
    job: TranscodeJob,
    media_item: MediaItem,
    preset_name: str,
    output_dir: str,
    callback: Optional[Callable] = None,
):
    """Thread function for transcoding."""
    try:
        # Import here to avoid circular imports
        from squishy.socket_events import emit_job_update

        # Emit initial job state
        emit_job_update(
            {
                "id": job.id,
                "media_id": job.media_id,
                "status": job.status,
                "progress": job.progress,
            }
        )

        transcode(job, media_item, preset_name, output_dir)

        # Emit final job state
        emit_job_update(
            {
                "id": job.id,
                "media_id": job.media_id,
                "status": job.status,
                "progress": job.progress,
                "output_path": job.output_path,
                "output_size": job.output_size,
            }
        )
    finally:
        # Call the callback if provided
        if callback:
            callback()


def transcode(
    job: TranscodeJob, media_item: MediaItem, preset_name: str, output_dir: str
):
    """Perform the transcoding using effeffmpeg."""
    try:
        # Update status with thread safety
        job.update_status("processing")
        logger.debug(f"Job {job.id} status changed to processing")
        
        # Apply path mappings to the output directory
        # This ensures we use the correct path for transcodes, especially in Docker
        original_output_dir = output_dir
        output_dir = apply_output_path_mapping(output_dir)
        
        if original_output_dir != output_dir:
            logger.info(f"Output directory mapped from {original_output_dir} to {output_dir}")

        # Get the preset from config
        config = load_config()
        if preset_name not in config.presets:
            raise ValueError(f"Preset '{preset_name}' not found in configuration")

        preset = config.presets[preset_name]

        # Get original filename without extension
        original_filename = os.path.basename(media_item.path)
        filename_without_ext, _ = os.path.splitext(original_filename)

        # Get container format from preset (remove leading dot if present)
        container = preset.get("container", ".mkv")
        if container.startswith("."):
            container = container[1:]

        # Create output filename with preset name in parentheses
        output_filename = f"{filename_without_ext} ({preset_name}).{container}"
        output_path = os.path.join(output_dir, output_filename)
        logger.debug(f"Output path: {output_path}")

        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        logger.debug(f"Ensured output directory exists: {output_dir}")

        # Check if input file exists
        if not os.path.exists(media_item.path):
            raise FileNotFoundError(f"Input file not found: {media_item.path}")

        # Create a progress callback to update the job status
        def progress_callback(status_text, progress_value):
            # Extract current time from status text if possible
            time_match = re.search(r"Time: (\d+):(\d+):([\d.]+)", status_text)
            if time_match:
                h, m, s = time_match.groups()
                current_time = int(h) * 3600 + int(m) * 60 + float(s)
                job.current_time = current_time

            # Extract duration from status if available
            duration_match = re.search(r"(\d+):(\d+):([\d.]+)", status_text)
            if duration_match and "/" in status_text:
                parts = status_text.split("/", 1)
                if len(parts) == 2 and duration_match:
                    h, m, s = re.search(r"(\d+):(\d+):([\d.]+)", parts[1]).groups()
                    job.duration = int(h) * 3600 + int(m) * 60 + float(s)

            if progress_value is not None:
                job.progress = progress_value

            # Add to logs if it's not just a progress update
            if not status_text.startswith("Time:"):
                if len(job.ffmpeg_logs) >= 1000:
                    job.ffmpeg_logs.pop(0)  # Remove oldest log if we have too many
                job.ffmpeg_logs.append(status_text)

            # Emit socket update every 2 seconds
            if job.current_time and int(job.current_time) % 2 == 0:
                try:
                    from squishy.socket_events import emit_job_update
                    emit_job_update({
                        "id": job.id,
                        "media_id": job.media_id,
                        "status": job.status,
                        "progress": job.progress,
                        "current_time": job.current_time,
                        "duration": job.duration,
                    })
                except ImportError:
                    pass  # Ignore if socket_events can't be imported

        # Get hardware acceleration settings from config
        hw_accel = config.hw_accel
        hw_device = config.hw_device

        # Override force_software if hw_accel is set to none
        if hw_accel and hw_accel.lower() == "none":
            preset["force_software"] = True

        # Run the effeffmpeg transcoding
        logger.info(f"Starting transcode for job {job.id} using effeffmpeg")

        try:
            # Generate the command first with dry_run to log it
            command = effeff_transcode(
                input_file=media_item.path,
                output_file=output_path,
                dry_run=True,
                overwrite=True,
                presets_data={"preset": preset}  # Wrap the preset in a dict as expected by effeffmpeg
            )

            # Store the command in the job
            cmd_str = " ".join(command)
            job.ffmpeg_command = cmd_str
            logger.debug(f"FFmpeg command: {cmd_str}")

            # Now run the actual transcode non-blocking to use our progress callback
            process = effeff_transcode(
                input_file=media_item.path,
                output_file=output_path,
                overwrite=True,
                non_blocking=True,
                progress_callback=progress_callback,
                preset_name="preset",  # Use the preset name
                presets_data={"preset": preset}  # Pass the preset data directly
            )

            # Store the process ID for potential cancellation
            if hasattr(process, "process") and process.process:
                job.process_id = process.process.pid
                logger.debug(f"Process ID for job {job.id}: {job.process_id}")

            # Monitor the process
            cancelled = False
            while not process.finished:
                # Check if job has been cancelled
                with job._lock:
                    is_cancelled = job.status == "cancelled"

                if is_cancelled:
                    logger.info(f"Job {job.id} has been cancelled, terminating process")
                    process.terminate()
                    cancelled = True
                    break

                # Update output file size
                if os.path.exists(output_path):
                    output_size = os.path.getsize(output_path)
                    job.update_output_size(format_file_size(output_size))

                # Use process.poll() instead of wait with timeout to check if it's still running
                # This avoids the TimeoutExpired exception when using eventlet's patched subprocess
                if process.process.poll() is not None:
                    # Process completed
                    process.finished = True
                    process.returncode = process.process.returncode
                    break

                # Sleep for a short time
                time.sleep(0.5)

            # If cancelled, return early
            if cancelled:
                return

            # Check if the process completed successfully
            if process.returncode != 0:
                stderr = process.get_stderr()
                logger.error(f"Transcode failed with code {process.returncode}: {stderr}")
                raise RuntimeError(f"Transcode failed with code {process.returncode}")

            # Update job status
            job.update_status("completed")

            # Update progress and output path
            with job._lock:
                job.progress = 1.0
                job.output_path = output_path

            # Get final output file size
            if os.path.exists(output_path):
                output_size = os.path.getsize(output_path)
                job.update_output_size(format_file_size(output_size))

            logger.debug(
                f"Job {job.id} completed successfully, output: {output_path}, size: {job.output_size}"
            )

            # Create JSON sidecar file with metadata
            sidecar_path = f"{output_path}.json"

            # Handle poster_url and thumbnail_url differently for Movies vs Episodes
            poster_url = None
            thumbnail_url = None

            if isinstance(media_item, Episode):
                # For episodes, we want to use the parent show's poster as the poster_url
                # and the episode's thumbnail as the thumbnail_url
                from squishy.scanner import get_show

                show = get_show(media_item.show_id)
                if show:
                    poster_url = show.poster_url
                # Use the episode's thumbnail_url if available, otherwise fall back to poster_url
                thumbnail_url = media_item.thumbnail_url or media_item.poster_url
            else:
                # For movies, use the movie's poster_url as poster
                poster_url = media_item.poster_url
                # Use movie's thumbnail_url if available, otherwise fall back to poster_url
                thumbnail_url = media_item.thumbnail_url or media_item.poster_url

            metadata = {
                "original_path": media_item.path,
                "media_id": media_item.id,
                "title": media_item.title,
                "year": media_item.year,
                "type": media_item.type,
                "poster_url": poster_url,
                "thumbnail_url": thumbnail_url,
                "preset_name": preset_name,
                "completed_at": datetime.datetime.now().isoformat(),
                "output_size": job.output_size,
                "duration": job.duration,
            }

            # Add TV show specific metadata if applicable
            if isinstance(media_item, Episode):
                metadata["show_id"] = media_item.show_id
                metadata["season_number"] = media_item.season_number
                metadata["episode_number"] = media_item.episode_number

                # Add show title to the metadata
                from squishy.scanner import get_show
                show = get_show(media_item.show_id)
                if show:
                    metadata["show_title"] = show.title

            # Write metadata to sidecar file
            with open(sidecar_path, "w") as f:
                json.dump(metadata, f, indent=2)

            logger.debug(f"Created metadata sidecar file: {sidecar_path}")

        except Exception as e:
            logger.error(f"Error during transcoding: {str(e)}", exc_info=True)
            raise

    except Exception as e:
        logger.error(f"Transcoding job {job.id} failed: {str(e)}", exc_info=True)

        # Update job status with thread safety
        job.update_status("failed")

        # Update error message with thread safety
        with job._lock:
            job.error_message = str(e)

        # Make sure to capture final error messages in logs
        if hasattr(e, "stderr") and e.stderr:
            error_lines = []

            # Get current logs
            with job._lock:
                error_lines = list(job.ffmpeg_logs)

            # Add error lines
            for line in e.stderr.splitlines():
                if line.strip():
                    error_lines.append(f"STDERR: {line.strip()}")

            # Update logs
            job.update_logs(error_lines)


def get_media_duration(input_path: str) -> Optional[float]:
    """Get the duration of a media file in seconds using effeffmpeg."""
    try:
        # Run ffprobe to get duration
        ffprobe_cmd = ["ffprobe", "-v", "error", "-show_entries",
                      "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                      input_path]

        result = subprocess.run(ffprobe_cmd, capture_output=True, text=True)

        if result.returncode == 0 and result.stdout.strip():
            try:
                # ffprobe returns duration in seconds as a float
                return float(result.stdout.strip())
            except (ValueError, TypeError) as e:
                logger.error(f"Error parsing ffprobe duration: {e}")

        # Fall back to regex parsing if ffprobe doesn't return a clean duration
        ffmpeg_cmd = ["ffmpeg", "-i", input_path]
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)

        # Look for duration in the output
        duration_match = re.search(
            r"Duration: (\d{2}):(\d{2}):(\d{2})\.(\d{2})", result.stderr
        )
        if duration_match:
            hours = int(duration_match.group(1))
            minutes = int(duration_match.group(2))
            seconds = int(duration_match.group(3))
            centiseconds = int(duration_match.group(4))

            total_seconds = hours * 3600 + minutes * 60 + seconds + centiseconds / 100
            return total_seconds

        return None
    except Exception as e:
        logger.error(f"Error getting media duration: {str(e)}")
        return None


def apply_output_path_mapping(path: str) -> str:
    """
    Apply path mapping to output directory if needed.
    
    This handles cases where the config.transcode_path may need to be 
    mapped to a different location (like in Docker environments).
    """
    config = load_config()
    
    # Print detailed debug information
    logger.debug(f"apply_output_path_mapping: Input path: {path}")
    logger.debug(f"apply_output_path_mapping: Path mappings: {config.path_mappings}")
    
    if not config.path_mappings:
        logger.debug("apply_output_path_mapping: No path mappings defined, returning original path")
        return path
        
    # Check if the transcode path is directly in the path mappings
    for source_path, target_path in config.path_mappings.items():
        if path == source_path:
            logger.info(f"Mapping output path: {path} -> {target_path}")
            return target_path
    
    # If path doesn't exist but a mapping target does, use that
    if not os.path.exists(path):
        logger.debug(f"apply_output_path_mapping: Path {path} does not exist, checking for accessible alternatives")
        for source_path, target_path in config.path_mappings.items():
            # Check if the target path exists and matches our transcode path pattern
            if os.path.exists(target_path) and (target_path.endswith('/transcodes') or target_path == '/transcodes'):
                logger.info(f"Using accessible output path mapping: {path} -> {target_path}")
                return target_path
    
    logger.debug(f"apply_output_path_mapping: No mapping found, using original path: {path}")
    return path

def format_file_size(size_bytes: int) -> str:
    """Format file size in a human-readable way."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{round(size_bytes / 1024, 2)} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{round(size_bytes / (1024 * 1024), 2)} MB"
    else:
        return f"{round(size_bytes / (1024 * 1024 * 1024), 2)} GB"


def get_process_status(pid: int) -> Optional[str]:
    """Get the status of a process by PID.

    Returns:
        str: Process status or None if process not found

    Status values:
        'R': Running
        'S': Sleeping (interruptible)
        'D': Disk sleep (uninterruptible)
        'Z': Zombie
        'T': Stopped
        '+': Foreground process
    """
    try:
        with open(f"/proc/{pid}/stat", "r") as f:
            stats = f.read().split()
            if len(stats) > 2:
                # Third field is the process state
                return stats[2]
        return None
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None


def detect_hw_accel(ffmpeg_path: str) -> Dict[str, Any]:
    """Detect available hardware acceleration methods using effeffmpeg."""
    config = load_config()

    # Check if we have hw_capabilities in config
    if config.hw_capabilities:
        capabilities = config.hw_capabilities
        logger.info("Using hardware capabilities from config")
    else:
        # Use effeffmpeg's detect_capabilities with the provided ffmpeg_path
        logger.info(f"Detecting hardware capabilities using FFmpeg at: {ffmpeg_path}")
        capabilities = detect_capabilities(ffmpeg_path=ffmpeg_path)

    # Format the results to match the expected output format in the admin UI
    result = {
        "methods": [],
        "devices": {
            "cuda": [],
            "vaapi": [],
            "qsv": [],
            "videotoolbox": [],
            "d3d11va": [],
            "dxva2": [],
            "opencl": [],
            "amf": [],
        },
        "recommended": {"method": "", "device": ""},
    }

    # Add detected methods
    hwaccel = capabilities.get("hwaccel")
    if hwaccel:
        result["methods"].append(hwaccel)

    # Add detected encoders as methods
    for codec, encoder in capabilities.get("encoders", {}).items():
        method = encoder.split('_')[1] if '_' in encoder else encoder
        if method not in result["methods"]:
            result["methods"].append(method)

    # Add detected devices
    device = capabilities.get("device")
    if device and hwaccel == "vaapi":
        result["devices"]["vaapi"].append({"path": device})

    # Set recommended method and device
    if hwaccel:
        result["recommended"]["method"] = hwaccel
        result["recommended"]["device"] = device

    logger.info(f"Hardware acceleration methods detected: {', '.join(result['methods']) or 'None'}")
    logger.info(f"Recommended method: {result['recommended']['method'] or 'None'}")

    return result


def cancel_job(job_id: str) -> bool:
    """Cancel a transcoding job.

    Returns:
        bool: True if the job was cancelled, False otherwise.
    """
    job = get_job(job_id)
    if not job:
        logger.warning(f"Attempted to cancel non-existent job: {job_id}")
        return False

    # Check if the job is pending
    is_pending = False
    with job._lock:
        is_pending = job.status == "pending"

    if is_pending:
        # Check if job is in the queue with thread safety
        job_found = False
        job_index = -1

        with JOB_QUEUE_LOCK:
            for i, queued_job in enumerate(JOB_QUEUE):
                if queued_job["job_id"] == job_id:
                    # Mark index for removal
                    job_index = i
                    job_found = True
                    break

            # Remove from queue if found (still inside the lock)
            if job_index >= 0:
                JOB_QUEUE.pop(job_index)

        # Update job status if found in queue
        if job_found:
            job.update_status("cancelled")
            logger.info(f"Removed job {job_id} from queue")
            return True

    # Check if the job is active
    if not job.is_active:
        logger.warning(f"Attempted to cancel job {job_id} with status {job.status}")
        return False

    logger.info(f"Cancelling job {job_id}")
    job.update_status("cancelled")

    # If the job has a process ID, try to terminate it directly
    process_id = None
    with job._lock:
        process_id = job.process_id

    if process_id:
        try:
            os.kill(process_id, signal.SIGTERM)
            logger.info(f"Sent SIGTERM to process {process_id}")
        except (ProcessLookupError, PermissionError) as e:
            logger.warning(f"Could not terminate process {process_id}: {str(e)}")

    return True


def remove_job(job_id: str) -> bool:
    """Remove a job from the jobs list.

    This function should only be used for completed, failed, or cancelled jobs.

    Args:
        job_id: The ID of the job to remove

    Returns:
        bool: True if the job was removed, False otherwise
    """
    job = get_job(job_id)
    if not job:
        logger.warning(f"Attempted to remove non-existent job: {job_id}")
        return False

    # Only allow removing completed, failed, or cancelled jobs
    # Use thread-safe access to job status
    with job._lock:
        job_status = job.status
        is_removable = job_status in ["completed", "failed", "cancelled"]

    if not is_removable:
        logger.warning(f"Attempted to remove job {job_id} with status {job_status}")
        return False

    # Remove the job from the global jobs dictionary with thread safety
    try:
        with JOBS_LOCK:
            if job_id in JOBS:
                del JOBS[job_id]
                logger.info(f"Removed job {job_id} with status {job_status}")
                return True
            else:
                logger.warning(f"Failed to remove job {job_id}: Job not found in dictionary")
                return False
    except Exception as e:
        logger.warning(f"Failed to remove job {job_id}: {str(e)}")
        return False
