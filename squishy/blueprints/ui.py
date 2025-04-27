"""User interface blueprint."""

import os
from flask import (
    Blueprint, render_template, request, redirect, url_for, current_app,
    flash
)

from squishy.config import load_config
from squishy.scanner import get_all_media, get_media, get_shows_and_movies, get_show
from squishy.transcoder import create_job, get_job, start_transcode

ui_bp = Blueprint("ui", __name__)

@ui_bp.route("/")
def index():
    """Display the home page with pagination and search."""
    # Get search query and pagination parameters
    search_query = request.args.get('q', '').strip().lower()
    show_page = max(1, int(request.args.get('show_page', 1)))
    movie_page = max(1, int(request.args.get('movie_page', 1)))
    
    # Get all shows and movies
    all_shows, all_movies = get_shows_and_movies()
    
    # Sort alphabetically by title
    all_shows = sorted(all_shows, key=lambda x: x.title.lower())
    all_movies = sorted(all_movies, key=lambda x: x.title.lower())
    
    # Filter by search query if provided
    if search_query:
        all_shows = [show for show in all_shows if search_query in show.title.lower()]
        all_movies = [movie for movie in all_movies if search_query in movie.title.lower()]
    
    # Calculate pagination for shows
    items_per_page = 50
    total_shows = len(all_shows)
    total_show_pages = max(1, (total_shows + items_per_page - 1) // items_per_page)
    show_page = min(show_page, total_show_pages)
    show_start_idx = (show_page - 1) * items_per_page
    show_end_idx = min(show_start_idx + items_per_page, total_shows)
    paginated_shows = all_shows[show_start_idx:show_end_idx]
    
    # Calculate pagination for movies
    total_movies = len(all_movies)
    total_movie_pages = max(1, (total_movies + items_per_page - 1) // items_per_page)
    movie_page = min(movie_page, total_movie_pages)
    movie_start_idx = (movie_page - 1) * items_per_page
    movie_end_idx = min(movie_start_idx + items_per_page, total_movies)
    paginated_movies = all_movies[movie_start_idx:movie_end_idx]
    
    return render_template(
        "ui/index.html",
        shows=paginated_shows,
        total_shows=total_shows,
        show_page=show_page,
        total_show_pages=total_show_pages,
        movies=paginated_movies,
        total_movies=total_movies,
        movie_page=movie_page,
        total_movie_pages=total_movie_pages,
        search_query=search_query
    )

@ui_bp.route("/media/<media_id>")
def media_detail(media_id):
    """Display details for a specific media item."""
    media_item = get_media(media_id)
    if media_item is None:
        flash("Media not found")
        return redirect(url_for("ui.index"))
    
    config = load_config()
    
    # If this is an episode, redirect to the show detail page
    if media_item.type == "episode" and media_item.show_id:
        return redirect(url_for("ui.show_detail", show_id=media_item.show_id))
    
    return render_template(
        "ui/media_detail.html",
        media=media_item,
        profiles=config.profiles,
    )

@ui_bp.route("/shows/<show_id>")
def show_detail(show_id):
    """Display details for a TV show."""
    show = get_show(show_id)
    if show is None:
        flash("Show not found")
        return redirect(url_for("ui.index"))
    
    config = load_config()
    return render_template(
        "ui/show_detail.html",
        show=show,
        profiles=config.profiles,
    )

@ui_bp.route("/transcode/<media_id>", methods=["POST"])
def transcode(media_id):
    """Start a transcoding job."""
    profile_name = request.form["profile"]
    
    media_item = get_media(media_id)
    if media_item is None:
        flash("Media not found")
        return redirect(url_for("ui.index"))
    
    config = load_config()
    if profile_name not in config.profiles:
        flash("Invalid profile")
        if media_item.type == "movie":
            return redirect(url_for("ui.media_detail", media_id=media_id))
        else:  # episode
            return redirect(url_for("ui.show_detail", show_id=media_item.show_id))
    
    job = create_job(media_item, profile_name)
    start_transcode(
        job,
        media_item,
        config.profiles[profile_name],
        current_app.config["TRANSCODE_PATH"],
    )
    
    flash(f"Transcoding job started with profile: {profile_name}")
    
    # Return to the appropriate page
    if media_item.type == "movie":
        return redirect(url_for("ui.media_detail", media_id=media_id))
    else:  # episode
        return redirect(url_for("ui.show_detail", show_id=media_item.show_id))

@ui_bp.route("/jobs")
def jobs():
    """Display transcoding jobs."""
    from squishy.transcoder import JOBS
    
    # Get media items for each job to display title instead of ID
    job_data = []
    for job in JOBS.values():
        media_item = get_media(job.media_id)
        if media_item:
            # Get file size in a human-readable format
            try:
                file_size_bytes = os.path.getsize(media_item.path)
                # Format file size in a human-readable way
                if file_size_bytes < 1024 * 1024:  # Less than 1 MB
                    file_size = f"{round(file_size_bytes / 1024, 2)} KB"
                elif file_size_bytes < 1024 * 1024 * 1024:  # Less than 1 GB
                    file_size = f"{round(file_size_bytes / (1024 * 1024), 2)} MB"
                else:  # GB or larger
                    file_size = f"{round(file_size_bytes / (1024 * 1024 * 1024), 2)} GB"
                
                # For TV shows, include show title
                if media_item.type == "episode" and media_item.show_id:
                    show = get_show(media_item.show_id)
                    if show:
                        media_title = f"{show.title} - {media_item.display_name}"
                    else:
                        media_title = media_item.display_name
                else:
                    media_title = media_item.display_name
                
                job_data.append({
                    "job": job,
                    "media_title": media_title,
                    "file_size": file_size
                })
            except (FileNotFoundError, OSError):
                # Handle case where file doesn't exist or can't be accessed
                job_data.append({
                    "job": job,
                    "media_title": media_item.display_name if media_item else "Unknown",
                    "file_size": "N/A"
                })
        else:
            job_data.append({
                "job": job,
                "media_title": "Unknown",
                "file_size": "N/A"
            })
    
    return render_template("ui/jobs.html", job_data=job_data)
@ui_bp.route("/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    """Cancel a transcoding job."""
    from squishy.transcoder import cancel_job as cancel_transcode_job
    
    success = cancel_transcode_job(job_id)
    if success:
        flash("Job cancelled successfully")
    else:
        flash("Could not cancel job", "error")
    
    return redirect(url_for("ui.jobs"))
