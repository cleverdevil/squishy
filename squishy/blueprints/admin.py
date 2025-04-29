"""Admin blueprint for Squishy."""

import os
import json
import requests
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    current_app,
    flash,
    jsonify,
)

from squishy.config import load_config, save_config, TranscodeProfile, Config
from squishy.scanner import (
    scan_filesystem, scan_jellyfin, scan_plex,
    scan_filesystem_async, scan_jellyfin_async, scan_plex_async
)
from squishy.transcoder import detect_hw_accel, process_job_queue, get_running_job_count

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/")
def index():
    """Admin dashboard."""
    config = load_config()
    return render_template("admin/index.html", config=config)


@admin_bp.route("/scan", methods=["POST"])
def scan():
    """Scan for media files."""
    scan_type = request.form["scan_type"]
    config = load_config()

    if scan_type == "jellyfin" and config.jellyfin_url and config.jellyfin_api_key:
        scan_jellyfin_async(config.jellyfin_url, config.jellyfin_api_key)
        flash("Jellyfin scan started in background")
    elif scan_type == "plex" and config.plex_url and config.plex_token:
        scan_plex_async(config.plex_url, config.plex_token)
        flash("Plex scan started in background")
    else:
        flash("Invalid scan type or missing configuration")

    return redirect(url_for("admin.index"))


@admin_bp.route("/profiles")
def list_profiles():
    """List transcoding profiles."""
    config = load_config()
    return render_template("admin/profiles.html", profiles=config.profiles.values())


@admin_bp.route("/profiles/add", methods=["GET", "POST"])
def add_profile():
    """Add a new transcoding profile."""
    if request.method == "POST":
        name = request.form["name"]
        resolution = request.form["resolution"]
        codec = request.form["codec"]
        container = request.form["container"]
        quality = request.form["quality"]
        bitrate = request.form.get("bitrate")
        hw_accel = request.form.get("hw_accel")
        hw_device = request.form.get("hw_device")

        config = load_config()
        config.profiles[name] = TranscodeProfile(
            name=name,
            resolution=resolution,
            codec=codec,
            container=container,
            quality=quality,
            bitrate=bitrate,
            hw_accel=hw_accel if hw_accel else None,
            hw_device=hw_device if hw_device else None,
        )
        save_config(config)

        flash(f"Profile {name} added")
        return redirect(url_for("admin.list_profiles"))

    return render_template("admin/add_profile.html")


@admin_bp.route("/profiles/<name>/edit", methods=["GET", "POST"])
def edit_profile(name):
    """Edit a transcoding profile."""
    config = load_config()
    if name not in config.profiles:
        flash(f"Profile {name} not found")
        return redirect(url_for("admin.list_profiles"))

    profile = config.profiles[name]

    if request.method == "POST":
        profile.resolution = request.form["resolution"]
        profile.codec = request.form["codec"]
        profile.container = request.form["container"]
        profile.quality = request.form["quality"]
        profile.bitrate = request.form.get("bitrate")
        
        # Update hardware acceleration settings
        hw_accel = request.form.get("hw_accel")
        hw_device = request.form.get("hw_device")
        profile.hw_accel = hw_accel if hw_accel else None
        profile.hw_device = hw_device if hw_device else None

        save_config(config)

        flash(f"Profile {name} updated")
        return redirect(url_for("admin.list_profiles"))

    return render_template("admin/edit_profile.html", profile=profile)


@admin_bp.route("/profiles/<name>/delete", methods=["POST"])
def delete_profile(name):
    """Delete a transcoding profile."""
    config = load_config()
    if name not in config.profiles:
        flash(f"Profile {name} not found")
        return redirect(url_for("admin.list_profiles"))

    del config.profiles[name]
    save_config(config)

    flash(f"Profile {name} deleted")
    return redirect(url_for("admin.list_profiles"))


@admin_bp.route("/update_source", methods=["POST"])
def update_source():
    """Update the media source configuration."""
    config = load_config()
    source = request.form["source"]
    
    # Reset all source configurations
    config.jellyfin_url = None
    config.jellyfin_api_key = None
    config.plex_url = None
    config.plex_token = None
    
    # Set the selected source
    if source == "jellyfin":
        config.jellyfin_url = request.form["jellyfin_url"]
        config.jellyfin_api_key = request.form["jellyfin_api_key"]
    elif source == "plex":
        config.plex_url = request.form["plex_url"]
        config.plex_token = request.form["plex_token"]
    else:
        flash("You must configure either Jellyfin or Plex to use Squishy")
        return redirect(url_for("admin.index"))
    
    save_config(config)
    flash(f"Media source updated to {source}")
    return redirect(url_for("admin.index"))


@admin_bp.route("/update_paths", methods=["POST"])
def update_paths():
    """Update the media path and transcode path configuration."""
    config = load_config()
    
    # Get media path
    media_path = request.form["media_path"].strip()
    
    # Get transcode path
    transcode_path = request.form["transcode_path"].strip()
    
    # Update config
    config.media_path = media_path
    config.transcode_path = transcode_path
    
    save_config(config)
    flash("Path configuration updated")
    return redirect(url_for("admin.index"))


@admin_bp.route("/browse_filesystem")
def browse_filesystem():
    """Browse filesystem directories and files for the file browser modal."""
    path = request.args.get("path", "/")
    file_type = request.args.get("type", "directory")  # 'directory' or 'file'
    
    # Sanitize path to prevent directory traversal attacks
    path = os.path.normpath(path)
    if not path.startswith("/"):
        path = "/"
    
    try:
        # Get entries in the specified path
        entries = os.listdir(path)
        directories = []
        files = []
        
        for entry in entries:
            if entry.startswith('.'):
                continue
                
            full_path = os.path.join(path, entry)
            if os.path.isdir(full_path):
                directories.append(entry)
            elif file_type == "file" and os.path.isfile(full_path):
                # For ffmpeg path, we want to show executable files
                if entry == "ffmpeg" or entry.endswith(".exe"):
                    files.append(entry)
        
        # Sort entries alphabetically
        directories.sort()
        files.sort()
        
        return jsonify({
            "path": path,
            "directories": directories,
            "files": files
        })
    except (FileNotFoundError, PermissionError) as e:
        return jsonify({
            "error": f"Could not access directory: {str(e)}"
        }), 400


@admin_bp.route("/api/libraries")
def list_libraries():
    """List all available libraries from the configured media server."""
    config = load_config()
    libraries = []
    
    try:
        if config.plex_url and config.plex_token:
            # Get Plex libraries
            headers = {
                "X-Plex-Token": config.plex_token,
                "Accept": "application/json",
            }
            response = requests.get(f"{config.plex_url}/library/sections", headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                sections = data.get("MediaContainer", {}).get("Directory", [])
                
                for section in sections:
                    section_id = section.get("key")
                    if section_id:
                        libraries.append({
                            "id": section_id,
                            "title": section.get("title", "Unknown"),
                            "type": section.get("type", "unknown"),
                            "enabled": config.enabled_libraries.get(section_id, True),
                            "server": "plex"
                        })
        
        elif config.jellyfin_url and config.jellyfin_api_key:
            # Get Jellyfin libraries
            headers = {
                "X-MediaBrowser-Token": config.jellyfin_api_key,
                "Content-Type": "application/json",
            }
            response = requests.get(f"{config.jellyfin_url}/Library/VirtualFolders", headers=headers)
            
            if response.status_code == 200:
                sections = response.json()
                
                for section in sections:
                    section_id = section.get("ItemId")
                    if section_id:
                        libraries.append({
                            "id": section_id,
                            "title": section.get("Name", "Unknown"),
                            "type": section.get("CollectionType", "unknown").lower(),
                            "enabled": config.enabled_libraries.get(section_id, True),
                            "server": "jellyfin"
                        })
        
        return jsonify({"libraries": libraries})
    
    except Exception as e:
        current_app.logger.error(f"Error fetching libraries: {str(e)}")
        return jsonify({"error": str(e), "libraries": []})


@admin_bp.route("/update_libraries", methods=["POST"])
def update_libraries():
    """Update library configuration and trigger a scan."""
    config = load_config()
    
    # Get the enabled library IDs from the form
    enabled_libraries = request.form.getlist("enabled_libraries[]")
    
    # Get all libraries to set the proper state for each
    all_libraries = []
    
    if config.jellyfin_url and config.jellyfin_api_key:
        # Get Jellyfin libraries
        headers = {
            "X-MediaBrowser-Token": config.jellyfin_api_key,
            "Content-Type": "application/json",
        }
        response = requests.get(f"{config.jellyfin_url}/Library/VirtualFolders", headers=headers)
        
        if response.status_code == 200:
            sections = response.json()
            
            for section in sections:
                section_id = section.get("ItemId")
                if section_id:
                    all_libraries.append(section_id)
    
    elif config.plex_url and config.plex_token:
        # Get Plex libraries
        headers = {
            "X-Plex-Token": config.plex_token,
            "Accept": "application/json",
        }
        response = requests.get(f"{config.plex_url}/library/sections", headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            sections = data.get("MediaContainer", {}).get("Directory", [])
            
            for section in sections:
                section_id = section.get("key")
                if section_id:
                    all_libraries.append(section_id)
    
    # Update enabled_libraries in config
    new_enabled_libraries = {}
    for library_id in all_libraries:
        new_enabled_libraries[library_id] = library_id in enabled_libraries
    
    config.enabled_libraries = new_enabled_libraries
    
    # Save the config
    save_config(config)
    
    # Clear existing media and trigger a new scan
    from squishy.scanner import MEDIA, TV_SHOWS, scan_jellyfin_async, scan_plex_async
    
    # Clear existing media items
    MEDIA.clear()
    TV_SHOWS.clear()
    
    # Start a new scan in background
    if config.jellyfin_url and config.jellyfin_api_key:
        scan_jellyfin_async(config.jellyfin_url, config.jellyfin_api_key)
        flash("Library configuration updated and Jellyfin scan started")
    elif config.plex_url and config.plex_token:
        scan_plex_async(config.plex_url, config.plex_token)
        flash("Library configuration updated and Plex scan started")
    else:
        flash("Library configuration updated, but no media server is configured")
    
    return redirect(url_for("admin.index"))


@admin_bp.route("/update_path_mappings", methods=["POST"])
def update_path_mappings():
    """Update path mapping configuration."""
    config = load_config()
    
    # Get source and target paths from form
    source_path = request.form.get("source_path", "").strip()
    target_path = request.form.get("target_path", "").strip()
    
    # Create new path mappings dictionary
    path_mappings = {}
    if source_path and target_path:  # Only add if both fields are filled
        path_mappings[source_path] = target_path
    
    # Update config
    config.path_mappings = path_mappings
    
    save_config(config)
    flash("Path mapping updated")
    return redirect(url_for("admin.index"))


@admin_bp.route("/update_paths_and_mapping", methods=["POST"])
def update_paths_and_mapping():
    """Update both path configuration and path mapping."""
    config = load_config()
    
    # Get media and transcode paths
    media_path = request.form["media_path"].strip()
    transcode_path = request.form["transcode_path"].strip()
    ffmpeg_path = request.form["ffmpeg_path"].strip()
    
    # Get max concurrent jobs
    try:
        max_concurrent_jobs = int(request.form["max_concurrent_jobs"])
        if max_concurrent_jobs < 1:
            max_concurrent_jobs = 1
    except (ValueError, KeyError):
        max_concurrent_jobs = 1
    
    # Get source and target paths for mapping
    # We now support multiple path mappings
    # Format in form data: source_path_1, target_path_1, source_path_2, target_path_2, etc.
    path_mappings = {}
    
    # First check the legacy single mapping fields
    source_path = request.form.get("source_path", "").strip()
    target_path = request.form.get("target_path", "").strip()
    if source_path and target_path:
        path_mappings[source_path] = target_path
    
    # Then check for multiple mappings using numbered fields
    i = 1
    while True:
        source_key = f"source_path_{i}"
        target_key = f"target_path_{i}"
        
        if source_key not in request.form or target_key not in request.form:
            break
            
        source = request.form.get(source_key, "").strip()
        target = request.form.get(target_key, "").strip()
        
        if source and target:
            path_mappings[source] = target
            
        i += 1
    
    # Check if the concurrent job limit changed
    old_max_concurrent_jobs = config.max_concurrent_jobs
    new_max_concurrent_jobs = max_concurrent_jobs
    
    # Update config
    config.media_path = media_path
    config.transcode_path = transcode_path
    config.ffmpeg_path = ffmpeg_path
    config.max_concurrent_jobs = new_max_concurrent_jobs
    
    # Update hardware acceleration settings
    hw_accel = request.form.get("hw_accel")
    hw_device = request.form.get("hw_device")
    config.hw_accel = hw_accel if hw_accel else None
    config.hw_device = hw_device if hw_device and hw_accel else None
    
    # Set the path mappings
    config.path_mappings = path_mappings
    
    # Log the path mappings for debugging
    if path_mappings:
        current_app.logger.debug(f"Updated path mappings: {path_mappings}")
    else:
        current_app.logger.debug("No path mappings configured")
    
    # Save config first so process_job_queue uses the updated max_concurrent_jobs
    save_config(config)
    
    # Check job queue if concurrent jobs limit changed
    if new_max_concurrent_jobs != old_max_concurrent_jobs:
        current_job_count = get_running_job_count()
        
        # Get pending job count for better messaging
        from squishy.transcoder import get_pending_jobs, JOB_QUEUE
        pending_jobs = get_pending_jobs()
        
        if new_max_concurrent_jobs > old_max_concurrent_jobs:
            # If limit was increased, process the queue to start pending jobs
            current_app.logger.info(f"Concurrent job limit increased from {old_max_concurrent_jobs} to {new_max_concurrent_jobs}. Processing job queue with {len(pending_jobs)} pending jobs.")
            
            # Process the job queue immediately
            process_job_queue()
            
            if pending_jobs:
                flash(f"Increased concurrent job limit to {new_max_concurrent_jobs}. Starting pending jobs ({len(pending_jobs)}).")
            else:
                flash(f"Increased concurrent job limit to {new_max_concurrent_jobs}. No pending jobs to start.")
        elif new_max_concurrent_jobs < current_job_count:
            # If limit was reduced and we have more running jobs than the new limit,
            # we don't automatically cancel jobs, but inform the user
            current_app.logger.info(f"Concurrent job limit decreased from {old_max_concurrent_jobs} to {new_max_concurrent_jobs}. Currently running {current_job_count} jobs.")
            flash(f"Reduced concurrent job limit to {new_max_concurrent_jobs}. Currently running {current_job_count} jobs. New jobs will only start when current ones complete.")
        else:
            flash(f"Updated concurrent job limit to {new_max_concurrent_jobs}.")
    flash("Path configuration updated")
    return redirect(url_for("admin.index"))


@admin_bp.route("/detect_hw_accel")
def detect_hw_accel_route():
    """Detect available hardware acceleration methods and return as JSON."""
    config = load_config()
    ffmpeg_path = config.ffmpeg_path
    
    # Run detection
    hw_accel_info = detect_hw_accel(ffmpeg_path)
    
    # Automatically set the recommended hardware acceleration method
    if hw_accel_info["recommended"]["method"]:
        config.hw_accel = hw_accel_info["recommended"]["method"]
        config.hw_device = hw_accel_info["recommended"]["device"]
        save_config(config)
        hw_accel_info["auto_configured"] = True
    
    return jsonify(hw_accel_info)