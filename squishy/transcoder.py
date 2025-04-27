"""Media transcoding functionality."""

import os
import uuid
import threading
import logging
import subprocess
import re
import time
from typing import Dict, Optional, Tuple

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

def start_transcode(job: TranscodeJob, media_item: MediaItem, profile: TranscodeProfile, output_dir: str):
    """Start a transcoding job in a separate thread."""
    logger.info(f"Starting transcode job={job.id} for media={media_item.id}, profile={profile.name}")
    logger.debug(f"Profile settings: resolution={profile.resolution}, codec={profile.codec}, "
                 f"container={profile.container}, quality={profile.quality}, bitrate={profile.bitrate}")
    logger.debug(f"Output directory: {output_dir}")
    
    def transcode():
        """Perform the transcoding."""
        try:
            job.status = "processing"
            logger.info(f"Job {job.id} status changed to processing")
            
            # Create output filename
            filename = f"{media_item.title}_{profile.name}.{profile.container}"
            filename = filename.replace(" ", "_").replace(":", "_")
            output_path = os.path.join(output_dir, filename)
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
                
                # Monitor progress
                while process.poll() is None:
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
                
                # Get the final output
                stdout, stderr = process.communicate()
                
                if process.returncode != 0:
                    logger.error(f"FFmpeg process failed with return code {process.returncode}")
                    logger.error(f"FFmpeg stderr: {stderr}")
                    raise RuntimeError(f"FFmpeg failed with return code {process.returncode}")
                
                logger.info(f"FFmpeg process completed successfully for job {job.id}")
            except Exception as e:
                error_message = str(e)
                logger.error(f"FFmpeg error: {error_message}")
                raise
            
            # Update job status
            job.status = "completed"
            job.progress = 1.0
            job.output_path = output_path
            
            # Get final output file size
            if os.path.exists(output_path):
                output_size = os.path.getsize(output_path)
                job.output_size = format_file_size(output_size)
                
            logger.info(f"Job {job.id} completed successfully, output: {output_path}, size: {job.output_size}")
            
        except Exception as e:
            logger.error(f"Transcoding job {job.id} failed: {str(e)}", exc_info=True)
            job.status = "failed"
            job.error_message = str(e)
    
    threading.Thread(target=transcode, daemon=True).start()
    logger.debug(f"Started transcoding thread for job {job.id}")
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
