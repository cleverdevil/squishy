"""
effeffmpeg module for Squishy.

Import contents from the main effeffmpeg.py file to provide a consistent API.
"""

from .effeffmpeg import (
    transcode, 
    detect_capabilities, 
    generate_ffmpeg_command, 
    TranscodeProcess,
    validate_presets_data
)