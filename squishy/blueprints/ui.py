"""User interface blueprint."""

import os
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_file,
)

from squishy.config import load_config
from squishy.scanner import get_media, get_show
from squishy.transcoder import (
    JOBS,
    create_job,
    start_transcode,
    apply_output_path_mapping,
    remove_job as remove_transcode_job,
    cancel_job as cancel_transcode_job,
)
from squishy.completed import get_completed_transcodes, delete_transcode

ui_bp = Blueprint("ui", __name__)


# Helper function to format file size
def format_file_size(bytes_size):
    if bytes_size < 1024 * 1024:  # Less than 1 MB
        return f"{round(bytes_size / 1024, 2)} KB"
    elif bytes_size < 1024 * 1024 * 1024:  # Less than 1 GB
        return f"{round(bytes_size / (1024 * 1024), 2)} MB"
    else:  # GB or larger
        return f"{round(bytes_size / (1024 * 1024 * 1024), 2)} GB"


@ui_bp.route("/")
def index():
    """Display the home page with client-side pagination and search."""
    # Get search query for initial state
    search_query = request.args.get("q", "").strip().lower()

    # We will load the media via AJAX, so just pass minimal parameters to the template
    return render_template("ui/index.html", search_query=search_query)


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
        profiles=config.presets,
    )


@ui_bp.route("/shows/<show_id>")
def show_detail(show_id):
    """Display details for a TV show."""
    show = get_show(show_id)
    if show is None:
        flash("Show not found")
        return redirect(url_for("ui.index"))

    config = load_config()

    # Count episodes for display and collect episode IDs for validation
    episode_count = 0
    episode_ids = []
    valid_episode_ids = set()

    for season in show.seasons.values():
        for episode in season.episodes.values():
            episode_count += 1
            # Verify each episode exists in MEDIA dictionary
            media_item = get_media(episode.id)
            if not media_item:
                print(
                    f"WARNING: Episode {episode.id} from show {show_id} not found in MEDIA dictionary"
                )
            else:
                episode_ids.append(episode.id)
                valid_episode_ids.add(episode.id)

    # Log total episode count
    print(
        f"Show {show_id} has {episode_count} episodes, {len(episode_ids)} valid in MEDIA dictionary"
    )

    return render_template(
        "ui/show_detail.html",
        show=show,
        profiles=config.presets,
        episode_count=episode_count,
        valid_episode_ids=valid_episode_ids,
    )


@ui_bp.route("/transcode/<media_id>", methods=["POST"])
def transcode(media_id):
    """Start a transcoding job."""
    preset_name = request.form["preset_name"]

    media_item = get_media(media_id)
    if media_item is None:
        flash("Media not found")
        return redirect(url_for("ui.index"))

    config = load_config()
    if preset_name not in config.presets:
        flash("Invalid preset")
        if media_item.type == "movie":
            return redirect(url_for("ui.media_detail", media_id=media_id))
        else:  # episode
            return redirect(url_for("ui.show_detail", show_id=media_item.show_id))

    job = create_job(media_item, preset_name)
    start_transcode(job, media_item, preset_name, config.transcode_path)

    flash(f"Transcoding job started with preset: {preset_name}")

    # Return to the appropriate page
    if media_item.type == "movie":
        return redirect(url_for("ui.media_detail", media_id=media_id))
    else:  # episode
        return redirect(url_for("ui.show_detail", show_id=media_item.show_id))


@ui_bp.route("/jobs")
def jobs():
    """Display transcoding jobs grouped by status."""

    # Get media items for each job to display title instead of ID
    active_jobs = []
    completed_jobs = []
    failed_jobs = []

    for job in JOBS.values():
        media_item = get_media(job.media_id)
        if media_item:
            # Get file size in a human-readable format
            try:
                file_size_bytes = os.path.getsize(media_item.path)
                file_size = format_file_size(file_size_bytes)

                # If job is completed and has output path, show both sizes and compression percentage
                if (
                    job.status == "completed"
                    and job.output_path
                    and os.path.exists(job.output_path)
                ):
                    output_size_bytes = os.path.getsize(job.output_path)
                    output_size = format_file_size(output_size_bytes)

                    # Calculate compression percentage
                    if file_size_bytes > 0:
                        compression_pct = 100 - (
                            output_size_bytes / file_size_bytes * 100
                        )
                        file_size = f"{file_size} → {output_size} ({compression_pct:.1f}% smaller)"

                # For TV shows, include show title
                if media_item.type == "episode" and media_item.show_id:
                    show = get_show(media_item.show_id)
                    if show:
                        media_title = f"{show.title} - {media_item.display_name}"
                    else:
                        media_title = media_item.display_name
                else:
                    media_title = media_item.display_name

                job_data = {
                    "job": job,
                    "media_title": media_title,
                    "file_size": file_size,
                }

                # Categorize job by status
                if job.status in ["processing", "pending"]:
                    active_jobs.append(job_data)
                elif job.status == "completed":
                    completed_jobs.append(job_data)
                else:  # failed or cancelled
                    failed_jobs.append(job_data)

            except (FileNotFoundError, OSError):
                # Handle case where file doesn't exist or can't be accessed
                job_data = {
                    "job": job,
                    "media_title": media_item.display_name if media_item else "Unknown",
                    "file_size": "N/A",
                }

                # Categorize job by status
                if job.status in ["processing", "pending"]:
                    active_jobs.append(job_data)
                elif job.status == "completed":
                    completed_jobs.append(job_data)
                else:  # failed or cancelled
                    failed_jobs.append(job_data)
        else:
            job_data = {"job": job, "media_title": "Unknown", "file_size": "N/A"}

            # Categorize job by status
            if job.status in ["processing", "pending"]:
                active_jobs.append(job_data)
            elif job.status == "completed":
                completed_jobs.append(job_data)
            else:  # failed or cancelled
                failed_jobs.append(job_data)

    # Sort active jobs to put processing ones first, then pending ones
    active_jobs.sort(key=lambda x: 0 if x["job"].status == "processing" else 1)

    return render_template(
        "ui/jobs.html",
        active_jobs=active_jobs,
        completed_jobs=completed_jobs,
        failed_jobs=failed_jobs,
    )


@ui_bp.route("/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    """Cancel a transcoding job."""

    success = cancel_transcode_job(job_id)
    if success:
        flash("Job cancelled successfully")
    else:
        flash("Could not cancel job", "error")

    return redirect(url_for("ui.jobs"))


@ui_bp.route("/jobs/<job_id>/remove", methods=["POST"])
def remove_job(job_id):
    """Remove a completed, failed, or cancelled job."""

    success = remove_transcode_job(job_id)
    if success:
        flash("Job removed successfully")
    else:
        flash("Could not remove job", "error")

    return redirect(url_for("ui.jobs"))


@ui_bp.route("/completed")
def completed():
    """Display completed transcodes."""
    # Load config to get transcode path
    config = load_config()
    completed_transcodes = get_completed_transcodes(config.transcode_path)

    # Add original file size and compression details
    for transcode in completed_transcodes:
        if "original_path" in transcode and os.path.exists(transcode["original_path"]):
            # Get original file size
            original_size_bytes = os.path.getsize(transcode["original_path"])
            original_size = format_file_size(original_size_bytes)

            # Get transcoded file size
            output_size_bytes = os.path.getsize(transcode["file_path"])
            output_size = format_file_size(output_size_bytes)

            # Calculate compression percentage
            if original_size_bytes > 0:
                compression_pct = 100 - (output_size_bytes / original_size_bytes * 100)
                transcode["size_comparison"] = (
                    f"{original_size} → {output_size} ({compression_pct:.1f}% smaller)"
                )
            else:
                transcode["size_comparison"] = output_size
        else:
            transcode["size_comparison"] = transcode.get("output_size", "Unknown")

    return render_template("ui/completed.html", transcodes=completed_transcodes)


@ui_bp.route("/download/<filename>")
def download_file(filename):
    """Serve a file for download."""
    # Load config to get transcode path
    config = load_config()
    transcode_path = config.transcode_path

    # Apply path mappings to transcode_path
    transcode_path = apply_output_path_mapping(transcode_path)

    file_path = os.path.join(transcode_path, filename)

    # Verify the file exists and is within transcode_path
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        flash("File not found")
        return redirect(url_for("ui.completed"))

    # Security check - make sure the file is in the transcode directory
    real_transcode_path = os.path.realpath(transcode_path)
    real_file_path = os.path.realpath(file_path)
    if not real_file_path.startswith(real_transcode_path):
        flash("Invalid file path")
        return redirect(url_for("ui.completed"))

    # Set download flag to trigger "Save As" dialog
    return send_file(file_path, as_attachment=True)


@ui_bp.route("/download-episode/<media_id>")
def download_episode(media_id):
    """Serve an episode file for download."""
    media_item = get_media(media_id)
    if media_item is None:
        flash("Media not found")
        return redirect(url_for("ui.index"))

    # Verify the episode file exists
    if (
        not media_item.path
        or not os.path.exists(media_item.path)
        or not os.path.isfile(media_item.path)
    ):
        flash("Episode file not found")
        if media_item.show_id:
            return redirect(url_for("ui.show_detail", show_id=media_item.show_id))
        return redirect(url_for("ui.index"))

    # Extract filename from path for attachment name
    filename = os.path.basename(media_item.path)

    # Set download flag to trigger "Save As" dialog
    return send_file(media_item.path, as_attachment=True, download_name=filename)


@ui_bp.route("/completed/delete/<filename>", methods=["POST"])
def delete_completed_transcode(filename):
    """Delete a completed transcode and its metadata file."""
    # Load config to get transcode path
    config = load_config()
    transcode_path = config.transcode_path

    # Call the delete function from the completed module
    success, message = delete_transcode(filename, transcode_path)

    if success:
        flash(f"Transcode deleted: {message}")
    else:
        flash(f"Error deleting transcode: {message}", "error")

    return redirect(url_for("ui.completed"))


@ui_bp.route("/test-responsive")
def test_responsive():
    """Test page for responsive design."""
    return render_template("test_responsive.html")


@ui_bp.route("/test-tables")
def test_tables():
    """Test page for responsive tables."""
    return render_template("test_tables.html")
