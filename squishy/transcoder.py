"""Media transcoding functionality."""

import os
import uuid
import threading
import logging
import subprocess
from typing import Dict, Optional

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
            
            # Log the command
            logger.debug(f"FFmpeg command: {' '.join(cmd)}")
            
            # Run the transcoding
            logger.info(f"Starting FFmpeg process for job {job.id}")
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True
                )
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
            logger.info(f"Job {job.id} completed successfully, output: {output_path}")
            
        except Exception as e:
            logger.error(f"Transcoding job {job.id} failed: {str(e)}", exc_info=True)
            job.status = "failed"
            job.error_message = str(e)
    
    threading.Thread(target=transcode, daemon=True).start()
    logger.debug(f"Started transcoding thread for job {job.id}")