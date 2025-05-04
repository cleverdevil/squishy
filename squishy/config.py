"""Configuration module for Squishy."""

import json
import os
import logging
from dataclasses import dataclass
from typing import Dict, Optional, Any


@dataclass
class Config:
    """Main application configuration."""

    media_path: str
    transcode_path: str
    ffmpeg_path: str = "/usr/bin/ffmpeg"
    ffprobe_path: str = "/usr/bin/ffprobe"
    jellyfin_url: Optional[str] = None
    jellyfin_api_key: Optional[str] = None
    plex_url: Optional[str] = None
    plex_token: Optional[str] = None
    path_mappings: Dict[str, str] = None  # Dictionary of source path -> target path mappings
    presets: Dict[str, Dict[str, Any]] = None  # Using effeffmpeg presets directly
    max_concurrent_jobs: int = 1  # Default to 1 concurrent job
    hw_accel: Optional[str] = None  # Global hardware acceleration method
    hw_device: Optional[str] = None  # Global hardware acceleration device
    hw_capabilities: Optional[Dict[str, Any]] = None  # Hardware capabilities JSON data
    enabled_libraries: Dict[str, bool] = None  # Dictionary of library_id -> enabled status
    log_level: str = "INFO"  # Application log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    
    def __post_init__(self):
        """Ensure dictionaries are initialized."""
        if self.presets is None:
            self.presets = {}
        if self.path_mappings is None:
            self.path_mappings = {}
        if self.enabled_libraries is None:
            self.enabled_libraries = {}


def load_config(config_path: str = None) -> Config:
    """Load configuration from a JSON file."""
    if config_path is None:
        config_path = os.environ.get("CONFIG_PATH", "./config/config.json")
        
    # Check if the config directory exists, create it if not
    config_dir = os.path.dirname(config_path)
    if not os.path.exists(config_dir):
        os.makedirs(config_dir, exist_ok=True)

    # Default presets that will be used if none are defined in the config
    default_presets = {
        "high": {
            "codec": "hevc",
            "scale": "1080p",
            "container": ".mkv",
            "audio_codec": "aac",
            "audio_bitrate": "192k",
            "crf": 20,
            "allow_fallback": True
        },
        "medium": {
            "codec": "hevc",
            "scale": "720p",
            "container": ".mkv",
            "audio_codec": "aac",
            "audio_bitrate": "128k",
            "crf": 24,
            "allow_fallback": True
        },
        "low": {
            "codec": "hevc",
            "scale": "480p",
            "container": ".mkv",
            "audio_codec": "aac",
            "audio_bitrate": "96k",
            "crf": 28,
            "allow_fallback": True
        }
    }

    # Use default configuration as a fallback if config file doesn't exist
    default_config = {
        "media_path": "/media",
        "transcode_path": "/transcodes",
        "ffmpeg_path": "/usr/bin/ffmpeg",
        "ffprobe_path": "/usr/bin/ffprobe",
        "path_mappings": {},
        "presets": default_presets,
        # Default to Jellyfin settings to encourage configuration
        "jellyfin_url": "",
        "jellyfin_api_key": "",
    }

    if not os.path.exists(config_path):
        # Log that we're using default configuration
        logging.warning(
            f"Config file not found at {config_path}, using default configuration"
        )
        logging.warning("Please configure either Jellyfin or Plex to use Squishy.")
        config_data = default_config
    else:
        # Load configuration from file
        with open(config_path, "r") as f:
            config_data = json.load(f)

            # Ensure presets are defined
            if "presets" not in config_data or not config_data["presets"]:
                logging.warning(
                    "No presets defined in config file, using default presets"
                )
                config_data["presets"] = default_presets

            # Ensure either Jellyfin or Plex is configured
            has_jellyfin = config_data.get("jellyfin_url") and config_data.get(
                "jellyfin_api_key"
            )
            has_plex = config_data.get("plex_url") and config_data.get("plex_token")

            if not has_jellyfin and not has_plex:
                logging.warning(
                    "No media server configured. Please configure either Jellyfin or Plex to use Squishy."
                )

    # Handle migration from media_paths to media_path
    media_path = config_data.get("media_path")
    if not media_path and "media_paths" in config_data and config_data["media_paths"]:
        media_path = config_data["media_paths"][0]

    # Get path mappings
    path_mappings = config_data.get("path_mappings", {})

    # Get enabled libraries (default all to True if not specified)
    enabled_libraries = config_data.get("enabled_libraries", {})

    # Get presets
    presets = config_data.get("presets", default_presets)

    return Config(
        media_path=media_path or default_config["media_path"],
        transcode_path=config_data.get(
            "transcode_path", default_config["transcode_path"]
        ),
        ffmpeg_path=config_data.get("ffmpeg_path", default_config["ffmpeg_path"]),
        ffprobe_path=config_data.get(
            "ffprobe_path", default_config["ffprobe_path"]
        ),
        jellyfin_url=config_data.get("jellyfin_url"),
        jellyfin_api_key=config_data.get("jellyfin_api_key"),
        plex_url=config_data.get("plex_url"),
        plex_token=config_data.get("plex_token"),
        path_mappings=path_mappings,
        presets=presets,
        max_concurrent_jobs=config_data.get("max_concurrent_jobs", 1),
        hw_accel=config_data.get("hw_accel"),
        hw_device=config_data.get("hw_device"),
        hw_capabilities=config_data.get("hw_capabilities"),
        enabled_libraries=enabled_libraries,
        log_level=config_data.get("log_level", "INFO"),
    )




def save_config(config: Config, config_path: str = None) -> None:
    """Save configuration to a JSON file."""
    if config_path is None:
        config_path = os.environ.get("CONFIG_PATH", "./config/config.json")

    config_data = {
        "media_path": config.media_path,
        "transcode_path": config.transcode_path,
        "ffmpeg_path": config.ffmpeg_path,
        "ffprobe_path": config.ffprobe_path,
        "presets": config.presets,
        "path_mappings": config.path_mappings,
        "max_concurrent_jobs": config.max_concurrent_jobs,
        "hw_accel": config.hw_accel,
        "hw_device": config.hw_device,
        "hw_capabilities": config.hw_capabilities,
        "enabled_libraries": config.enabled_libraries,
        "log_level": config.log_level,
    }

    # Only include one source configuration
    if config.jellyfin_url and config.jellyfin_api_key:
        config_data["jellyfin_url"] = config.jellyfin_url
        config_data["jellyfin_api_key"] = config.jellyfin_api_key
    elif config.plex_url and config.plex_token:
        config_data["plex_url"] = config.plex_url
        config_data["plex_token"] = config.plex_token

    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2)