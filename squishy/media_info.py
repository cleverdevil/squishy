"""Media information extraction functionality."""

import json
import logging
import subprocess
from typing import Dict, Any, Optional

from squishy.config import load_config

logger = logging.getLogger(__name__)


def get_media_info(file_path: str) -> Dict[str, Any]:
    """
    Extract detailed technical information about a media file using FFmpeg.

    Args:
        file_path: Path to the media file

    Returns:
        Dictionary containing technical information about the media file
    """
    try:
        config = load_config()
        ffprobe_path = (
            config.ffprobe_path or "ffprobe"
        )  # Use config path or default to system ffprobe

        # Run ffprobe to get detailed media information in JSON format
        cmd = [
            ffprobe_path,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            file_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)

        # Process the raw ffprobe output into a more user-friendly format
        info = {
            "format": {
                "filename": data.get("format", {}).get("filename", ""),
                "format_name": data.get("format", {}).get("format_long_name", ""),
                "duration": float(data.get("format", {}).get("duration", 0)),
                "size": int(data.get("format", {}).get("size", 0)),
                "bit_rate": int(data.get("format", {}).get("bit_rate", 0)),
            },
            "video": [],
            "audio": [],
            "subtitle": [],
            "hdr_info": None,
        }

        # Store raw data for debugging
        info["raw_data"] = data

        # Extract stream information
        for stream in data.get("streams", []):
            codec_type = stream.get("codec_type")

            if codec_type == "video":
                video_info = {
                    "codec": stream.get("codec_name", ""),
                    "codec_description": stream.get("codec_long_name", ""),
                    "width": stream.get("width", 0),
                    "height": stream.get("height", 0),
                    "aspect_ratio": stream.get("display_aspect_ratio", ""),
                    "frame_rate": _parse_frame_rate(
                        stream.get("avg_frame_rate", "0/1")
                    ),
                    "bit_depth": stream.get("bits_per_raw_sample", ""),
                    "pixel_format": stream.get("pix_fmt", ""),
                    "profile": stream.get("profile", ""),
                    "color_space": stream.get("color_space", ""),
                    "color_transfer": stream.get("color_transfer", ""),
                    "color_primaries": stream.get("color_primaries", ""),
                }

                # Extract HDR information
                hdr_info = _extract_hdr_info(stream)
                if hdr_info:
                    info["hdr_info"] = hdr_info

                info["video"].append(video_info)

            elif codec_type == "audio":
                audio_info = {
                    "codec": stream.get("codec_name", ""),
                    "codec_description": stream.get("codec_long_name", ""),
                    "channels": stream.get("channels", 0),
                    "channel_layout": stream.get("channel_layout", ""),
                    "sample_rate": stream.get("sample_rate", ""),
                    "bit_rate": stream.get("bit_rate", ""),
                    "language": stream.get("tags", {}).get("language", ""),
                    "title": stream.get("tags", {}).get("title", ""),
                }
                info["audio"].append(audio_info)

            elif codec_type == "subtitle":
                subtitle_info = {
                    "codec": stream.get("codec_name", ""),
                    "language": stream.get("tags", {}).get("language", ""),
                    "title": stream.get("tags", {}).get("title", ""),
                }
                info["subtitle"].append(subtitle_info)

        # If HDR info wasn't found in stream metadata, try to detect it from color information
        if not info["hdr_info"] and info["video"]:
            info["hdr_info"] = _detect_hdr_from_color_info(info["video"][0])

        return info

    except subprocess.CalledProcessError as e:
        logger.error(f"Error running ffprobe: {e}")
        return {"error": f"Failed to extract media information: {str(e)}"}
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing ffprobe output: {e}")
        return {"error": f"Failed to parse media information: {str(e)}"}
    except Exception as e:
        logger.error(f"Unexpected error extracting media information: {e}")
        return {"error": f"Unexpected error: {str(e)}"}


def _parse_frame_rate(frame_rate_str: str) -> float:
    """Parse frame rate string (e.g., '24000/1001') to a float."""
    try:
        if "/" in frame_rate_str:
            num, den = map(int, frame_rate_str.split("/"))
            if den == 0:  # Avoid division by zero
                return 0
            return round(num / den, 3)
        else:
            return float(frame_rate_str)
    except (ValueError, ZeroDivisionError):
        return 0


def _extract_hdr_info(stream: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract HDR information from stream metadata."""
    # Check for common HDR indicators in the stream
    side_data = stream.get("side_data_list", [])
    hdr_info = {}

    # Check for Dolby Vision first (highest priority)
    # Look for Dolby Vision configuration record in side data
    for data in side_data:
        if (
            data.get("side_data_type") == "DOVI configuration record"
            or "dv_profile" in data
        ):
            hdr_info["type"] = "Dolby Vision"
            hdr_info["dv_profile"] = data.get("dv_profile")
            hdr_info["dv_level"] = data.get("dv_level")
            # Return immediately as Dolby Vision is the highest priority
            return hdr_info

    # Check for codec tags that indicate Dolby Vision
    if (
        stream.get("codec_tag_string") == "dvh1"
        or stream.get("codec_name") == "dvhe"
        or "dvhe" in str(stream)
    ):
        hdr_info["type"] = "Dolby Vision"
        return hdr_info

    # Check for HDR10/HDR10+ metadata
    for data in side_data:
        if data.get("side_data_type") == "Mastering display metadata":
            hdr_info["type"] = "HDR10"
            hdr_info["master_display"] = data.get("master_display", "")

        if data.get("side_data_type") == "Content light level metadata":
            if "type" not in hdr_info or hdr_info["type"] == "HDR10":
                hdr_info["type"] = "HDR10"
            hdr_info["max_content"] = data.get("max_content", 0)
            hdr_info["max_average"] = data.get("max_average", 0)

    # Check for HDR10+ based on codec profile and metadata
    if "HDR10+" in json.dumps(stream) or "hdr10plus" in json.dumps(stream).lower():
        hdr_info["type"] = "HDR10+"

    # Check color properties for HDR indicators
    color_transfer = stream.get("color_transfer", "").lower()
    if "smpte2084" in color_transfer or "pq" in color_transfer:
        if "type" not in hdr_info:
            hdr_info["type"] = "HDR10"
    elif "arib-std-b67" in color_transfer or "hlg" in color_transfer:
        if "type" not in hdr_info:  # Don't override Dolby Vision or HDR10+
            hdr_info["type"] = "HLG"

    return hdr_info if hdr_info else None


def _detect_hdr_from_color_info(video_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Detect HDR type from color information when explicit metadata is missing."""
    hdr_info = {}

    # Check for Dolby Vision indicators in the raw data
    if (
        "dv_" in str(video_info)
        or "dolby" in str(video_info).lower()
        or "vision" in str(video_info).lower()
    ):
        hdr_info["type"] = "Dolby Vision"
        return hdr_info

    # Check color transfer function
    color_transfer = video_info.get("color_transfer", "").lower()
    color_primaries = video_info.get("color_primaries", "").lower()
    bit_depth = video_info.get("bit_depth")
    pixel_format = video_info.get("pixel_format", "").lower()

    # Check for HDR10+ indicators
    if "hdr10plus" in str(video_info).lower() or "hdr10+" in str(video_info):
        hdr_info["type"] = "HDR10+"
        return hdr_info

    # PQ (Perceptual Quantizer) is used in HDR10 and Dolby Vision
    if "smpte2084" in color_transfer or "pq" in color_transfer:
        hdr_info["type"] = "HDR10"
    # HLG (Hybrid Log-Gamma)
    elif "arib-std-b67" in color_transfer or "hlg" in color_transfer:
        hdr_info["type"] = "HLG"
    # Check for wide color gamut
    elif "bt2020" in color_primaries and bit_depth and int(bit_depth) >= 10:
        hdr_info["type"] = "HDR (unspecified)"
    # Check for 10-bit content which might be HDR
    elif (
        bit_depth
        and int(bit_depth) >= 10
        and ("yuv420p10" in pixel_format or "p010" in pixel_format)
    ):
        hdr_info["type"] = "HDR (unspecified)"

    return hdr_info if hdr_info else None


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