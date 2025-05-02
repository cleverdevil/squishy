"""Configuration module for Squishy."""

import json
import os
import logging
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class TranscodeProfile:
    """Transcoding profile configuration."""

    name: str
    resolution: str
    codec: str
    container: str
    quality: str
    bitrate: Optional[str] = None
    hw_accel: Optional[str] = None
    hw_device: Optional[str] = None
    allow_hw_failover: bool = (
        True  # Allow fallback to software encoding if hardware acceleration fails
    )

    @classmethod
    def from_dict(cls, data):
        """Create a profile from a dictionary."""
        return cls(
            name=data["name"],
            resolution=data["resolution"],
            codec=data["codec"],
            container=data["container"],
            quality=data["quality"],
            bitrate=data.get("bitrate"),
            hw_accel=data.get("hw_accel"),
            hw_device=data.get("hw_device"),
            allow_hw_failover=data.get(
                "allow_hw_failover", True
            ),  # Default to True for backward compatibility
        )


@dataclass
class Config:
    """Main application configuration."""

    media_path: str
    transcode_path: str
    ffmpeg_path: str = "/usr/bin/ffmpeg"
    ffprobe_path: str = "/usr/bin/ffprobe"  # Added ffprobe path
    jellyfin_url: Optional[str] = None
    jellyfin_api_key: Optional[str] = None
    plex_url: Optional[str] = None
    plex_token: Optional[str] = None
    path_mappings: Dict[str, str] = (
        None  # Dictionary of source path -> target path mappings
    )
    profiles: Dict[str, TranscodeProfile] = None
    max_concurrent_jobs: int = 1  # Default to 1 concurrent job
    hw_accel: Optional[str] = None  # Global hardware acceleration method
    hw_device: Optional[str] = None  # Global hardware acceleration device
    enabled_libraries: Dict[str, bool] = (
        None  # Dictionary of library_id -> enabled status
    )
    log_level: str = (
        "INFO"  # Application log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    )

    def __post_init__(self):
        """Ensure dictionaries are initialized."""
        if self.profiles is None:
            self.profiles = {}
        if self.path_mappings is None:
            self.path_mappings = {}
        if self.enabled_libraries is None:
            self.enabled_libraries = {}


def load_config(config_path: str = None) -> Config:
    """Load configuration from a JSON file."""
    if config_path is None:
        config_path = os.environ.get("CONFIG_PATH", "config/config.json")

    # Use default configuration as a fallback if config file doesn't exist
    default_config = {
        "media_path": "/media",
        "transcode_path": "/app/data/transcodes",
        "ffmpeg_path": "/usr/bin/ffmpeg",
        "ffprobe_path": "/usr/bin/ffprobe",  # Added default ffprobe path
        "path_mappings": {},
        "profiles": [
            {
                "name": "high",
                "resolution": "3840x2160",
                "codec": "h264",
                "container": "mkv",
                "quality": "high",
            },
            {
                "name": "medium",
                "resolution": "1920x1080",
                "codec": "h264",
                "container": "mkv",
                "quality": "medium",
            },
            {
                "name": "low",
                "resolution": "1280x720",
                "codec": "h264",
                "container": "mp4",
                "quality": "low",
            },
            {
                "name": "potato",
                "resolution": "854x480",
                "codec": "h264",
                "container": "mp4",
                "quality": "low",
                "bitrate": "1M",
            },
        ],
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

            # Ensure profiles are defined
            if "profiles" not in config_data or not config_data["profiles"]:
                logging.warning(
                    "No profiles defined in config file, using default profiles"
                )
                config_data["profiles"] = default_config["profiles"]

            # Ensure either Jellyfin or Plex is configured
            has_jellyfin = config_data.get("jellyfin_url") and config_data.get(
                "jellyfin_api_key"
            )
            has_plex = config_data.get("plex_url") and config_data.get("plex_token")

            if not has_jellyfin and not has_plex:
                logging.warning(
                    "No media server configured. Please configure either Jellyfin or Plex to use Squishy."
                )

    # Parse profiles
    profiles = {}
    for profile_data in config_data["profiles"]:
        profile = TranscodeProfile.from_dict(profile_data)
        profiles[profile.name] = profile

    # Handle migration from media_paths to media_path
    media_path = config_data.get("media_path")
    if not media_path and "media_paths" in config_data and config_data["media_paths"]:
        media_path = config_data["media_paths"][0]

    # Get path mappings
    path_mappings = config_data.get("path_mappings", {})

    # Get enabled libraries (default all to True if not specified)
    enabled_libraries = config_data.get("enabled_libraries", {})

    return Config(
        media_path=media_path or default_config["media_path"],
        transcode_path=config_data.get(
            "transcode_path", default_config["transcode_path"]
        ),
        ffmpeg_path=config_data.get("ffmpeg_path", default_config["ffmpeg_path"]),
        ffprobe_path=config_data.get(
            "ffprobe_path", default_config["ffprobe_path"]
        ),  # Added ffprobe path
        jellyfin_url=config_data.get("jellyfin_url"),
        jellyfin_api_key=config_data.get("jellyfin_api_key"),
        plex_url=config_data.get("plex_url"),
        plex_token=config_data.get("plex_token"),
        path_mappings=path_mappings,
        profiles=profiles,
        max_concurrent_jobs=config_data.get("max_concurrent_jobs", 1),
        hw_accel=config_data.get("hw_accel"),
        hw_device=config_data.get("hw_device"),
        enabled_libraries=enabled_libraries,
        log_level=config_data.get("log_level", "INFO"),
    )


def save_config(config: Config, config_path: str = None) -> None:
    """Save configuration to a JSON file."""
    if config_path is None:
        config_path = os.environ.get("CONFIG_PATH", "config/config.json")

    profiles_data = []
    for profile in config.profiles.values():
        profile_dict = {
            "name": profile.name,
            "resolution": profile.resolution,
            "codec": profile.codec,
            "container": profile.container,
            "quality": profile.quality,
            "allow_hw_failover": profile.allow_hw_failover,  # Always include this field
        }
        if profile.bitrate:
            profile_dict["bitrate"] = profile.bitrate
        if profile.hw_accel:
            profile_dict["hw_accel"] = profile.hw_accel
        if profile.hw_device:
            profile_dict["hw_device"] = profile.hw_device
        profiles_data.append(profile_dict)

    config_data = {
        "media_path": config.media_path,
        "transcode_path": config.transcode_path,
        "ffmpeg_path": config.ffmpeg_path,
        "ffprobe_path": config.ffprobe_path,  # Added ffprobe path
        "profiles": profiles_data,
        "path_mappings": config.path_mappings,
        "max_concurrent_jobs": config.max_concurrent_jobs,
        "hw_accel": config.hw_accel,
        "hw_device": config.hw_device,
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
