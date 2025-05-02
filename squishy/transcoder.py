"""Media transcoding functionality."""

import os
import uuid
import threading
import logging
import subprocess
import re
import json
import datetime
import select
import signal
from typing import Dict, Optional, List, Callable, Any

from squishy.config import TranscodeProfile, load_config
from squishy.models import TranscodeJob, MediaItem, Movie, Episode
from squishy.scanner import get_media

# Configure logging
logger = logging.getLogger(__name__)

# In-memory job store
JOBS: Dict[str, TranscodeJob] = {}

# Job queue for pending jobs
JOB_QUEUE: List[Dict] = []

# Currently running jobs
RUNNING_JOBS = set()


def create_job(media_item: MediaItem, profile_name: str) -> TranscodeJob:
    """Create a new transcoding job."""
    logger.debug(
        f"Creating transcoding job for media_id={media_item.id} with profile={profile_name}"
    )
    job_id = str(uuid.uuid4())
    job = TranscodeJob(
        id=job_id,
        media_id=media_item.id,
        profile_name=profile_name,
        status="pending",
    )
    JOBS[job_id] = job
    logger.debug(f"Created job with id={job_id}")
    return job


def get_job(job_id: str) -> Optional[TranscodeJob]:
    """Get a job by ID."""
    logger.debug(f"Getting job with id={job_id}")
    return JOBS.get(job_id)


def get_running_job_count():
    """Get the number of currently running jobs."""
    return len([j for j in JOBS.values() if j.status == "processing"])


def get_pending_jobs():
    """Get a list of all pending jobs from the JOBS dictionary."""
    return [j for j in JOBS.values() if j.status == "pending"]


def process_job_queue():
    """Process the job queue based on the concurrency limit."""
    config = load_config()
    max_jobs = config.max_concurrent_jobs

    # Check if we can start more jobs
    current_running = get_running_job_count()
    available_slots = max(0, max_jobs - current_running)

    logger.debug(
        f"Processing job queue: current_running={current_running}, max_jobs={max_jobs}, available_slots={available_slots}, queue_length={len(JOB_QUEUE)}"
    )

    # Also check for any pending jobs in the JOBS dictionary that might not be in the queue
    pending_jobs = get_pending_jobs()
    logger.debug(f"Found {len(pending_jobs)} pending jobs in the JOBS dictionary")

    # First handle jobs in the JOB_QUEUE
    if available_slots > 0 and JOB_QUEUE:
        logger.debug(f"Starting up to {available_slots} jobs from queue")
        # Get the next job(s) from the queue
        jobs_to_start = min(available_slots, len(JOB_QUEUE))
        for _ in range(jobs_to_start):
            if not JOB_QUEUE:
                break

            job_data = JOB_QUEUE.pop(0)
            job_id = job_data["job_id"]
            media_item = job_data["media_item"]
            profile = job_data["profile"]
            output_dir = job_data["output_dir"]

            job = get_job(job_id)
            if job and job.status == "pending":
                # Start the job
                _start_transcode_job(job, media_item, profile, output_dir)
                logger.debug(
                    f"Started queued job {job_id}, {len(JOB_QUEUE)} jobs remaining in queue"
                )
                available_slots -= 1
            else:
                logger.warning(
                    f"Job {job_id} in queue is not in pending state or doesn't exist anymore"
                )

    # If we still have available slots and there are pending jobs not in the queue,
    # we need to find the media items and profiles to start them
    if available_slots > 0 and pending_jobs:
        logger.debug(
            f"Looking for pending jobs not in the queue: available_slots={available_slots}, pending_jobs={len(pending_jobs)}"
        )

        # Get the list of job IDs already in the queue
        queued_job_ids = [job_data["job_id"] for job_data in JOB_QUEUE]

        # Find the pending jobs not in the queue
        for job in pending_jobs:
            # Skip if job is already in the queue
            if job.id in queued_job_ids:
                continue

            # Get the media item and profile
            config = load_config()

            media_item = get_media(job.media_id)
            if not media_item:
                logger.warning(
                    f"Media item {job.media_id} for pending job {job.id} not found"
                )
                continue

            if job.profile_name not in config.profiles:
                logger.warning(
                    f"Profile {job.profile_name} for pending job {job.id} not found"
                )
                continue

            profile = config.profiles[job.profile_name]
            output_dir = config.transcode_path

            # Start the job
            _start_transcode_job(job, media_item, profile, output_dir)
            logger.debug(f"Started pending job {job.id} that was not in queue")

            available_slots -= 1
            if available_slots <= 0:
                break


def start_transcode(
    job: TranscodeJob, media_item: MediaItem, profile: TranscodeProfile, output_dir: str
):
    """Start or queue a transcoding job based on concurrency limits."""
    logger.debug(
        f"Starting transcode job={job.id} for media={media_item.id}, profile={profile.name}"
    )
    logger.debug(
        f"Profile settings: resolution={profile.resolution}, codec={profile.codec}, "
        f"container={profile.container}, quality={profile.quality}, bitrate={profile.bitrate}"
    )

    config = load_config()
    max_jobs = config.max_concurrent_jobs

    # Check if we can start the job immediately
    current_running = get_running_job_count()

    if current_running < max_jobs:
        # Start the job immediately
        _start_transcode_job(job, media_item, profile, output_dir)
        logger.debug(f"Started job {job.id} immediately")
    else:
        # Queue the job
        JOB_QUEUE.append(
            {
                "job_id": job.id,
                "media_item": media_item,
                "profile": profile,
                "output_dir": output_dir,
            }
        )
        logger.debug(f"Queued job {job.id}, position in queue: {len(JOB_QUEUE)}")


def _start_transcode_job(
    job: TranscodeJob, media_item: MediaItem, profile: TranscodeProfile, output_dir: str
):
    """Internal function to start a transcoding job."""
    # Add to running jobs set
    RUNNING_JOBS.add(job.id)

    # Define a callback for when the job finishes
    def job_finished_callback():
        # Remove from running jobs
        if job.id in RUNNING_JOBS:
            RUNNING_JOBS.remove(job.id)

        # Process the queue to see if we can start more jobs
        process_job_queue()

    # Start the job in a thread
    threading.Thread(
        target=transcode_thread,
        args=(job, media_item, profile, output_dir, job_finished_callback),
        daemon=True,
    ).start()

    logger.debug(f"Started transcoding thread for job {job.id}")


def transcode_thread(
    job: TranscodeJob,
    media_item: MediaItem,
    profile: TranscodeProfile,
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

        transcode(job, media_item, profile, output_dir)

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


def build_ffmpeg_command(
    ffmpeg_path: str,
    input_path: str,
    output_path: str,
    width: int,
    height: int,
    profile: TranscodeProfile,
    hw_accel: str = None,
    hw_device: str = None,
    use_hw_scaling: bool = True,
):
    """Build FFmpeg command with appropriate settings."""
    cmd = [ffmpeg_path]

    # Add hardware acceleration options if available
    if hw_accel:
        logger.debug(f"Using hardware acceleration: {hw_accel}")

        if hw_accel in ["cuda", "nvenc"]:
            cmd.extend(["-hwaccel", "cuda"])
            if hw_device:
                cmd.extend(["-hwaccel_device", hw_device])
        elif hw_accel == "vaapi":
            cmd.extend(["-hwaccel", "vaapi"])
            if hw_device:
                cmd.extend(["-vaapi_device", hw_device])
            else:
                cmd.extend(["-vaapi_device", "/dev/dri/renderD128"])

            # Add hwaccel output format before input for VAAPI
            cmd.extend(["-hwaccel_output_format", "vaapi"])
        elif hw_accel == "videotoolbox":
            cmd.extend(["-hwaccel", "videotoolbox"])
        elif hw_accel == "amf":
            cmd.extend(["-hwaccel", "amf"])
        else:
            # QSV and other non-working methods fall back to VAAPI on this system
            logger.warning(
                f"Hardware acceleration method {hw_accel} may not be compatible, trying VAAPI instead"
            )
            cmd.extend(["-hwaccel", "vaapi"])
            cmd.extend(["-vaapi_device", "/dev/dri/renderD128"])
            cmd.extend(["-hwaccel_output_format", "vaapi"])
            hw_accel = "vaapi"

    # Add input file
    cmd.extend(["-i", input_path])

    # Add video scaling filter
    if use_hw_scaling and hw_accel == "vaapi":
        cmd.extend(["-vf", f"scale_vaapi=w={width}:h={height}"])
    elif use_hw_scaling and hw_accel in ["cuda", "nvenc"]:
        cmd.extend(["-vf", f"scale_cuda=w={width}:h={height}"])
    else:
        cmd.extend(["-vf", f"scale={width}:{height}"])

    # Add video codec and options based on codec and hardware accel
    if profile.codec == "h264":
        if hw_accel == "nvenc":
            cmd.extend(["-c:v", "h264_nvenc"])
            # Use presets instead of CRF for NVENC
            preset = (
                "p7"
                if profile.quality == "high"
                else "p5"
                if profile.quality == "medium"
                else "p3"
            )
            cmd.extend(["-preset", preset])
        elif hw_accel == "qsv":
            cmd.extend(["-c:v", "h264_qsv"])
            # Set QSV parameters
            bitrate = (
                "5M"
                if profile.quality == "high"
                else "3M"
                if profile.quality == "medium"
                else "1.5M"
            )
            cmd.extend(["-b:v", bitrate, "-maxrate", bitrate])
        elif hw_accel == "vaapi":
            cmd.extend(["-c:v", "h264_vaapi"])
            # VAAPI quality targets
            qp = (
                "18"
                if profile.quality == "high"
                else "23"
                if profile.quality == "medium"
                else "28"
            )
            cmd.extend(["-qp", qp])
            cmd.extend(["-low_power", "1"])
        elif hw_accel == "videotoolbox":
            cmd.extend(["-c:v", "h264_videotoolbox"])
            # VideoToolbox quality
            q = (
                "50"
                if profile.quality == "high"
                else "70"
                if profile.quality == "medium"
                else "90"
            )
            cmd.extend(["-q:v", q])
        elif hw_accel == "amf":
            cmd.extend(["-c:v", "h264_amf"])
            # AMF quality settings
            if profile.quality == "high":
                cmd.extend(["-quality", "quality", "-qp_i", "18", "-qp_p", "20"])
            elif profile.quality == "medium":
                cmd.extend(["-quality", "balanced", "-qp_i", "22", "-qp_p", "24"])
            else:  # low
                cmd.extend(["-quality", "speed", "-qp_i", "26", "-qp_p", "28"])
        else:
            # Software encoding
            cmd.extend(["-c:v", "libx264"])
            crf = (
                "18"
                if profile.quality == "high"
                else "22"
                if profile.quality == "medium"
                else "28"
            )
            cmd.extend(["-crf", crf])
    elif profile.codec == "hevc":
        if hw_accel == "nvenc":
            cmd.extend(["-c:v", "hevc_nvenc"])
            # Use presets instead of CRF for NVENC
            preset = (
                "p7"
                if profile.quality == "high"
                else "p5"
                if profile.quality == "medium"
                else "p3"
            )
            cmd.extend(["-preset", preset])
        elif hw_accel == "qsv":
            cmd.extend(["-c:v", "hevc_qsv"])
            # Set QSV parameters
            bitrate = (
                "4M"
                if profile.quality == "high"
                else "2.5M"
                if profile.quality == "medium"
                else "1M"
            )
            cmd.extend(["-b:v", bitrate, "-maxrate", bitrate])
        elif hw_accel == "vaapi":
            cmd.extend(["-c:v", "hevc_vaapi"])
            # VAAPI quality targets
            qp = (
                "22"
                if profile.quality == "high"
                else "26"
                if profile.quality == "medium"
                else "32"
            )
            cmd.extend(["-qp", qp])
            cmd.extend(["-low_power", "1"])
        elif hw_accel == "videotoolbox":
            cmd.extend(["-c:v", "hevc_videotoolbox"])
            # VideoToolbox quality
            q = (
                "50"
                if profile.quality == "high"
                else "70"
                if profile.quality == "medium"
                else "90"
            )
            cmd.extend(["-q:v", q])
        elif hw_accel == "amf":
            cmd.extend(["-c:v", "hevc_amf"])
            # AMF quality settings
            if profile.quality == "high":
                cmd.extend(["-quality", "quality", "-qp_i", "22", "-qp_p", "24"])
            elif profile.quality == "medium":
                cmd.extend(["-quality", "balanced", "-qp_i", "26", "-qp_p", "28"])
            else:  # low
                cmd.extend(["-quality", "speed", "-qp_i", "30", "-qp_p", "32"])
        else:
            # Software encoding
            cmd.extend(["-c:v", "libx265"])
            crf = (
                "22"
                if profile.quality == "high"
                else "26"
                if profile.quality == "medium"
                else "32"
            )
            cmd.extend(["-crf", crf])
    elif profile.codec == "av1":
        # Currently no HW acceleration support for AV1 encoding
        cmd.extend(["-c:v", "libsvtav1"])
        crf = (
            "24"
            if profile.quality == "high"
            else "30"
            if profile.quality == "medium"
            else "36"
        )
        cmd.extend(["-crf", crf])
    else:
        logger.warning(f"Unknown codec specified: {profile.codec}, defaulting to h264")
        cmd.extend(["-c:v", "libx264", "-crf", "22"])

    # Set bitrate if specified
    if profile.bitrate:
        cmd.extend(["-b:v", profile.bitrate])

    # Set audio codec
    cmd.extend(["-c:a", "aac", "-b:a", "128k"])

    # Add output path
    cmd.extend(["-y", output_path])

    # Add progress monitoring
    cmd.extend(["-progress", "pipe:1"])

    return cmd


def build_alternative_vaapi_command(
    ffmpeg_path: str,
    media_item: MediaItem,
    output_path: str,
    width: int,
    height: int,
    profile: TranscodeProfile,
    hw_device: str = None,
):
    """Build alternative command for VAAPI encoding."""
    alt_cmd = [ffmpeg_path, "-hwaccel", "vaapi"]

    # Add device if available
    if hw_device:
        alt_cmd.extend(["-vaapi_device", hw_device])
    else:
        alt_cmd.extend(["-vaapi_device", "/dev/dri/renderD128"])

    # Add input file
    alt_cmd.extend(["-i", media_item.path])

    # Use alternative filter chain
    alt_cmd.extend(
        [
            "-vf",
            f"format=nv12,hwupload,scale_vaapi=w={width}:h={height}:format=nv12",
        ]
    )

    # Add codec
    if profile.codec == "h264":
        alt_cmd.extend(["-c:v", "h264_vaapi"])
        qp = (
            "18"
            if profile.quality == "high"
            else "23"
            if profile.quality == "medium"
            else "28"
        )
        alt_cmd.extend(["-qp", qp])
    elif profile.codec == "hevc":
        alt_cmd.extend(["-c:v", "hevc_vaapi"])
        qp = (
            "22"
            if profile.quality == "high"
            else "26"
            if profile.quality == "medium"
            else "32"
        )
        alt_cmd.extend(["-qp", qp])
    else:
        # Default to H.264
        alt_cmd.extend(["-c:v", "h264_vaapi", "-qp", "23"])

    # Add low_power setting
    alt_cmd.extend(["-low_power", "1"])

    # Add audio codec settings
    alt_cmd.extend(["-c:a", "aac", "-b:a", "128k"])

    # Add output file
    alt_cmd.extend(["-y", output_path])

    # Add progress monitoring
    alt_cmd.extend(["-progress", "pipe:1"])

    return alt_cmd


def build_hybrid_command(
    ffmpeg_path: str,
    media_item: MediaItem,
    output_path: str,
    width: int,
    height: int,
    profile: TranscodeProfile,
    hw_device: str = None,
):
    """Build hybrid command with hardware decode but software encode."""
    hybrid_cmd = [ffmpeg_path, "-hwaccel", "vaapi"]

    # Add device if available
    if hw_device:
        hybrid_cmd.extend(["-vaapi_device", hw_device])
    else:
        hybrid_cmd.extend(["-vaapi_device", "/dev/dri/renderD128"])

    # Add input file
    hybrid_cmd.extend(["-i", media_item.path])

    # Use software scaling
    hybrid_cmd.extend(["-vf", f"scale={width}:{height}"])

    # Use software encoder
    if profile.codec == "h264":
        hybrid_cmd.extend(["-c:v", "libx264"])
        crf = (
            "18"
            if profile.quality == "high"
            else "22"
            if profile.quality == "medium"
            else "28"
        )
        hybrid_cmd.extend(["-crf", crf])
    elif profile.codec == "hevc":
        hybrid_cmd.extend(["-c:v", "libx265"])
        crf = (
            "22"
            if profile.quality == "high"
            else "26"
            if profile.quality == "medium"
            else "32"
        )
        hybrid_cmd.extend(["-crf", crf])
    else:
        hybrid_cmd.extend(["-c:v", "libx264", "-crf", "23"])

    # Add audio codec settings
    hybrid_cmd.extend(["-c:a", "aac", "-b:a", "128k"])

    # Add output file
    hybrid_cmd.extend(["-y", output_path])

    # Add progress monitoring
    hybrid_cmd.extend(["-progress", "pipe:1"])

    return hybrid_cmd


def build_software_command(
    ffmpeg_path: str,
    media_item: MediaItem,
    output_path: str,
    width: int,
    height: int,
    profile: TranscodeProfile,
):
    """Build pure software encoding command."""
    sw_cmd = [ffmpeg_path, "-i", media_item.path]

    # Add software video filter for scaling
    sw_cmd.extend(["-vf", f"scale={width}:{height}"])

    # Use software codec
    if profile.codec == "h264":
        sw_cmd.extend(["-c:v", "libx264"])
        crf = (
            "18"
            if profile.quality == "high"
            else "22"
            if profile.quality == "medium"
            else "28"
        )
        sw_cmd.extend(["-crf", crf])
    elif profile.codec == "hevc":
        sw_cmd.extend(["-c:v", "libx265"])
        crf = (
            "22"
            if profile.quality == "high"
            else "26"
            if profile.quality == "medium"
            else "32"
        )
        sw_cmd.extend(["-crf", crf])
    else:
        sw_cmd.extend(["-c:v", "libx264", "-crf", "23"])

    # Add audio codec settings
    sw_cmd.extend(["-c:a", "aac", "-b:a", "128k"])

    # Add output file
    sw_cmd.extend(["-y", output_path])

    # Add progress monitoring
    sw_cmd.extend(["-progress", "pipe:1"])

    return sw_cmd


def run_ffmpeg_process(
    cmd: List[str], job: TranscodeJob, output_path: str, max_log_lines: int = 1000
):
    """Run FFmpeg process with progress monitoring."""
    # Log the command
    cmd_str = " ".join(cmd)
    logger.debug(f"FFmpeg command: {cmd_str}")
    job.ffmpeg_command = cmd_str

    # Create the process
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        shell=False,
        encoding="utf-8",
        errors="replace",
    )

    # Store process ID for potential cancellation
    job.process_id = process.pid
    logger.debug(f"Process ID for job {job.id}: {job.process_id}")

    # Create a queue for log lines
    log_lines = []

    # Monitor progress
    while process.poll() is None:
        # Check if job has been cancelled
        if job.status == "cancelled":
            logger.info(f"Job {job.id} has been cancelled, terminating process")
            process.terminate()
            break

        # Use non-blocking reads from stdout & stderr
        ready_to_read, _, _ = select.select(
            [process.stdout, process.stderr], [], [], 0.1
        )

        for stream in ready_to_read:
            if stream == process.stdout:
                stdout_line = stream.readline().strip()
                if stdout_line:
                    # Parse progress information
                    if stdout_line.startswith("out_time_ms="):
                        try:
                            time_ms = int(stdout_line.split("=")[1])
                            current_time = (
                                time_ms / 1000000
                            )  # Convert microseconds to seconds
                            job.current_time = current_time

                            if job.duration:
                                job.progress = min(current_time / job.duration, 0.99)
                                logger.debug(f"Progress: {job.progress:.2%}")

                                # Import here to avoid circular imports - emit progress every 2 seconds
                                if int(current_time) % 2 == 0:
                                    from squishy.socket_events import emit_job_update

                                    emit_job_update(
                                        {
                                            "id": job.id,
                                            "media_id": job.media_id,
                                            "status": job.status,
                                            "progress": job.progress,
                                            "current_time": job.current_time,
                                            "duration": job.duration,
                                            "output_size": job.output_size,
                                        }
                                    )
                        except (ValueError, IndexError) as e:
                            logger.warning(f"Error parsing time: {str(e)}")

                    # Store the line in logs
                    log_lines.append(f"STDOUT: {stdout_line}")
                    if len(log_lines) > max_log_lines:
                        log_lines.pop(0)

            elif stream == process.stderr:
                stderr_line = stream.readline().strip()
                if stderr_line:
                    # Store the line in logs
                    log_lines.append(f"STDERR: {stderr_line}")
                    if len(log_lines) > max_log_lines:
                        log_lines.pop(0)

        # Update job logs
        job.ffmpeg_logs = log_lines

        # Check output file size
        if os.path.exists(output_path):
            output_size = os.path.getsize(output_path)
            job.output_size = format_file_size(output_size)

        # Check if process might be stuck (hanging)
        if (
            hasattr(job, "last_progress_time")
            and job.current_time
            and job.last_progress_time == job.current_time
        ):
            job.progress_stalled_count = getattr(job, "progress_stalled_count", 0) + 1

            # If we've been at the same timestamp for multiple consecutive checks
            if job.progress_stalled_count > 300:
                # Check process status
                process_status = get_process_status(process.pid)
                logger.warning(
                    f"Process {process.pid} appears stalled at {job.current_time}s with status {process_status}"
                )

                # Only terminate if the process is a zombie or has been stalled for a very long time
                # And if we have no file growth at all (real stall, not just slow encoding)
                if process_status == "Z" or job.progress_stalled_count > 600:
                    file_growing = False

                    # Check if output file exists and is growing
                    if os.path.exists(output_path):
                        current_size = os.path.getsize(output_path)
                        # Store last size if we haven't already
                        if not hasattr(job, "last_file_size"):
                            job.last_file_size = current_size
                        # Check if file is growing
                        elif current_size > job.last_file_size:
                            file_growing = True
                            job.last_file_size = current_size

                    # Only kill the process if it's a zombie or the file isn't growing at all
                    if process_status == "Z" or (
                        job.progress_stalled_count > 600 and not file_growing
                    ):
                        logger.error(
                            f"Killing stalled process {process.pid} after {job.progress_stalled_count} checks"
                        )
                        try:
                            os.kill(process.pid, signal.SIGKILL)
                            process.poll()  # Force update the returncode
                        except Exception as e:
                            logger.error(f"Error killing process: {str(e)}")
                        break
        else:
            # Reset stall counter if progress has changed
            job.progress_stalled_count = 0

        # Store last progress time for stall detection
        if job.current_time:
            job.last_progress_time = job.current_time

    # Get the final output
    stdout, stderr = process.communicate()

    # Add final output to logs
    for line in stdout.splitlines():
        if line.strip():
            log_lines.append(f"STDOUT: {line.strip()}")

    for line in stderr.splitlines():
        if line.strip():
            log_lines.append(f"STDERR: {line.strip()}")

    # Update job logs one last time
    job.ffmpeg_logs = (
        log_lines[-max_log_lines:] if len(log_lines) > max_log_lines else log_lines
    )

    return process.returncode, stdout, stderr


def detect_hw_accel_error(stderr: str) -> bool:
    """Detect hardware acceleration failure."""
    hw_error_patterns = [
        "No usable encoding profile found",
        "Error initializing output stream",
        "Invalid hardware device ",
        "Cannot load hwaccel",
        "Failed to set value",
        "Device creation failed",
        "Cannot open the hardware device",
        "Failed to open VAAPI device",
        "Error initializing an internal frame pool",
    ]

    for pattern in hw_error_patterns:
        if pattern in stderr:
            return True
    return False


def transcode(
    job: TranscodeJob, media_item: MediaItem, profile: TranscodeProfile, output_dir: str
):
    """Perform the transcoding."""
    try:
        job.status = "processing"
        logger.debug(f"Job {job.id} status changed to processing")

        # Get original filename without extension
        original_filename = os.path.basename(media_item.path)
        filename_without_ext, _ = os.path.splitext(original_filename)

        # Create output filename with profile name in parentheses
        output_filename = f"{filename_without_ext} ({profile.name}).{profile.container}"
        output_path = os.path.join(output_dir, output_filename)
        logger.debug(f"Output path: {output_path}")

        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        logger.debug(f"Ensured output directory exists: {output_dir}")

        # Get ffmpeg path from config
        config = load_config()
        ffmpeg_path = config.ffmpeg_path
        logger.debug(f"Using ffmpeg from: {ffmpeg_path}")

        # Check if input file exists
        if not os.path.exists(media_item.path):
            raise FileNotFoundError(f"Input file not found: {media_item.path}")

        # Parse resolution
        logger.debug(f"Parsing resolution: {profile.resolution}")
        try:
            width, height = map(int, profile.resolution.split("x"))
            logger.debug(f"Parsed width={width}, height={height}")
        except ValueError:
            logger.error(f"Invalid resolution format: {profile.resolution}")
            raise ValueError(f"Invalid resolution format: {profile.resolution}")

        # Determine hardware acceleration settings (inherit global if not set in profile)
        active_hw_accel = None
        active_hw_device = None

        # If profile has explicit hw_accel (not inherited), use it
        if profile.hw_accel and profile.hw_accel != "inherit":
            logger.debug(
                f"Using profile-specific hardware acceleration: {profile.hw_accel}"
            )
            active_hw_accel = profile.hw_accel
            active_hw_device = profile.hw_device
        # Otherwise, if global hw_accel is set, use that
        elif config.hw_accel:
            logger.debug(f"Using global hardware acceleration: {config.hw_accel}")
            active_hw_accel = config.hw_accel
            active_hw_device = config.hw_device

        # Default to VAAPI if no acceleration specified
        if not active_hw_accel:
            active_hw_accel = "vaapi"
            active_hw_device = "/dev/dri/renderD128"  # Default VAAPI device
            logger.debug(f"Using default VAAPI hardware acceleration")

        # Get media duration
        duration = get_media_duration(ffmpeg_path, media_item.path)
        if duration:
            job.duration = duration
            logger.debug(f"Media duration: {duration} seconds")

        # Build initial command with hardware acceleration
        cmd = build_ffmpeg_command(
            ffmpeg_path,
            media_item.path,
            output_path,
            width,
            height,
            profile,
            active_hw_accel,
            active_hw_device,
            True,
        )

        # Run the transcoding
        logger.debug(f"Starting FFmpeg process for job {job.id}")
        returncode, stdout, stderr = run_ffmpeg_process(cmd, job, output_path)

        # Check if job was cancelled
        if job.status == "cancelled":
            logger.info(f"Job {job.id} was cancelled")
            return

        if returncode != 0:
            logger.error(f"FFmpeg process failed with return code {returncode}")
            logger.error(f"FFmpeg stderr: {stderr}")

            # Check if this was a hardware acceleration failure
            hw_accel_error = detect_hw_accel_error(stderr)

            # Check if the profile allows hardware acceleration failover
            allow_failover = profile.allow_hw_failover

            # Handle hardware acceleration failures with fallback approaches
            if hw_accel_error and active_hw_accel and allow_failover:
                # First try alternate method based on current acceleration
                if active_hw_accel == "vaapi":
                    # Try alternate VAAPI approach
                    logger.warning(
                        "Standard VAAPI acceleration failed, trying alternate VAAPI approach"
                    )
                    job.ffmpeg_logs.append(
                        "NOTICE: Standard VAAPI encoding failed, trying alternate VAAPI approach..."
                    )

                    # Create and run alternate VAAPI command
                    alt_cmd = build_alternative_vaapi_command(
                        ffmpeg_path,
                        media_item,
                        output_path,
                        width,
                        height,
                        profile,
                        active_hw_device,
                    )

                    logger.info(
                        f"Trying alternate VAAPI encoding approach for job {job.id}"
                    )
                    alt_returncode, alt_stdout, alt_stderr = run_ffmpeg_process(
                        alt_cmd, job, output_path
                    )

                    # Check if job was cancelled
                    if job.status == "cancelled":
                        logger.info(
                            f"Alternate VAAPI encoding job {job.id} was cancelled"
                        )
                        return

                    # If alternate method succeeded, we're done
                    if alt_returncode == 0:
                        logger.info(
                            f"Successfully used alternate VAAPI approach for job {job.id}"
                        )
                        job.ffmpeg_logs.append(
                            "SUCCESS: Alternate VAAPI approach worked successfully for HDR content"
                        )
                        # Update job status
                        job.status = "completed"
                        job.progress = 1.0
                        job.output_path = output_path
                        if os.path.exists(output_path):
                            output_size = os.path.getsize(output_path)
                            job.output_size = format_file_size(output_size)
                        return

                # If we're here, try hybrid approach (HW decode + SW encode) for VAAPI
                if active_hw_accel == "vaapi":
                    logger.warning(
                        "Both standard and alternate VAAPI encoding approaches failed, trying HW decode + SW encode"
                    )
                    job.ffmpeg_logs.append(
                        "NOTICE: Both VAAPI encoding methods failed, trying hardware decode + software encode as last resort before full software mode..."
                    )

                    # Create and run hybrid command
                    hybrid_cmd = build_hybrid_command(
                        ffmpeg_path,
                        media_item,
                        output_path,
                        width,
                        height,
                        profile,
                        active_hw_device,
                    )

                    logger.info(
                        f"Trying hybrid hardware decode + software encode for job {job.id}"
                    )
                    hybrid_returncode, hybrid_stdout, hybrid_stderr = (
                        run_ffmpeg_process(hybrid_cmd, job, output_path)
                    )

                    # Check if job was cancelled
                    if job.status == "cancelled":
                        logger.info(f"Hybrid encoding job {job.id} was cancelled")
                        return

                    # If hybrid approach succeeded, we're done
                    if hybrid_returncode == 0:
                        logger.info(
                            f"Hybrid hardware decode + software encode succeeded for job {job.id}"
                        )
                        # Update job status
                        job.status = "completed"
                        job.progress = 1.0
                        job.output_path = output_path
                        if os.path.exists(output_path):
                            output_size = os.path.getsize(output_path)
                            job.output_size = format_file_size(output_size)
                        return

                # Last resort - pure software encoding
                logger.warning(
                    f"All hardware acceleration attempts with {active_hw_accel} failed, falling back to pure software encoding"
                )
                if active_hw_accel == "vaapi":
                    job.ffmpeg_logs.append(
                        "NOTICE: All VAAPI approaches failed, falling back to pure software encoding..."
                    )
                else:
                    job.ffmpeg_logs.append(
                        f"NOTICE: Hardware acceleration with {active_hw_accel} failed, falling back to software encoding..."
                    )

                # Create and run software-only command
                sw_cmd = build_software_command(
                    ffmpeg_path, media_item, output_path, width, height, profile
                )

                logger.info(f"Retrying with software encoding for job {job.id}")
                sw_returncode, sw_stdout, sw_stderr = run_ffmpeg_process(
                    sw_cmd, job, output_path
                )

                # Check if job was cancelled
                if job.status == "cancelled":
                    logger.info(f"Software encoding job {job.id} was cancelled")
                    return

                # Check if software encoding succeeded
                if sw_returncode != 0:
                    logger.error(
                        f"Software encoding also failed with return code {sw_returncode}"
                    )
                    logger.error(f"FFmpeg stderr: {sw_stderr}")
                    raise RuntimeError(
                        f"Both hardware acceleration and software encoding failed for job {job.id}"
                    )
                else:
                    # Software encoding succeeded
                    logger.info(
                        f"Software encoding succeeded after hardware acceleration failed for job {job.id}"
                    )
            elif hw_accel_error and active_hw_accel and not allow_failover:
                # Hardware acceleration failed and failover not allowed
                err_msg = f"Hardware acceleration with {active_hw_accel} failed and failover to software is not allowed by profile"
                logger.error(err_msg)
                job.ffmpeg_logs.append(f"ERROR: {err_msg}")
                raise RuntimeError(err_msg)
            else:
                # Not a hardware acceleration error or no hardware acceleration was used
                raise RuntimeError(f"FFmpeg failed with return code {returncode}")

        logger.debug(f"FFmpeg process completed successfully for job {job.id}")

        # Update job status
        job.status = "completed"
        job.progress = 1.0
        job.output_path = output_path

        # Get final output file size
        if os.path.exists(output_path):
            output_size = os.path.getsize(output_path)
            job.output_size = format_file_size(output_size)

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
            "profile_name": profile.name,
            "completed_at": datetime.datetime.now().isoformat(),
            "output_size": job.output_size,
            "duration": job.duration,
        }

        # Add TV show specific metadata if applicable
        if isinstance(media_item, Episode):
            metadata["show_id"] = media_item.show_id
            metadata["season_number"] = media_item.season_number
            metadata["episode_number"] = media_item.episode_number

        # Write metadata to sidecar file
        with open(sidecar_path, "w") as f:
            json.dump(metadata, f, indent=2)

        logger.debug(f"Created metadata sidecar file: {sidecar_path}")

    except Exception as e:
        logger.error(f"Transcoding job {job.id} failed: {str(e)}", exc_info=True)
        job.status = "failed"
        job.error_message = str(e)

        # Make sure to capture final error messages in logs
        if hasattr(e, "stderr") and e.stderr:
            for line in e.stderr.splitlines():
                if line.strip():
                    job.ffmpeg_logs.append(f"STDERR: {line.strip()}")


def get_media_duration(ffmpeg_path: str, input_path: str) -> Optional[float]:
    """Get the duration of a media file in seconds."""
    try:
        cmd = [ffmpeg_path, "-i", input_path]
        result = subprocess.run(
            cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True
        )

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
    """Detect available hardware acceleration methods.

    Returns:
        Dict containing available HW acceleration methods and devices.
    """
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

    logger.debug("Detecting available hardware acceleration methods...")

    # Check FFmpeg version and codecs
    try:
        # Get FFmpeg version info
        version_cmd = [ffmpeg_path, "-version"]
        version_output = subprocess.check_output(
            version_cmd, stderr=subprocess.STDOUT, text=True
        )
        logger.debug(
            f"FFmpeg version: {version_output.splitlines()[0] if version_output.splitlines() else 'unknown'}"
        )

        # Get available encoders
        encoders_cmd = [ffmpeg_path, "-encoders"]
        encoders_output = subprocess.check_output(
            encoders_cmd, stderr=subprocess.STDOUT, text=True
        )

        # Check for hardware encoder presence
        if re.search(r"h264_nvenc", encoders_output):
            result["methods"].append("nvenc")
        if re.search(r"hevc_nvenc", encoders_output):
            if "nvenc" not in result["methods"]:
                result["methods"].append("nvenc")
        if re.search(r"h264_qsv", encoders_output):
            result["methods"].append("qsv")
        if re.search(r"hevc_qsv", encoders_output):
            if "qsv" not in result["methods"]:
                result["methods"].append("qsv")
        if re.search(r"h264_vaapi", encoders_output):
            result["methods"].append("vaapi")
        if re.search(r"h264_videotoolbox", encoders_output):
            result["methods"].append("videotoolbox")
        if re.search(r"h264_amf", encoders_output):
            result["methods"].append("amf")

        # Check for -hwaccel support
        hwaccels_cmd = [ffmpeg_path, "-hwaccels"]
        try:
            hwaccels_output = subprocess.check_output(
                hwaccels_cmd, stderr=subprocess.STDOUT, text=True
            )

            # Parse hwaccels output
            for line in hwaccels_output.splitlines():
                line = line.strip()
                if line and line != "Hardware acceleration methods:":
                    if line not in result["methods"]:
                        result["methods"].append(line)
        except subprocess.CalledProcessError:
            # Some FFmpeg builds don't support -hwaccels
            logger.warning("FFmpeg -hwaccels command not supported")

        # Check for CUDA devices if NVENC is available
        if "nvenc" in result["methods"] or "cuda" in result["methods"]:
            try:
                # Try to get NVIDIA device info
                nvidia_smi_cmd = [
                    "nvidia-smi",
                    "--query-gpu=name,index",
                    "--format=csv,noheader",
                ]
                nvidia_output = subprocess.check_output(
                    nvidia_smi_cmd, stderr=subprocess.PIPE, text=True
                )

                for line in nvidia_output.splitlines():
                    parts = line.strip().split(", ")
                    if len(parts) == 2:
                        name, index = parts
                        result["devices"]["cuda"].append({"name": name, "index": index})
            except (subprocess.CalledProcessError, FileNotFoundError):
                logger.warning("nvidia-smi command failed or not found")

        # Check for VAAPI devices
        if "vaapi" in result["methods"]:
            # Common VAAPI device nodes
            for device_path in ["/dev/dri/renderD128", "/dev/dri/card0"]:
                if os.path.exists(device_path):
                    result["devices"]["vaapi"].append({"path": device_path})

        # Determine recommended method
        if "vaapi" in result["methods"] and result["devices"]["vaapi"]:
            # VAAPI is the most compatible option on Linux
            result["recommended"]["method"] = "vaapi"
            result["recommended"]["device"] = result["devices"]["vaapi"][0]["path"]
        elif "nvenc" in result["methods"] and result["devices"]["cuda"]:
            # NVENC if available
            result["recommended"]["method"] = "nvenc"
            result["recommended"]["device"] = result["devices"]["cuda"][0]["index"]
        elif "videotoolbox" in result["methods"]:
            # VideoToolbox on macOS
            result["recommended"]["method"] = "videotoolbox"
        elif "amf" in result["methods"]:
            # AMD AMF
            result["recommended"]["method"] = "amf"

        logger.info(
            f"Hardware acceleration methods detected: {', '.join(result['methods']) or 'None'}"
        )
        logger.info(f"Recommended method: {result['recommended']['method'] or 'None'}")
        return result

    except Exception as e:
        logger.error(f"Error detecting hardware acceleration: {str(e)}", exc_info=True)
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

    if job.status == "pending":
        # Check if job is in the queue
        for i, queued_job in enumerate(JOB_QUEUE):
            if queued_job["job_id"] == job_id:
                # Remove from queue
                JOB_QUEUE.pop(i)
                job.status = "cancelled"
                logger.info(f"Removed job {job_id} from queue")
                return True

    if not job.is_active:
        logger.warning(f"Attempted to cancel job {job_id} with status {job.status}")
        return False

    logger.info(f"Cancelling job {job_id}")
    job.status = "cancelled"

    # If the job has a process ID, try to terminate it directly
    if job.process_id:
        try:
            os.kill(job.process_id, signal.SIGTERM)
            logger.info(f"Sent SIGTERM to process {job.process_id}")
        except (ProcessLookupError, PermissionError) as e:
            logger.warning(f"Could not terminate process {job.process_id}: {str(e)}")

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
    if job.status not in ["completed", "failed", "cancelled"]:
        logger.warning(f"Attempted to remove job {job_id} with status {job.status}")
        return False

    # Remove the job from the global jobs dictionary
    try:
        del JOBS[job_id]
        logger.info(f"Removed job {job_id} with status {job.status}")
        return True
    except KeyError:
        logger.warning(f"Failed to remove job {job_id}: Job not found")
        return False
