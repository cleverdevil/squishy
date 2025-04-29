"""Media transcoding functionality."""

import os
import uuid
import threading
import logging
import subprocess
import re
import time
import json
import datetime
import select
from typing import Dict, Optional, Tuple, List, Callable, Any

from squishy.config import TranscodeProfile, load_config
from squishy.models import TranscodeJob, MediaItem
from squishy.scanner import get_media

# Configure logging
logger = logging.getLogger(__name__)
# Configure logging based on the config's log level
# We don't set level here as it's set in run.py

# In-memory job store - in a real application, this would be in a database
JOBS: Dict[str, TranscodeJob] = {}

# Job queue for pending jobs
JOB_QUEUE: List[Dict] = []

# Currently running jobs
RUNNING_JOBS = set()

def create_job(media_item: MediaItem, profile_name: str) -> TranscodeJob:
    """Create a new transcoding job."""
    logger.debug(f"Creating transcoding job for media_id={media_item.id} with profile={profile_name}")
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
    
    logger.debug(f"Processing job queue: current_running={current_running}, max_jobs={max_jobs}, available_slots={available_slots}, queue_length={len(JOB_QUEUE)}")
    
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
                logger.debug(f"Started queued job {job_id}, {len(JOB_QUEUE)} jobs remaining in queue")
                available_slots -= 1
            else:
                logger.warning(f"Job {job_id} in queue is not in pending state or doesn't exist anymore")
    
    # If we still have available slots and there are pending jobs not in the queue,
    # we need to find the media items and profiles to start them
    if available_slots > 0 and pending_jobs:
        logger.debug(f"Looking for pending jobs not in the queue: available_slots={available_slots}, pending_jobs={len(pending_jobs)}")
        
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
                logger.warning(f"Media item {job.media_id} for pending job {job.id} not found")
                continue
                
            if job.profile_name not in config.profiles:
                logger.warning(f"Profile {job.profile_name} for pending job {job.id} not found")
                continue
                
            profile = config.profiles[job.profile_name]
            output_dir = config.transcode_path
            
            # Start the job
            _start_transcode_job(job, media_item, profile, output_dir)
            logger.debug(f"Started pending job {job.id} that was not in queue")
            
            available_slots -= 1
            if available_slots <= 0:
                break

def start_transcode(job: TranscodeJob, media_item: MediaItem, profile: TranscodeProfile, output_dir: str):
    """Start or queue a transcoding job based on concurrency limits."""
    logger.debug(f"Starting transcode job={job.id} for media={media_item.id}, profile={profile.name}")
    logger.debug(f"Profile settings: resolution={profile.resolution}, codec={profile.codec}, "
                 f"container={profile.container}, quality={profile.quality}, bitrate={profile.bitrate}")
    
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
        JOB_QUEUE.append({
            "job_id": job.id,
            "media_item": media_item,
            "profile": profile,
            "output_dir": output_dir
        })
        logger.debug(f"Queued job {job.id}, position in queue: {len(JOB_QUEUE)}")

def _start_transcode_job(job: TranscodeJob, media_item: MediaItem, profile: TranscodeProfile, output_dir: str):
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
        daemon=True
    ).start()
    
    logger.debug(f"Started transcoding thread for job {job.id}")

def transcode_thread(job: TranscodeJob, media_item: MediaItem, profile: TranscodeProfile, 
                     output_dir: str, callback: Optional[Callable] = None):
    """Thread function for transcoding."""
    try:
        # Import here to avoid circular imports
        from squishy.socket_events import emit_job_update
        
        # Emit initial job state
        emit_job_update({
            "id": job.id,
            "media_id": job.media_id,
            "status": job.status,
            "progress": job.progress
        })
        
        transcode(job, media_item, profile, output_dir)
        
        # Emit final job state
        emit_job_update({
            "id": job.id,
            "media_id": job.media_id,
            "status": job.status,
            "progress": job.progress,
            "output_path": job.output_path,
            "output_size": job.output_size
        })
    finally:
        # Call the callback if provided
        if callback:
            callback()

def transcode(job: TranscodeJob, media_item: MediaItem, profile: TranscodeProfile, output_dir: str):
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
        
        # Build ffmpeg command
        cmd = [ffmpeg_path]
        
        # Determine hardware acceleration settings (inherit global if not set in profile)
        config = load_config()
        active_hw_accel = None
        active_hw_device = None
        
        # If profile has explicit hw_accel (not inherited), use it
        if profile.hw_accel and profile.hw_accel != "inherit":
            logger.debug(f"Using profile-specific hardware acceleration: {profile.hw_accel}")
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
        
        # Add hardware acceleration options if available
        has_hw_accel = False
        if active_hw_accel:
            logger.debug(f"Using hardware acceleration: {active_hw_accel}")
            
            # Add hardware acceleration flags
            if active_hw_accel in ["cuda", "nvenc"]:
                cmd.extend(["-hwaccel", "cuda"])
                has_hw_accel = True
                if active_hw_device:
                    cmd.extend(["-hwaccel_device", active_hw_device])
            elif active_hw_accel == "vaapi":
                cmd.extend(["-hwaccel", "vaapi"])
                
                # Add VAAPI-specific options before input
                if active_hw_device:
                    cmd.extend(["-vaapi_device", active_hw_device])
                else:
                    # Use default VAAPI device
                    cmd.extend(["-vaapi_device", "/dev/dri/renderD128"])
                
                # Add hwaccel output format before input for VAAPI
                cmd.extend(["-hwaccel_output_format", "vaapi"])
                
                has_hw_accel = True
            elif active_hw_accel == "videotoolbox":
                cmd.extend(["-hwaccel", "videotoolbox"])
                has_hw_accel = True
            elif active_hw_accel == "amf":
                cmd.extend(["-hwaccel", "amf"])
                has_hw_accel = True
            else:
                # QSV and other non-working methods fall back to VAAPI on this system
                logger.warning(f"Hardware acceleration method {active_hw_accel} may not be compatible, trying VAAPI instead")
                cmd.extend(["-hwaccel", "vaapi"])
                cmd.extend(["-vaapi_device", "/dev/dri/renderD128"])
                cmd.extend(["-hwaccel_output_format", "vaapi"])
                active_hw_accel = "vaapi"
                has_hw_accel = True
        
        # Add input file
        cmd.extend(["-i", media_item.path])
        
        # Add video scaling filter
        if active_hw_accel == "vaapi":
            # VAAPI hardware scaling - more efficient
            # When using -hwaccel_output_format vaapi, we only need scale_vaapi
            cmd.extend([
                "-vf", f"scale_vaapi=w={width}:h={height}"
            ])
        elif active_hw_accel in ["cuda", "nvenc"]:
            # CUDA hardware scaling - more efficient 
            cmd.extend([
                "-vf", f"scale_cuda=w={width}:h={height}"
            ])
        else:
            # Software scaling
            cmd.extend(["-vf", f"scale={width}:{height}"])
        
        # Add video codec and options based on codec and hardware accel
        if profile.codec == "h264":
            if active_hw_accel == "nvenc":
                logger.debug("Using h264 codec with NVENC")
                cmd.extend(["-c:v", "h264_nvenc"])
                # Use presets instead of CRF for NVENC
                if profile.quality == "high":
                    preset = "p7"  # Highest quality for NVENC
                elif profile.quality == "medium":
                    preset = "p5"
                else:  # low
                    preset = "p3"
                cmd.extend(["-preset", preset])
            elif active_hw_accel == "qsv":
                logger.debug("Using h264 codec with QSV")
                cmd.extend(["-c:v", "h264_qsv"])
                
                # Set QSV parameters
                if profile.quality == "high":
                    bitrate = "5M"
                elif profile.quality == "medium":
                    bitrate = "3M"
                else:  # low
                    bitrate = "1.5M"
                
                # Use bitrate control and simpler params for better compatibility
                cmd.extend(["-b:v", bitrate, "-maxrate", bitrate])
            elif active_hw_accel == "vaapi":
                logger.debug("Using h264 codec with VAAPI")
                cmd.extend(["-c:v", "h264_vaapi"])
                
                # VAAPI quality targets
                if profile.quality == "high":
                    cmd.extend(["-qp", "18"])
                elif profile.quality == "medium":
                    cmd.extend(["-qp", "23"])
                else:  # low
                    cmd.extend(["-qp", "28"])
                    
                # Add low_power setting for faster encoding (1=disabled, 0=enabled)
                cmd.extend(["-low_power", "1"])
            elif active_hw_accel == "videotoolbox":
                logger.debug("Using h264 codec with VideoToolbox")
                cmd.extend(["-c:v", "h264_videotoolbox"])
                # VideoToolbox quality
                if profile.quality == "high":
                    cmd.extend(["-q:v", "50"])
                elif profile.quality == "medium":
                    cmd.extend(["-q:v", "70"])
                else:  # low
                    cmd.extend(["-q:v", "90"])
            elif active_hw_accel == "amf":
                logger.debug("Using h264 codec with AMF")
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
                logger.debug("Using h264 codec (libx264)")
                cmd.extend(["-c:v", "libx264"])
                if profile.quality == "high":
                    crf = "18"
                elif profile.quality == "medium":
                    crf = "22"
                else:  # low
                    crf = "28"
                logger.debug(f"Setting CRF to {crf} for {profile.quality} quality")
                cmd.extend(["-crf", crf])
        elif profile.codec == "hevc":
            if active_hw_accel == "nvenc":
                logger.debug("Using HEVC codec with NVENC")
                cmd.extend(["-c:v", "hevc_nvenc"])
                # Use presets instead of CRF for NVENC
                if profile.quality == "high":
                    preset = "p7"  # Highest quality for NVENC
                elif profile.quality == "medium":
                    preset = "p5"
                else:  # low
                    preset = "p3"
                cmd.extend(["-preset", preset])
            elif active_hw_accel == "qsv":
                logger.debug("Using HEVC codec with QSV")
                cmd.extend(["-c:v", "hevc_qsv"])
                
                # Set QSV parameters
                if profile.quality == "high":
                    bitrate = "4M"
                elif profile.quality == "medium":
                    bitrate = "2.5M"
                else:  # low
                    bitrate = "1M"
                
                # Use bitrate control and simpler params for better compatibility
                cmd.extend(["-b:v", bitrate, "-maxrate", bitrate])
            elif active_hw_accel == "vaapi":
                logger.debug("Using HEVC codec with VAAPI")
                cmd.extend(["-c:v", "hevc_vaapi"])
                
                # VAAPI quality targets
                if profile.quality == "high":
                    cmd.extend(["-qp", "22"])
                elif profile.quality == "medium":
                    cmd.extend(["-qp", "26"])
                else:  # low
                    cmd.extend(["-qp", "32"])
                    
                # Add low_power setting for faster encoding (1=disabled, 0=enabled)
                cmd.extend(["-low_power", "1"])
            elif active_hw_accel == "videotoolbox":
                logger.debug("Using HEVC codec with VideoToolbox")
                cmd.extend(["-c:v", "hevc_videotoolbox"])
                # VideoToolbox quality
                if profile.quality == "high":
                    cmd.extend(["-q:v", "50"])
                elif profile.quality == "medium":
                    cmd.extend(["-q:v", "70"])
                else:  # low
                    cmd.extend(["-q:v", "90"])
            elif active_hw_accel == "amf":
                logger.debug("Using HEVC codec with AMF")
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
                logger.debug("Using HEVC codec (libx265)")
                cmd.extend(["-c:v", "libx265"])
                if profile.quality == "high":
                    crf = "22"
                elif profile.quality == "medium":
                    crf = "26"
                else:  # low
                    crf = "32"
                logger.debug(f"Setting CRF to {crf} for {profile.quality} quality")
                cmd.extend(["-crf", crf])
        elif profile.codec == "av1":
            # Currently no HW acceleration support for AV1 encoding
            logger.debug("Using AV1 codec (libsvtav1)")
            cmd.extend(["-c:v", "libsvtav1"])
            if profile.quality == "high":
                crf = "24"
            elif profile.quality == "medium":
                crf = "30"
            else:  # low
                crf = "36"
            logger.debug(f"Setting CRF to {crf} for {profile.quality} quality")
            cmd.extend(["-crf", crf])
        else:
            logger.warning(f"Unknown codec specified: {profile.codec}, defaulting to h264")
            cmd.extend(["-c:v", "libx264", "-crf", "22"])
        
        # Set bitrate if specified
        if profile.bitrate:
            logger.debug(f"Setting bitrate to {profile.bitrate}")
            cmd.extend(["-b:v", profile.bitrate])
        
        # Set audio codec
        logger.debug("Configuring audio stream with AAC codec at 128k")
        cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        
        # Set output format
        logger.debug(f"Setting up output format: {profile.container}")
        output_format = "matroska" if profile.container == "mkv" else profile.container
        logger.debug(f"Using format: {output_format}")
        
        # Add output path
        cmd.extend(["-y", output_path])
        
        # Get media duration
        duration = get_media_duration(ffmpeg_path, media_item.path)
        if duration:
            job.duration = duration
            logger.debug(f"Media duration: {duration} seconds")
        
        # Add progress monitoring
        cmd.extend(["-progress", "pipe:1"])
        
        # Store the command for reference
        ffmpeg_command_str = ' '.join(cmd)
        job.ffmpeg_command = ffmpeg_command_str
        
        # Log the command
        logger.debug(f"FFmpeg command: {ffmpeg_command_str}")
        
        # Run the transcoding
        logger.debug(f"Starting FFmpeg process for job {job.id}")
        try:
            # Properly quote command arguments to handle spaces and special characters
            # This ensures subprocess doesn't have issues with argument parsing
            cmd_str_for_log = ' '.join([f'"{arg}"' if ' ' in arg else arg for arg in cmd])
            logger.debug(f"Running command: {cmd_str_for_log}")
            
            # Create a new command list with paths properly handled
            # This ensures we properly handle paths with spaces and special characters
            sanitized_cmd = []
            for arg in cmd:
                # Keep as-is, subprocess.Popen with shell=False handles spaces properly
                # when passed as a list
                sanitized_cmd.append(arg)
            
            # Use text mode (instead of universal_newlines which is deprecated)
            # Add shell=False explicitly to ensure arguments are passed as a list
            # Add a specific encoding to ensure proper text handling
            process = subprocess.Popen(
                sanitized_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,  # Preferred over universal_newlines
                bufsize=1,  # Line buffered
                shell=False,  # Ensure arguments are passed as a list, not through shell
                encoding='utf-8',  # Explicitly set encoding
                errors='replace'  # Handle encoding errors gracefully
            )
            
            # Store process ID for potential cancellation
            job.process_id = process.pid
            logger.debug(f"Process ID for job {job.id}: {job.process_id}")
            
            # Create a queue for log lines
            log_lines = []
            max_log_lines = 1000  # Limit the number of log lines to store
            
            # Monitor progress
            while process.poll() is None:
                # Check if job has been cancelled
                if job.status == "cancelled":
                    logger.info(f"Job {job.id} has been cancelled, terminating process")
                    process.terminate()
                    break
                    
                # Use non-blocking reads from stdout & stderr to prevent potential deadlocks
                # This approach prevents hanging when one pipe is full but the other isn't being read
                
                # Read from stdout without blocking
                ready_to_read, _, _ = select.select([process.stdout, process.stderr], [], [], 0.1)
                
                for stream in ready_to_read:
                    if stream == process.stdout:
                        stdout_line = stream.readline().strip()
                        if stdout_line:
                            # Parse progress information
                            if stdout_line.startswith("out_time_ms="):
                                try:
                                    time_ms = int(stdout_line.split("=")[1])
                                    current_time = time_ms / 1000000  # Convert microseconds to seconds
                                    job.current_time = current_time
                                    
                                    if job.duration:
                                        job.progress = min(current_time / job.duration, 0.99)
                                        logger.debug(f"Progress: {job.progress:.2%}")
                                        
                                        # Import here to avoid circular imports - emit progress every 2 seconds
                                        if int(current_time) % 2 == 0:
                                            from squishy.socket_events import emit_job_update
                                            emit_job_update({
                                                "id": job.id,
                                                "media_id": job.media_id,
                                                "status": job.status,
                                                "progress": job.progress,
                                                "current_time": job.current_time,
                                                "duration": job.duration,
                                                "output_size": job.output_size
                                            })
                                except (ValueError, IndexError) as e:
                                    logger.warning(f"Error parsing time: {str(e)}")
                            
                            # Store the line in logs
                            log_lines.append(f"STDOUT: {stdout_line}")
                            if len(log_lines) > max_log_lines:
                                log_lines.pop(0)  # Remove oldest line if we exceed limit
                    
                    elif stream == process.stderr:
                        stderr_line = stream.readline().strip()
                        if stderr_line:
                            # Store the line in logs
                            log_lines.append(f"STDERR: {stderr_line}")
                            if len(log_lines) > max_log_lines:
                                log_lines.pop(0)  # Remove oldest line if we exceed limit
                
                # Update job logs
                job.ffmpeg_logs = log_lines
                
                # Check output file size
                if os.path.exists(output_path):
                    output_size = os.path.getsize(output_path)
                    job.output_size = format_file_size(output_size)
                    
                    # Log progress based on file size too as a fallback mechanism
                    if job.duration and job.current_time and job.current_time > 0 and job.progress < 0.99:
                        # Calculate expected file size based on current progress
                        elapsed_seconds = job.current_time
                        bytes_per_second = output_size / elapsed_seconds if elapsed_seconds > 0 else 0
                        
                        # Log activity to prevent zombie processes
                        if bytes_per_second > 0:
                            logger.debug(f"Encoding rate: {format_file_size(bytes_per_second)}/s, Size: {job.output_size}")
                
                # Check if process might be stuck (hanging)
                if hasattr(job, 'last_progress_time') and job.current_time and job.last_progress_time == job.current_time:
                    job.progress_stalled_count = getattr(job, 'progress_stalled_count', 0) + 1
                    
                    # If we've been at the same timestamp for multiple consecutive checks
                    if job.progress_stalled_count > 50:  # About 5 seconds with 0.1s timeout in select
                        # Check process status
                        process_status = get_process_status(process.pid)
                        logger.warning(f"Process {process.pid} appears stalled at {job.current_time}s with status {process_status}")
                        
                        # If the process is zombie or has been stalled for too long, kill it
                        if process_status == 'Z' or job.progress_stalled_count > 200:
                            logger.error(f"Killing stalled process {process.pid} after {job.progress_stalled_count} checks")
                            try:
                                import signal
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
                
                # No explicit sleep needed here - select.select already has a timeout
            
            # Check if job was cancelled
            if job.status == "cancelled":
                logger.info(f"Job {job.id} was cancelled")
                return
            
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
            job.ffmpeg_logs = log_lines[-max_log_lines:] if len(log_lines) > max_log_lines else log_lines
            
            if process.returncode != 0:
                logger.error(f"FFmpeg process failed with return code {process.returncode}")
                logger.error(f"FFmpeg stderr: {stderr}")
                
                # Check if this was a hardware acceleration failure
                hw_accel_error = False
                
                # Error patterns for hardware acceleration failures
                hw_error_patterns = [
                    "No usable encoding profile found",
                    "Error initializing output stream",
                    "Invalid hardware device ",
                    "Cannot load hwaccel",
                    "Failed to set value",
                    "Device creation failed",
                    "Cannot open the hardware device",
                    "Failed to open VAAPI device",
                    "Error initializing an internal frame pool"
                ]
                
                for pattern in hw_error_patterns:
                    if pattern in stderr:
                        hw_accel_error = True
                        break
                
                # If hardware acceleration failed, try alternate approach first if it's VAAPI
                if hw_accel_error and active_hw_accel:
                    if active_hw_accel == "vaapi":
                        # Try alternate VAAPI approach first before falling back to software
                        logger.warning(f"Standard VAAPI acceleration failed, trying alternate VAAPI approach")
                        job.ffmpeg_logs.append(f"NOTICE: Standard VAAPI encoding failed, trying alternate VAAPI approach...")
                        
                        # Create alternate VAAPI command with different filter chain
                        # Based on test results, this approach is proven to work with 4K HDR content
                        # and produces optimal file size and encoding speed
                        alt_cmd = [ffmpeg_path, "-hwaccel", "vaapi"]
                        
                        # Add device if available
                        if active_hw_device:
                            alt_cmd.extend(["-vaapi_device", active_hw_device])
                        else:
                            # Use default VAAPI device
                            alt_cmd.extend(["-vaapi_device", "/dev/dri/renderD128"])
                            
                        # Important: Do NOT use hwaccel_output_format for this approach
                        # as we'll be using a different filter chain that explicitly handles the format conversion
                        
                        # Add input file
                        alt_cmd.extend(["-i", media_item.path])
                        
                        # Use alternative filter chain that was verified to work with 4K HDR content
                        # The format=nv12,hwupload,scale_vaapi approach proved most efficient in testing
                        alt_cmd.extend(["-vf", f"format=nv12,hwupload,scale_vaapi=w={width}:h={height}:format=nv12"])
                        
                        # Add codec
                        if profile.codec == "h264":
                            alt_cmd.extend(["-c:v", "h264_vaapi"])
                            
                            # VAAPI quality targets
                            if profile.quality == "high":
                                alt_cmd.extend(["-qp", "18"])
                            elif profile.quality == "medium":
                                alt_cmd.extend(["-qp", "23"])
                            else:  # low
                                alt_cmd.extend(["-qp", "28"])
                        elif profile.codec == "hevc":
                            alt_cmd.extend(["-c:v", "hevc_vaapi"])
                            
                            # VAAPI quality targets
                            if profile.quality == "high":
                                alt_cmd.extend(["-qp", "22"])
                            elif profile.quality == "medium":
                                alt_cmd.extend(["-qp", "26"])
                            else:  # low
                                alt_cmd.extend(["-qp", "32"])
                        else:
                            # Default to H.264
                            alt_cmd.extend(["-c:v", "h264_vaapi", "-qp", "23"])
                            
                        # Add low_power setting (testing shows minimal difference between 0/1, default to 1 for speed)
                        alt_cmd.extend(["-low_power", "1"])
                        
                        # Add audio codec settings (same as before)
                        alt_cmd.extend(["-c:a", "aac", "-b:a", "128k"])
                        
                        # Add output file
                        alt_cmd.extend(["-y", output_path])
                        
                        # Add progress monitoring
                        alt_cmd.extend(["-progress", "pipe:1"])
                        
                        # Store the alternate command for reference
                        alt_cmd_str = ' '.join(alt_cmd)
                        job.ffmpeg_command = alt_cmd_str
                        job.ffmpeg_logs.append(f"RETRY: Using alternate VAAPI encoding approach: {alt_cmd_str}")
                        
                        logger.info(f"Trying alternate VAAPI encoding approach for job {job.id}")
                        
                        # Run the alternate VAAPI encoding
                        # Properly quote command arguments to handle spaces and special characters
                        # This ensures subprocess doesn't have issues with argument parsing
                        alt_cmd_str_for_log = ' '.join([f'"{arg}"' if ' ' in arg else arg for arg in alt_cmd])
                        logger.debug(f"Running command: {alt_cmd_str_for_log}")
                        
                        # Create a new command list with paths properly handled
                        # This ensures we properly handle paths with spaces and special characters
                        alt_sanitized_cmd = []
                        for arg in alt_cmd:
                            # Keep as-is, subprocess.Popen with shell=False handles spaces properly
                            # when passed as a list
                            alt_sanitized_cmd.append(arg)
                        
                        # Use text mode (instead of universal_newlines which is deprecated)
                        # Add shell=False explicitly to ensure arguments are passed as a list
                        # Add a specific encoding to ensure proper text handling
                        alt_process = subprocess.Popen(
                            alt_sanitized_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,  # Preferred over universal_newlines
                            bufsize=1,  # Line buffered
                            shell=False,  # Ensure arguments are passed as a list, not through shell
                            encoding='utf-8',  # Explicitly set encoding
                            errors='replace'  # Handle encoding errors gracefully
                        )
                        
                        # Store the process ID for potential cancellation
                        job.process_id = alt_process.pid
                        
                        # Monitor alternate encoding progress
                        alt_log_lines = job.ffmpeg_logs.copy()  # Keep previous logs
                        alt_success = False
                        
                        while alt_process.poll() is None:
                            # Check if job has been cancelled
                            if job.status == "cancelled":
                                logger.info(f"Alternate VAAPI encoding job {job.id} was cancelled")
                                alt_process.terminate()
                                break
                                
                            # Use non-blocking reads from stdout & stderr to prevent potential deadlocks
                            # This approach prevents hanging when one pipe is full but the other isn't being read
                            ready_to_read, _, _ = select.select([alt_process.stdout, alt_process.stderr], [], [], 0.1)
                            
                            for stream in ready_to_read:
                                if stream == alt_process.stdout:
                                    stdout_line = stream.readline().strip()
                                    if stdout_line:
                                        # Parse progress information
                                        if stdout_line.startswith("out_time_ms="):
                                            try:
                                                time_ms = int(stdout_line.split("=")[1])
                                                current_time = time_ms / 1000000  # Convert microseconds to seconds
                                                job.current_time = current_time
                                                
                                                if job.duration:
                                                    job.progress = min(1.0, current_time / job.duration)
                                                    logger.debug(f"Progress: {job.progress:.2%}")
                                            except (ValueError, IndexError) as e:
                                                logger.warning(f"Error parsing time: {str(e)}")
                                        
                                        # Store the line in logs
                                        alt_log_lines.append(f"STDOUT: {stdout_line}")
                                        if len(alt_log_lines) > max_log_lines:
                                            alt_log_lines.pop(0)  # Remove oldest line
                                
                                elif stream == alt_process.stderr:
                                    stderr_line = stream.readline().strip()
                                    if stderr_line:
                                        alt_log_lines.append(f"STDERR: {stderr_line}")
                                        if len(alt_log_lines) > max_log_lines:
                                            alt_log_lines.pop(0)
                            
                            # Update job logs
                            job.ffmpeg_logs = alt_log_lines
                            
                            # Check output file size
                            if os.path.exists(output_path):
                                output_size = os.path.getsize(output_path)
                                job.output_size = format_file_size(output_size)
                                
                            # Check if process might be stuck (hanging)
                            if hasattr(job, 'last_progress_time') and job.current_time and job.last_progress_time == job.current_time:
                                job.progress_stalled_count = getattr(job, 'progress_stalled_count', 0) + 1
                                
                                # If we've been at the same timestamp for multiple consecutive checks
                                if job.progress_stalled_count > 50:  # About 5 seconds with 0.1s timeout in select
                                    # Check process status
                                    process_status = get_process_status(alt_process.pid)
                                    logger.warning(f"Alt process {alt_process.pid} appears stalled at {job.current_time}s with status {process_status}")
                                    
                                    # If the process is zombie or has been stalled for too long, kill it
                                    if process_status == 'Z' or job.progress_stalled_count > 200:
                                        logger.error(f"Killing stalled alt process {alt_process.pid} after {job.progress_stalled_count} checks")
                                        try:
                                            import signal
                                            os.kill(alt_process.pid, signal.SIGKILL)
                                            alt_process.poll()  # Force update the returncode
                                        except Exception as e:
                                            logger.error(f"Error killing alt process: {str(e)}")
                                        break
                            else:
                                # Reset stall counter if progress has changed
                                job.progress_stalled_count = 0
                            
                            # Store last progress time for stall detection
                            if job.current_time:
                                job.last_progress_time = job.current_time
                            
                            # No need to sleep here since select already has a timeout
                        
                        # Process alternate VAAPI encoding result
                        alt_stdout, alt_stderr = alt_process.communicate()
                        
                        # Add final output to logs
                        for line in alt_stdout.splitlines():
                            if line.strip():
                                alt_log_lines.append(f"STDOUT: {line.strip()}")
                        
                        for line in alt_stderr.splitlines():
                            if line.strip():
                                alt_log_lines.append(f"STDERR: {line.strip()}")
                        
                        # Update job logs
                        job.ffmpeg_logs = alt_log_lines[-max_log_lines:] if len(alt_log_lines) > max_log_lines else alt_log_lines
                        
                        # Check if alternate VAAPI encoding succeeded
                        if alt_process.returncode == 0:
                            # Alternate VAAPI encoding succeeded!
                            logger.info(f"Alternate VAAPI encoding succeeded for job {job.id}")
                            alt_success = True
                        else:
                            logger.warning(f"Alternate VAAPI encoding also failed with return code {alt_process.returncode}")
                            logger.warning(f"FFmpeg stderr: {alt_stderr}")
                            job.ffmpeg_logs.append(f"NOTICE: Alternate VAAPI encoding failed, falling back to software encoding...")
                        
                        # If alternate VAAPI succeeded, we're done
                        if alt_success:
                            logger.info(f"Successfully used alternate VAAPI approach for job {job.id}")
                            job.ffmpeg_logs.append("SUCCESS: Alternate VAAPI approach worked successfully for HDR content")
                            return
                    
                    # If we get here, either it wasn't VAAPI or alternate VAAPI also failed
                    # For VAAPI specifically, we could try HW decode + SW encode as it was slightly faster in tests
                    if active_hw_accel == "vaapi":
                        logger.warning(f"Both standard and alternate VAAPI encoding approaches failed, trying HW decode + SW encode")
                        job.ffmpeg_logs.append(f"NOTICE: Both VAAPI encoding methods failed, trying hardware decode + software encode as last resort before full software mode...")
                        
                        # Create a hybrid command that uses VAAPI for decode but software for encode
                        # Testing showed this was actually slightly faster than full software mode
                        hybrid_cmd = [ffmpeg_path, "-hwaccel", "vaapi"]
                        
                        # Add device if available
                        if active_hw_device:
                            hybrid_cmd.extend(["-vaapi_device", active_hw_device])
                        else:
                            hybrid_cmd.extend(["-vaapi_device", "/dev/dri/renderD128"])
                            
                        # Add input file
                        hybrid_cmd.extend(["-i", media_item.path])
                        
                        # Use software scaling - we're using hardware for decode only
                        hybrid_cmd.extend(["-vf", f"scale={width}:{height}"])
                        
                        # Use software encoder with appropriate quality settings
                        if profile.codec == "h264":
                            hybrid_cmd.extend(["-c:v", "libx264"])
                            # Quality settings
                            if profile.quality == "high":
                                hybrid_cmd.extend(["-crf", "18"])
                            elif profile.quality == "medium":
                                hybrid_cmd.extend(["-crf", "22"])
                            else:  # low
                                hybrid_cmd.extend(["-crf", "28"])
                        elif profile.codec == "hevc":
                            hybrid_cmd.extend(["-c:v", "libx265"])
                            # Quality settings
                            if profile.quality == "high":
                                hybrid_cmd.extend(["-crf", "22"])
                            elif profile.quality == "medium":
                                hybrid_cmd.extend(["-crf", "26"])
                            else:  # low
                                hybrid_cmd.extend(["-crf", "32"])
                        else:  # Default to H.264
                            hybrid_cmd.extend(["-c:v", "libx264", "-crf", "23"])
                            
                        # Add audio codec settings
                        hybrid_cmd.extend(["-c:a", "aac", "-b:a", "128k"])
                        
                        # Add output file
                        hybrid_cmd.extend(["-y", output_path])
                        
                        # Add progress monitoring
                        hybrid_cmd.extend(["-progress", "pipe:1"])
                        
                        # Store the hybrid command for reference
                        hybrid_cmd_str = ' '.join(hybrid_cmd)
                        job.ffmpeg_command = hybrid_cmd_str
                        job.ffmpeg_logs.append(f"RETRY: Using hybrid hardware decode + software encode: {hybrid_cmd_str}")
                        
                        logger.info(f"Trying hybrid hardware decode + software encode for job {job.id}")
                        
                        # Run the hybrid encoding
                        # Properly quote command arguments to handle spaces and special characters
                        # This ensures subprocess doesn't have issues with argument parsing
                        hybrid_cmd_str_for_log = ' '.join([f'"{arg}"' if ' ' in arg else arg for arg in hybrid_cmd])
                        logger.debug(f"Running command: {hybrid_cmd_str_for_log}")
                        
                        # Create a new command list with paths properly handled
                        # This ensures we properly handle paths with spaces and special characters
                        hybrid_sanitized_cmd = []
                        for arg in hybrid_cmd:
                            # Keep as-is, subprocess.Popen with shell=False handles spaces properly
                            # when passed as a list
                            hybrid_sanitized_cmd.append(arg)
                        
                        # Use text mode (instead of universal_newlines which is deprecated)
                        # Add shell=False explicitly to ensure arguments are passed as a list
                        # Add a specific encoding to ensure proper text handling
                        hybrid_process = subprocess.Popen(
                            hybrid_sanitized_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,  # Preferred over universal_newlines
                            bufsize=1,  # Line buffered
                            shell=False,  # Ensure arguments are passed as a list, not through shell
                            encoding='utf-8',  # Explicitly set encoding
                            errors='replace'  # Handle encoding errors gracefully
                        )
                        
                        # Store the process ID for potential cancellation
                        job.process_id = hybrid_process.pid
                        
                        # Monitor hybrid encoding progress
                        hybrid_log_lines = job.ffmpeg_logs.copy()  # Keep previous logs
                        hybrid_success = False
                        
                        while hybrid_process.poll() is None:
                            # Check if job has been cancelled
                            if job.status == "cancelled":
                                logger.info(f"Hybrid encoding job {job.id} was cancelled")
                                hybrid_process.terminate()
                                break
                                
                            # Use non-blocking reads from stdout & stderr to prevent potential deadlocks
                            # This approach prevents hanging when one pipe is full but the other isn't being read
                            ready_to_read, _, _ = select.select([hybrid_process.stdout, hybrid_process.stderr], [], [], 0.1)
                            
                            for stream in ready_to_read:
                                if stream == hybrid_process.stdout:
                                    stdout_line = stream.readline().strip()
                                    if stdout_line:
                                        if stdout_line.startswith("out_time_ms="):
                                            try:
                                                time_ms = int(stdout_line.split("=")[1])
                                                current_time = time_ms / 1000000  # Convert microseconds to seconds
                                                job.current_time = current_time
                                                
                                                if job.duration:
                                                    job.progress = min(1.0, current_time / job.duration)
                                                    logger.debug(f"Progress: {job.progress:.2%}")
                                            except (ValueError, IndexError) as e:
                                                logger.warning(f"Error parsing time: {str(e)}")
                                        
                                        hybrid_log_lines.append(f"STDOUT: {stdout_line}")
                                        if len(hybrid_log_lines) > max_log_lines:
                                            hybrid_log_lines.pop(0)
                                
                                elif stream == hybrid_process.stderr:
                                    stderr_line = stream.readline().strip()
                                    if stderr_line:
                                        hybrid_log_lines.append(f"STDERR: {stderr_line}")
                                        if len(hybrid_log_lines) > max_log_lines:
                                            hybrid_log_lines.pop(0)
                            
                            # Update job logs
                            job.ffmpeg_logs = hybrid_log_lines
                            
                            # Check output file size
                            if os.path.exists(output_path):
                                output_size = os.path.getsize(output_path)
                                job.output_size = format_file_size(output_size)
                                
                            # Check if process might be stuck (hanging)
                            if hasattr(job, 'last_progress_time') and job.current_time and job.last_progress_time == job.current_time:
                                job.progress_stalled_count = getattr(job, 'progress_stalled_count', 0) + 1
                                
                                # If we've been at the same timestamp for multiple consecutive checks
                                if job.progress_stalled_count > 50:  # About 5 seconds with 0.1s timeout in select
                                    # Check process status
                                    process_status = get_process_status(hybrid_process.pid)
                                    logger.warning(f"Hybrid process {hybrid_process.pid} appears stalled at {job.current_time}s with status {process_status}")
                                    
                                    # If the process is zombie or has been stalled for too long, kill it
                                    if process_status == 'Z' or job.progress_stalled_count > 200:
                                        logger.error(f"Killing stalled hybrid process {hybrid_process.pid} after {job.progress_stalled_count} checks")
                                        try:
                                            import signal
                                            os.kill(hybrid_process.pid, signal.SIGKILL)
                                            hybrid_process.poll()  # Force update the returncode
                                        except Exception as e:
                                            logger.error(f"Error killing hybrid process: {str(e)}")
                                        break
                            else:
                                # Reset stall counter if progress has changed
                                job.progress_stalled_count = 0
                            
                            # Store last progress time for stall detection
                            if job.current_time:
                                job.last_progress_time = job.current_time
                            
                            # No need to sleep here since select already has a timeout
                        
                        # Process hybrid encoding result
                        hybrid_stdout, hybrid_stderr = hybrid_process.communicate()
                        
                        # Add final output to logs
                        for line in hybrid_stdout.splitlines():
                            if line.strip():
                                hybrid_log_lines.append(f"STDOUT: {line.strip()}")
                        
                        for line in hybrid_stderr.splitlines():
                            if line.strip():
                                hybrid_log_lines.append(f"STDERR: {line.strip()}")
                        
                        # Update job logs
                        job.ffmpeg_logs = hybrid_log_lines[-max_log_lines:] if len(hybrid_log_lines) > max_log_lines else hybrid_log_lines
                        
                        # Check if hybrid encoding succeeded
                        if hybrid_process.returncode == 0:
                            # Hybrid encoding succeeded!
                            logger.info(f"Hybrid hardware decode + software encode succeeded for job {job.id}")
                            hybrid_success = True
                        else:
                            logger.warning(f"Hybrid encoding also failed with return code {hybrid_process.returncode}")
                            logger.warning(f"FFmpeg stderr: {hybrid_stderr}")
                            job.ffmpeg_logs.append(f"NOTICE: Hybrid encoding failed, falling back to pure software encoding...")
                        
                        # If hybrid approach succeeded, we're done
                        if hybrid_success:
                            return
                    
                    # Last resort - fall back to pure software encoding
                    logger.warning(f"All hardware acceleration attempts with {active_hw_accel} failed, falling back to pure software encoding")
                    if active_hw_accel == "vaapi":
                        job.ffmpeg_logs.append(f"NOTICE: All VAAPI approaches failed, falling back to pure software encoding...")
                    else:
                        job.ffmpeg_logs.append(f"NOTICE: Hardware acceleration with {active_hw_accel} failed, falling back to software encoding...")
                    
                    # Create a new software-only command
                    # Note: We avoid using hardware acceleration entirely in the fallback
                    # to ensure maximum compatibility
                    sw_cmd = [ffmpeg_path, "-i", media_item.path]
                    
                    # Add software video filter for scaling
                    # Using standard ffmpeg software scaling, which has maximum compatibility
                    sw_cmd.extend(["-vf", f"scale={width}:{height}"])
                    
                    # Use software codec based on profile.codec
                    if profile.codec == "h264":
                        sw_cmd.extend(["-c:v", "libx264"])
                        # Quality settings
                        if profile.quality == "high":
                            sw_cmd.extend(["-crf", "18"])
                        elif profile.quality == "medium":
                            sw_cmd.extend(["-crf", "22"])
                        else:  # low
                            sw_cmd.extend(["-crf", "28"])
                    elif profile.codec == "hevc":
                        sw_cmd.extend(["-c:v", "libx265"])
                        # Quality settings
                        if profile.quality == "high":
                            sw_cmd.extend(["-crf", "22"])
                        elif profile.quality == "medium":
                            sw_cmd.extend(["-crf", "26"])
                        else:  # low
                            sw_cmd.extend(["-crf", "32"])
                    else:  # Default to H.264
                        sw_cmd.extend(["-c:v", "libx264", "-crf", "23"])
                    
                    # Add audio codec settings (same as before)
                    sw_cmd.extend(["-c:a", "aac", "-b:a", "128k"])
                    
                    # Add output file
                    sw_cmd.extend(["-y", output_path])
                    
                    # Add progress monitoring
                    sw_cmd.extend(["-progress", "pipe:1"])
                    
                    # Store the software command for reference
                    sw_cmd_str = ' '.join(sw_cmd)
                    job.ffmpeg_command = sw_cmd_str
                    job.ffmpeg_logs.append(f"RETRY: Using software encoding command: {sw_cmd_str}")
                    
                    logger.info(f"Retrying with software encoding for job {job.id}")
                    
                    # Run the software encoding
                    # Properly quote command arguments to handle spaces and special characters
                    # This ensures subprocess doesn't have issues with argument parsing
                    sw_cmd_str_for_log = ' '.join([f'"{arg}"' if ' ' in arg else arg for arg in sw_cmd])
                    logger.debug(f"Running command: {sw_cmd_str_for_log}")
                    
                    # Create a new command list with paths properly handled
                    # This ensures we properly handle paths with spaces and special characters
                    sw_sanitized_cmd = []
                    for arg in sw_cmd:
                        # Keep as-is, subprocess.Popen with shell=False handles spaces properly
                        # when passed as a list
                        sw_sanitized_cmd.append(arg)
                    
                    # Use text mode (instead of universal_newlines which is deprecated)
                    # Add shell=False explicitly to ensure arguments are passed as a list
                    # Add a specific encoding to ensure proper text handling
                    sw_process = subprocess.Popen(
                        sw_sanitized_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,  # Preferred over universal_newlines
                        bufsize=1,  # Line buffered
                        shell=False,  # Ensure arguments are passed as a list, not through shell
                        encoding='utf-8',  # Explicitly set encoding
                        errors='replace'  # Handle encoding errors gracefully
                    )
                    
                    # Store the process ID for potential cancellation
                    job.process_id = sw_process.pid
                    
                    # Monitor software encoding progress (similar to before)
                    sw_log_lines = job.ffmpeg_logs.copy()  # Keep previous logs
                    
                    while sw_process.poll() is None:
                        # Check if job has been cancelled
                        if job.status == "cancelled":
                            logger.info(f"Software encoding job {job.id} was cancelled")
                            sw_process.terminate()
                            break
                            
                        # Use non-blocking reads from stdout & stderr to prevent potential deadlocks
                        # This approach prevents hanging when one pipe is full but the other isn't being read
                        ready_to_read, _, _ = select.select([sw_process.stdout, sw_process.stderr], [], [], 0.1)
                        
                        for stream in ready_to_read:
                            if stream == sw_process.stdout:
                                stdout_line = stream.readline().strip()
                                if stdout_line:
                                    # Parse progress information similar to before
                                    if stdout_line.startswith("out_time_ms="):
                                        try:
                                            time_ms = int(stdout_line.split("=")[1])
                                            current_time = time_ms / 1000000  # Convert microseconds to seconds
                                            job.current_time = current_time
                                            
                                            if job.duration:
                                                job.progress = min(1.0, current_time / job.duration)
                                                logger.debug(f"Progress: {job.progress:.2%}")
                                        except (ValueError, IndexError) as e:
                                            logger.warning(f"Error parsing time: {str(e)}")
                                    
                                    # Store the line in logs
                                    sw_log_lines.append(f"STDOUT: {stdout_line}")
                                    if len(sw_log_lines) > max_log_lines:
                                        sw_log_lines.pop(0)  # Remove oldest line
                            
                            elif stream == sw_process.stderr:
                                stderr_line = stream.readline().strip()
                                if stderr_line:
                                    sw_log_lines.append(f"STDERR: {stderr_line}")
                                    if len(sw_log_lines) > max_log_lines:
                                        sw_log_lines.pop(0)
                        
                        # Update job logs
                        job.ffmpeg_logs = sw_log_lines
                        
                        # Check output file size
                        if os.path.exists(output_path):
                            output_size = os.path.getsize(output_path)
                            job.output_size = format_file_size(output_size)
                            
                        # Check if process might be stuck (hanging)
                        if hasattr(job, 'last_progress_time') and job.current_time and job.last_progress_time == job.current_time:
                            job.progress_stalled_count = getattr(job, 'progress_stalled_count', 0) + 1
                            
                            # If we've been at the same timestamp for multiple consecutive checks
                            if job.progress_stalled_count > 50:  # About 5 seconds with 0.1s timeout in select
                                # Check process status
                                process_status = get_process_status(sw_process.pid)
                                logger.warning(f"Software process {sw_process.pid} appears stalled at {job.current_time}s with status {process_status}")
                                
                                # If the process is zombie or has been stalled for too long, kill it
                                if process_status == 'Z' or job.progress_stalled_count > 200:
                                    logger.error(f"Killing stalled software process {sw_process.pid} after {job.progress_stalled_count} checks")
                                    try:
                                        import signal
                                        os.kill(sw_process.pid, signal.SIGKILL)
                                        sw_process.poll()  # Force update the returncode
                                    except Exception as e:
                                        logger.error(f"Error killing software process: {str(e)}")
                                    break
                        else:
                            # Reset stall counter if progress has changed
                            job.progress_stalled_count = 0
                        
                        # Store last progress time for stall detection
                        if job.current_time:
                            job.last_progress_time = job.current_time
                        
                        # No need to sleep here since select already has a timeout
                    
                    # Process software encoding result
                    sw_stdout, sw_stderr = sw_process.communicate()
                    
                    # Add final output to logs
                    for line in sw_stdout.splitlines():
                        if line.strip():
                            sw_log_lines.append(f"STDOUT: {line.strip()}")
                    
                    for line in sw_stderr.splitlines():
                        if line.strip():
                            sw_log_lines.append(f"STDERR: {line.strip()}")
                    
                    # Update job logs one last time
                    job.ffmpeg_logs = sw_log_lines[-max_log_lines:] if len(sw_log_lines) > max_log_lines else sw_log_lines
                    
                    # Check if software encoding succeeded
                    if sw_process.returncode != 0:
                        logger.error(f"Software encoding also failed with return code {sw_process.returncode}")
                        logger.error(f"FFmpeg stderr: {sw_stderr}")
                        raise RuntimeError(f"Both hardware acceleration and software encoding failed for job {job.id}")
                    else:
                        # Software encoding succeeded, continue with success path
                        logger.info(f"Software encoding succeeded after hardware acceleration failed for job {job.id}")
                else:
                    # Not a hardware acceleration error or no hardware acceleration was used
                    raise RuntimeError(f"FFmpeg failed with return code {process.returncode}")
            
            logger.debug(f"FFmpeg process completed successfully for job {job.id}")
            
            # Update job status
            job.status = "completed"
            job.progress = 1.0
            job.output_path = output_path
            
            # Get final output file size
            if os.path.exists(output_path):
                output_size = os.path.getsize(output_path)
                job.output_size = format_file_size(output_size)
                
            logger.debug(f"Job {job.id} completed successfully, output: {output_path}, size: {job.output_size}")
            
            # Create JSON sidecar file with metadata
            sidecar_path = f"{output_path}.json"
            metadata = {
                "original_path": media_item.path,
                "media_id": media_item.id,
                "title": media_item.title,
                "year": media_item.year,
                "type": media_item.type,
                "poster_url": media_item.poster_url,
                "profile_name": profile.name,
                "completed_at": datetime.datetime.now().isoformat(),
                "output_size": job.output_size,
                "duration": job.duration
            }
            
            # Add TV show specific metadata if applicable
            if media_item.type == "episode" and media_item.show_id:
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
            if hasattr(e, 'stderr') and e.stderr:
                for line in e.stderr.splitlines():
                    if line.strip():
                        job.ffmpeg_logs.append(f"STDERR: {line.strip()}")
    
    except Exception as e:
        logger.error(f"Error in transcoding job {job.id}: {str(e)}", exc_info=True)
        job.status = "failed"
        job.error_message = str(e)
        
        # Add error to logs
        job.ffmpeg_logs.append(f"ERROR: {str(e)}")

def get_media_duration(ffmpeg_path: str, input_path: str) -> Optional[float]:
    """Get the duration of a media file in seconds."""
    try:
        cmd = [ffmpeg_path, "-i", input_path]
        result = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        
        # Look for duration in the output
        duration_match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2})\.(\d{2})", result.stderr)
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
        "recommended": {
            "method": "",
            "device": ""
        }
    }
    
    logger.debug("Detecting available hardware acceleration methods...")
    
    # Check FFmpeg version and codecs
    try:
        # Get FFmpeg version info
        version_cmd = [ffmpeg_path, "-version"]
        version_output = subprocess.check_output(version_cmd, stderr=subprocess.STDOUT, text=True)
        logger.debug(f"FFmpeg version: {version_output.splitlines()[0] if version_output.splitlines() else 'unknown'}")
        
        # Get available encoders
        encoders_cmd = [ffmpeg_path, "-encoders"]
        encoders_output = subprocess.check_output(encoders_cmd, stderr=subprocess.STDOUT, text=True)
        
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
            hwaccels_output = subprocess.check_output(hwaccels_cmd, stderr=subprocess.STDOUT, text=True)
            
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
                nvidia_smi_cmd = ["nvidia-smi", "--query-gpu=name,index", "--format=csv,noheader"]
                nvidia_output = subprocess.check_output(nvidia_smi_cmd, stderr=subprocess.PIPE, text=True)
                
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
            
        # Test selected hardware acceleration method with a 2-second clip
        if result["recommended"]["method"]:
            logger.info(f"Testing recommended hardware acceleration method: {result['recommended']['method']}")
            # We could add a quick test here, but for now we just recommended based on presence
            
        logger.info(f"Hardware acceleration methods detected: {', '.join(result['methods']) or 'None'}")
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
            import signal
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