"""API blueprint for Squishy."""

from flask import Blueprint, jsonify, request, current_app

from squishy.config import load_config
from squishy.models import TranscodeJob
from squishy.scanner import get_all_media, get_media, get_scan_status
from squishy.transcoder import create_job, get_job, start_transcode
from squishy.media_info import get_media_info, format_file_size

api_bp = Blueprint("api", __name__)

@api_bp.route("/media", methods=["GET"])
def list_media():
    """List all media items."""
    media_items = get_all_media()
    return jsonify({
        "media": [
            {
                "id": item.id,
                "title": item.title,
                "year": item.year,
                "type": item.type,
                "poster_url": item.poster_url,
            }
            for item in media_items
        ]
    })

@api_bp.route("/paginated-media", methods=["GET"])
def paginated_media():
    """Get paginated shows and movies data."""
    from squishy.scanner import get_shows_and_movies
    
    # Get search query
    search_query = request.args.get('q', '').strip().lower()

    # Get all shows and movies
    all_shows, all_movies = get_shows_and_movies()
    
    # Sort alphabetically by title
    all_shows = sorted(all_shows, key=lambda x: x.title.lower())
    all_movies = sorted(all_movies, key=lambda x: x.title.lower())
    
    # Filter by search query if provided
    if search_query:
        all_shows = [show for show in all_shows if search_query in show.title.lower()]
        all_movies = [movie for movie in all_movies if search_query in movie.title.lower()]
    
    # Convert shows to simplified format
    shows_data = [
        {
            "id": show.id,
            "title": show.title,
            "display_name": show.display_name,
            "year": show.year,
            "poster_url": show.poster_url,
            "season_count": len(show.seasons)
        } 
        for show in all_shows
    ]
    
    # Convert movies to simplified format
    movies_data = [
        {
            "id": movie.id,
            "title": movie.title,
            "display_name": movie.display_name,
            "year": movie.year,
            "poster_url": movie.poster_url
        }
        for movie in all_movies
    ]
    
    return jsonify({
        "shows": shows_data,
        "total_shows": len(shows_data),
        "movies": movies_data,
        "total_movies": len(movies_data)
    })

@api_bp.route("/media/<media_id>", methods=["GET"])
def get_media_item(media_id):
    """Get a specific media item."""
    media_item = get_media(media_id)
    if media_item is None:
        return jsonify({"error": "Media not found"}), 404
    
    return jsonify({
        "id": media_item.id,
        "title": media_item.title,
        "year": media_item.year,
        "type": media_item.type,
        "path": media_item.path,
        "poster_url": media_item.poster_url,
    })

@api_bp.route("/presets", methods=["GET"])
def list_presets():
    """List all transcoding presets."""
    config = load_config()
    
    return jsonify({
        "presets": [
            {
                "name": name,
                "codec": preset.get("codec", "h264"),
                "scale": preset.get("scale", "1080p"),
                "container": preset.get("container", ".mkv"),
                "crf": preset.get("crf"),
                "bitrate": preset.get("bitrate"),
                "audio_codec": preset.get("audio_codec", "aac"),
                "audio_bitrate": preset.get("audio_bitrate", "128k"),
                "force_software": preset.get("force_software", False),
                "allow_fallback": preset.get("allow_fallback", True),
            }
            for name, preset in config.presets.items()
        ]
    })

@api_bp.route("/transcode", methods=["POST"])
def transcode():
    """Start a transcoding job."""
    data = request.json
    if not data or "media_id" not in data or "preset" not in data:
        return jsonify({"error": "Missing required fields"}), 400
    
    media_id = data["media_id"]
    preset_name = data["preset"]
    
    media_item = get_media(media_id)
    if media_item is None:
        return jsonify({"error": "Media not found"}), 404
    
    config = load_config()
    if preset_name not in config.presets:
        return jsonify({"error": "Invalid preset"}), 400
    
    job = create_job(media_item, preset_name)
    start_transcode(
        job,
        media_item,
        preset_name,
        current_app.config["TRANSCODE_PATH"],
    )
    
    return jsonify({
        "job_id": job.id,
        "status": job.status,
        "media_id": media_id,
        "preset": preset_name,
    })

@api_bp.route("/jobs", methods=["GET"])
def list_jobs():
    """List all transcoding jobs."""
    from squishy.transcoder import JOBS
    
    return jsonify({
        "jobs": [
            {
                "id": job.id,
                "media_id": job.media_id,
                "preset": job.preset_name,
                "status": job.status,
                "progress": job.progress,
                "output_path": job.output_path,
                "error_message": job.error_message,
                "current_time": job.current_time if hasattr(job, 'current_time') else None,
                "duration": job.duration if hasattr(job, 'duration') else None,
            }
            for job in JOBS.values()
        ]
    })

@api_bp.route("/jobs/<job_id>", methods=["GET"])
def get_job_status(job_id):
    """Get the status of a specific job."""
    job = get_job(job_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    
    return jsonify({
        "id": job.id,
        "media_id": job.media_id,
        "preset": job.preset_name,
        "status": job.status,
        "progress": job.progress,
        "output_path": job.output_path,
        "error_message": job.error_message,
        "current_time": job.current_time if hasattr(job, 'current_time') else None,
        "duration": job.duration if hasattr(job, 'duration') else None,
    })
@api_bp.route("/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job_api(job_id):
    """Cancel a transcoding job."""
    from squishy.transcoder import cancel_job
    
    success = cancel_job(job_id)
    if success:
        return jsonify({"status": "cancelled"})
    else:
        return jsonify({"error": "Could not cancel job"}), 400

@api_bp.route("/jobs/<job_id>/remove", methods=["POST"])
def remove_job_api(job_id):
    """Remove a completed, failed, or cancelled job."""
    from squishy.transcoder import remove_job
    
    success = remove_job(job_id)
    if success:
        return jsonify({"status": "removed"})
    else:
        return jsonify({"error": "Could not remove job"}), 400

@api_bp.route("/jobs/<job_id>/logs", methods=["GET"])
def get_job_logs(job_id):
    """Get the FFmpeg logs for a specific job."""
    job = get_job(job_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    
    return jsonify({
        "ffmpeg_command": job.ffmpeg_command,
        "ffmpeg_logs": job.ffmpeg_logs
    })

@api_bp.route("/scan/status", methods=["GET"])
def scan_status():
    """Get the current scanning status."""
    status = get_scan_status()
    
    return jsonify(status)

@api_bp.route("/media/<media_id>/technical_info", methods=["GET"])
def get_media_technical_info(media_id):
    """Get detailed technical information about a specific media item."""
    # Improved debug logging
    print(f"DEBUG: Received technical info request for media ID: {media_id}")
    
    media_item = get_media(media_id)
    if media_item is None:
        print(f"DEBUG: Media item not found for ID: {media_id}")
        return jsonify({"error": "Media not found"}), 404
    
    try:
        print(f"DEBUG: Processing technical info for path: {media_item.path}")
        
        # Check if the file exists
        import os
        if not os.path.exists(media_item.path):
            print(f"DEBUG: File does not exist: {media_item.path}")
            return jsonify({"error": f"Media file not found at {media_item.path}"}), 404
        
        # Get technical information about the media file
        media_info = get_media_info(media_item.path)
        
        # Check if there was an error in get_media_info
        if "error" in media_info:
            print(f"DEBUG: Error in get_media_info: {media_info['error']}")
            return jsonify(media_info), 500
            
        # Format file size for display
        file_size = format_file_size(media_info.get("format", {}).get("size", 0))
        
        # Add the formatted file size to the response
        media_info["formatted_file_size"] = file_size
        
        # Add minimal info for resolution and HDR badges
        basic_info = {
            "has_resolution_badge": False,
            "resolution_badge": "",
            "has_hdr": False,
            "hdr_type": ""
        }
        
        # Check for resolution badges
        if media_info.get("video") and len(media_info["video"]) > 0:
            video = media_info["video"][0]
            width = video.get("width", 0)
            
            if width >= 3840:
                basic_info["has_resolution_badge"] = True
                basic_info["resolution_badge"] = "4K"
            elif width >= 1920:
                basic_info["has_resolution_badge"] = True
                basic_info["resolution_badge"] = "HD"
        
        # Check for HDR
        if media_info.get("hdr_info"):
            basic_info["has_hdr"] = True
            basic_info["hdr_type"] = media_info["hdr_info"].get("type", "")
        
        media_info["basic_info"] = basic_info
        
        # Log successful processing
        print(f"DEBUG: Successfully processed technical info for media ID: {media_id}")
        
        return jsonify(media_info)
    except Exception as e:
        # Enhanced error logging
        import traceback
        import sys
        print(f"DEBUG: Error processing technical info for media ID: {media_id}")
        print(f"DEBUG: Error type: {type(e).__name__}")
        print(f"DEBUG: Error message: {str(e)}")
        print(f"DEBUG: Traceback: {traceback.format_exc()}")
        
        return jsonify({"error": f"Error getting technical info: {str(e)}"}), 500