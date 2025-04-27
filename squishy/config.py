"""Configuration module for Squishy."""

import json
import os
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

@dataclass
class TranscodeProfile:
    """Transcoding profile configuration."""
    
    name: str
    resolution: str
    codec: str
    container: str
    quality: str
    bitrate: Optional[str] = None
    
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
        )

@dataclass
class Config:
    """Main application configuration."""
    
    media_path: str
    transcode_path: str
    ffmpeg_path: str = "/usr/bin/ffmpeg"
    jellyfin_url: Optional[str] = None
    jellyfin_api_key: Optional[str] = None
    plex_url: Optional[str] = None
    plex_token: Optional[str] = None
    path_mappings: Dict[str, str] = None
    profiles: Dict[str, TranscodeProfile] = None
    
    def __post_init__(self):
        """Ensure dictionaries are initialized."""
        if self.profiles is None:
            self.profiles = {}
        if self.path_mappings is None:
            self.path_mappings = {}

def load_config(config_path: str = None) -> Config:
    """Load configuration from a JSON file."""
    if config_path is None:
        config_path = os.environ.get("CONFIG_PATH", "config/config.json")
    
    # Use default configuration as a fallback if config file doesn't exist
    default_config = {
        "media_path": "/media",
        "transcode_path": "/app/data/transcodes",
        "ffmpeg_path": "/usr/bin/ffmpeg",
        "path_mappings": {},
        "profiles": [
            {
                "name": "high",
                "resolution": "3840x2160",
                "codec": "h264",
                "container": "mkv",
                "quality": "high"
            },
            {
                "name": "medium",
                "resolution": "1920x1080",
                "codec": "h264",
                "container": "mkv",
                "quality": "medium"
            },
            {
                "name": "low",
                "resolution": "1280x720",
                "codec": "h264",
                "container": "mp4",
                "quality": "low"
            },
            {
                "name": "potato",
                "resolution": "854x480",
                "codec": "h264",
                "container": "mp4",
                "quality": "low",
                "bitrate": "1M"
            }
        ]
    }
        
    if not os.path.exists(config_path):
        # Log that we're using default configuration
        logging.warning(f"Config file not found at {config_path}, using default configuration")
        config_data = default_config
    else:
        # Load configuration from file
        with open(config_path, "r") as f:
            config_data = json.load(f)
            
            # Ensure profiles are defined
            if "profiles" not in config_data or not config_data["profiles"]:
                logging.warning("No profiles defined in config file, using default profiles")
                config_data["profiles"] = default_config["profiles"]
        
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
            
    return Config(
        media_path=media_path or default_config["media_path"],
        transcode_path=config_data.get("transcode_path", default_config["transcode_path"]),
        ffmpeg_path=config_data.get("ffmpeg_path", default_config["ffmpeg_path"]),
        jellyfin_url=config_data.get("jellyfin_url"),
        jellyfin_api_key=config_data.get("jellyfin_api_key"),
        plex_url=config_data.get("plex_url"),
        plex_token=config_data.get("plex_token"),
        path_mappings=path_mappings,
        profiles=profiles,
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
        }
        if profile.bitrate:
            profile_dict["bitrate"] = profile.bitrate
        profiles_data.append(profile_dict)
    
    config_data = {
        "media_path": config.media_path,
        "transcode_path": config.transcode_path,
        "ffmpeg_path": config.ffmpeg_path,
        "profiles": profiles_data,
        "path_mappings": config.path_mappings
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