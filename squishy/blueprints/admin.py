"""Admin blueprint for Squishy."""

import os
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
from squishy.scanner import scan_filesystem, scan_jellyfin, scan_plex

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

    if scan_type == "filesystem":
        scan_filesystem([config.media_path])
        flash("Filesystem scan completed")
    elif scan_type == "jellyfin" and config.jellyfin_url and config.jellyfin_api_key:
        scan_jellyfin(config.jellyfin_url, config.jellyfin_api_key)
        flash("Jellyfin scan completed")
    elif scan_type == "plex" and config.plex_url and config.plex_token:
        scan_plex(config.plex_url, config.plex_token)
        flash("Plex scan completed")
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

        config = load_config()
        config.profiles[name] = TranscodeProfile(
            name=name,
            resolution=resolution,
            codec=codec,
            container=container,
            quality=quality,
            bitrate=bitrate,
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
    """Browse filesystem directories for the file browser modal."""
    path = request.args.get("path", "/")
    
    # Sanitize path to prevent directory traversal attacks
    path = os.path.normpath(path)
    if not path.startswith("/"):
        path = "/"
    
    try:
        # Get directories in the specified path
        entries = os.listdir(path)
        directories = []
        
        for entry in entries:
            full_path = os.path.join(path, entry)
            if os.path.isdir(full_path) and not entry.startswith('.'):
                directories.append(entry)
        
        # Sort directories alphabetically
        directories.sort()
        
        return jsonify({
            "path": path,
            "directories": directories
        })
    except (FileNotFoundError, PermissionError) as e:
        return jsonify({
            "error": f"Could not access directory: {str(e)}"
        }), 400
