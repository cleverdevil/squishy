"""API blueprint for Squishy."""

from flask import Blueprint, jsonify, request, current_app

from squishy.config import load_config
from squishy.models import TranscodeJob
from squishy.scanner import get_all_media, get_media, get_scan_status
from squishy.transcoder import create_job, get_job, start_transcode

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

@api_bp.route("/profiles", methods=["GET"])
def list_profiles():
    """List all transcoding profiles."""
    config = load_config()
    
    return jsonify({
        "profiles": [
            {
                "name": profile.name,
                "resolution": profile.resolution,
                "codec": profile.codec,
                "container": profile.container,
                "quality": profile.quality,
                "bitrate": profile.bitrate,
            }
            for profile in config.profiles.values()
        ]
    })

@api_bp.route("/transcode", methods=["POST"])
def transcode():
    """Start a transcoding job."""
    data = request.json
    if not data or "media_id" not in data or "profile" not in data:
        return jsonify({"error": "Missing required fields"}), 400
    
    media_id = data["media_id"]
    profile_name = data["profile"]
    
    media_item = get_media(media_id)
    if media_item is None:
        return jsonify({"error": "Media not found"}), 404
    
    config = load_config()
    if profile_name not in config.profiles:
        return jsonify({"error": "Invalid profile"}), 400
    
    job = create_job(media_item, profile_name)
    start_transcode(
        job,
        media_item,
        config.profiles[profile_name],
        current_app.config["TRANSCODE_PATH"],
    )
    
    return jsonify({
        "job_id": job.id,
        "status": job.status,
        "media_id": media_id,
        "profile": profile_name,
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
                "profile": job.profile_name,
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
        "profile": job.profile_name,
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
