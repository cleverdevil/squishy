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
from typing import Dict, Optional, Tuple, List, Callable

from squishy.config import TranscodeProfile, load_config
from squishy.models import TranscodeJob, MediaItem

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

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
    logger.info(f"Created job with id={job_id}")
    return job

def get_job(job_id: str) -> Optional[TranscodeJob]:
    """Get a job by ID."""
    logger.debug(f"Getting job with id={job_id}")
    return JOBS.get(job_id)

def process_job_queue():
    """Process the job queue based on the concurrency limit."""
    config = load_config()
    max_jobs = config.max_concurrent_jobs
    
    # Check if we can start more jobs
    current_running = len([j for j in JOBS.values() if j.status == "processing"])
    available_slots = max(0, max_jobs - current_running)
    
    if available_slots > 0 and JOB_QUEUE:
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
            
            # Start the job
            _start_transcode_job(get_job(job_id), media_item, profile, output_dir)
            logger.info(f"Started queued job {job_id}, {len(JOB_QUEUE)} jobs remaining in queue")

def start_transcode(job: TranscodeJob, media_item: MediaItem, profile: TranscodeProfile, output_dir: str):
    """Start or queue a transcoding job based on concurrency limits."""
    logger.info(f"Starting transcode job={job.id} for media={media_item.id}, profile={profile.name}")
    logger.debug(f"Profile settings: resolution={profile.resolution}, codec={profile.codec}, "
                 f"container={profile.container}, quality={profile.quality}, bitrate={profile.bitrate}")
    
    config = load_config()
    max_jobs = config.max_concurrent_jobs
    
    # Check if we can start the job immediately
    current_running = len([j for j in JOBS.values() if j.status == "processing"])
    
    if current_running < max_jobs:
        # Start the job immediately
        _start_transcode_job(job, media_item, profile, output_dir)
        logger.info(f"Started job {job.id} immediately")
    else:
        # Queue the job
        JOB_QUEUE.append({
            "job_id": job.id,
            "media_item": media_item,
            "profile": profile,
            "output_dir": output_dir
        })
        logger.info(f"Queued job {job.id}, position in queue: {len(JOB_QUEUE)}")

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
        transcode(job, media_item, profile, output_dir)
    finally:
        # Call the callback if provided
        if callback:
            callback()

def transcode(job: TranscodeJob, media_item: MediaItem, profile: TranscodeProfile, output_dir: str):
    """Perform the transcoding."""
    try:
        job.status = "processing"
        logger.info(f"Job {job.id} status changed to processing")
        
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
        cmd = [ffmpeg_path, "-i", media_item.path]
        
        # Add video codec and options
        cmd.extend(["-vf", f"scale={width}:{height}"])
        
        if profile.codec == "h264":
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
        
        # Log the command
        logger.debug(f"FFmpeg command: {' '.join(cmd)}")
        
        # Run the transcoding
        logger.info(f"Starting FFmpeg process for job {job.id}")
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1  # Line buffered
            )
            
            # Store process ID for potential cancellation
            job.process_id = process.pid
            logger.debug(f"Process ID for job {job.id}: {job.process_id}")
            
            # Monitor progress
            while process.poll() is None:
                # Check if job has been cancelled
                if job.status == "cancelled":
                    logger.info(f"Job {job.id} has been cancelled, terminating process")
                    process.terminate()
                    break
                    
                # Read progress output
                line = process.stdout.readline().strip()
                if line:
                    # Parse progress information
                    if line.startswith("out_time_ms="):
                        try:
                            time_ms = int(line.split("=")[1])
                            current_time = time_ms / 1000000  # Convert microseconds to seconds
                            job.current_time = current_time
                            
                            if job.duration:
                                job.progress = min(current_time / job.duration, 0.99)
                                logger.debug(f"Progress: {job.progress:.2%}")
                        except (ValueError, IndexError) as e:
                            logger.warning(f"Error parsing time: {str(e)}")
                
                # Check output file size
                if os.path.exists(output_path):
                    output_size = os.path.getsize(output_path)
                    job.output_size = format_file_size(output_size)
                
                # Sleep briefly to avoid high CPU usage
                time.sleep(1)
            
            # Check if job was cancelled
            if job.status == "cancelled":
                logger.info(f"Job {job.id} was cancelled")
                return
            
            # Get the final output
            stdout, stderr = process.communicate()
            
            if process.returncode != 0:
                logger.error(f"FFmpeg process failed with return code {process.returncode}")
                logger.error(f"FFmpeg stderr: {stderr}")
                raise RuntimeError(f"FFmpeg failed with return code {process.returncode}")
            
            logger.info(f"FFmpeg process completed successfully for job {job.id}")
            
            # Update job status
            job.status = "completed"
            job.progress = 1.0
            job.output_path = output_path
            
            # Get final output file size
            if os.path.exists(output_path):
                output_size = os.path.getsize(output_path)
                job.output_size = format_file_size(output_size)
                
            logger.info(f"Job {job.id} completed successfully, output: {output_path}, size: {job.output_size}")
            
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
                
            logger.info(f"Created metadata sidecar file: {sidecar_path}")
            
        except Exception as e:
            logger.error(f"Transcoding job {job.id} failed: {str(e)}", exc_info=True)
            job.status = "failed"
            job.error_message = str(e)
    
    except Exception as e:
        logger.error(f"Error in transcoding job {job.id}: {str(e)}", exc_info=True)
        job.status = "failed"
        job.error_message = str(e)

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