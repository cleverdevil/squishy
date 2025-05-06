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

from squishy.config import load_config, save_config
from squishy.scanner import scan_jellyfin_async, scan_plex_async
from squishy.transcoder import (
    detect_hw_accel,
    process_job_queue,
    get_running_job_count,
    get_pending_jobs,
)


admin_bp = Blueprint("admin", __name__)


codecs = [
    {"value": "h264", "label": "H.264 (AVC)"},
    {"value": "hevc", "label": "H.265 (HEVC)"},
    {"value": "vp9", "label": "VP9"},
    {"value": "av1", "label": "AV1"},
]

containers = [
    {"value": ".mp4", "label": "MP4"},
    {"value": ".mkv", "label": "MKV"},
    {"value": ".webm", "label": "WebM"},
    {"value": ".mov", "label": "MOV"},
]

scales = [
    {"value": "360p", "label": "360p"},
    {"value": "480p", "label": "480p"},
    {"value": "720p", "label": "720p"},
    {"value": "1080p", "label": "1080p"},
    {"value": "2160p", "label": "4K (2160p)"},
]

audio_codecs = [
    {"value": "aac", "label": "AAC"},
    {"value": "opus", "label": "Opus"},
    {"value": "flac", "label": "FLAC"},
    {"value": "copy", "label": "Copy (passthrough)"},
]

audio_bitrates = [
    {"value": "64k", "label": "64 kbps (low)"},
    {"value": "96k", "label": "96 kbps (medium)"},
    {"value": "128k", "label": "128 kbps (standard)"},
    {"value": "192k", "label": "192 kbps (high)"},
    {"value": "256k", "label": "256 kbps (very high)"},
]


@admin_bp.route("/")
def index():
    """Admin dashboard."""
    config = load_config()

    # Get hardware capabilities from config
    capabilities_json = config.hw_capabilities

    if capabilities_json:
        current_app.logger.debug("Using hardware capabilities from config")
    else:
        current_app.logger.debug("No hardware capabilities found in config")

    return render_template(
        "admin/index.html", config=config, capabilities_json=capabilities_json
    )


@admin_bp.route("/scan", methods=["POST"])
def scan():
    """Scan for media files from media server."""
    scan_type = request.form["scan_type"]
    config = load_config()

    if scan_type == "jellyfin" and config.jellyfin_url and config.jellyfin_api_key:
        scan_jellyfin_async(config.jellyfin_url, config.jellyfin_api_key)
        flash("Jellyfin scan started in background")
    elif scan_type == "plex" and config.plex_url and config.plex_token:
        scan_plex_async(config.plex_url, config.plex_token)
        flash("Plex scan started in background")
    else:
        flash(
            "Invalid scan type or missing configuration. Please configure either Jellyfin or Plex."
        )

    return redirect(url_for("admin.index"))


@admin_bp.route("/presets")
def list_presets():
    """List transcoding presets."""
    config = load_config()

    # Check if any effeffmpeg preset templates are available
    # Use a dictionary to ensure we don't have duplicates
    preset_templates_dict = {}

    # Check for the presets directory in effeffmpeg (local copy in Squishy)
    effeff_preset_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "presets"
    )
    if os.path.isdir(effeff_preset_dir):
        for filename in os.listdir(effeff_preset_dir):
            if filename.endswith(".json"):
                preset_name = os.path.splitext(filename)[0]
                # Clean up the name for display
                display_name = preset_name.replace("-", " ").title()
                # Prefer the local copy if it exists
                preset_templates_dict[filename] = {
                    "file_path": os.path.join(effeff_preset_dir, filename),
                    "name": preset_name,
                    "display_name": display_name,
                }

    # Also check in the original effeffmpeg package
    # Only add if not already found in the local directory
    package_preset_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "effeffmpeg", "presets"
    )
    if os.path.isdir(package_preset_dir):
        for filename in os.listdir(package_preset_dir):
            if filename.endswith(".json") and filename not in preset_templates_dict:
                preset_name = os.path.splitext(filename)[0]
                # Clean up the name for display
                display_name = preset_name.replace("-", " ").title()
                preset_templates_dict[filename] = {
                    "file_path": os.path.join(package_preset_dir, filename),
                    "name": preset_name,
                    "display_name": display_name,
                }

    # Convert dictionary to list for the template
    preset_templates = list(preset_templates_dict.values())

    return render_template(
        "admin/presets.html", presets=config.presets, preset_templates=preset_templates
    )


@admin_bp.route("/presets/add", methods=["GET", "POST"])
def add_preset():
    """Add a new transcoding preset."""
    if request.method == "POST":
        name = request.form["name"]
        codec = request.form["codec"]
        scale = request.form["scale"]
        container = request.form["container"]

        # Get quality settings (either CRF or bitrate)
        use_crf = request.form.get("use_crf", "false") == "true"
        if use_crf:
            crf = int(request.form["crf"])
            bitrate = None
        else:
            crf = None
            bitrate = request.form["bitrate"]

        audio_codec = request.form["audio_codec"]
        audio_bitrate = request.form["audio_bitrate"]

        # Hardware acceleration settings
        force_software = request.form.get("force_software") == "on"
        allow_fallback = request.form.get("allow_fallback") == "on"

        # Create the preset dictionary
        preset = {
            "codec": codec,
            "scale": scale,
            "container": container,
            "audio_codec": audio_codec,
            "audio_bitrate": audio_bitrate,
            "force_software": force_software,
            "allow_fallback": allow_fallback,
        }

        # Add either CRF or bitrate
        if use_crf and crf is not None:
            preset["crf"] = crf
        elif bitrate:
            preset["bitrate"] = bitrate

        # Add to config and save
        config = load_config()
        config.presets[name] = preset
        save_config(config)

        flash(f"Preset {name} added")
        return redirect(url_for("admin.list_presets"))

    # Pass codec and container options to the template

    return render_template(
        "admin/add_preset.html",
        codecs=codecs,
        containers=containers,
        scales=scales,
        audio_codecs=audio_codecs,
        audio_bitrates=audio_bitrates,
    )


@admin_bp.route("/presets/<name>/edit", methods=["GET", "POST"])
def edit_preset(name):
    """Edit a transcoding preset."""
    config = load_config()
    if name not in config.presets:
        flash(f"Preset {name} not found")
        return redirect(url_for("admin.list_presets"))

    preset = config.presets[name]

    if request.method == "POST":
        codec = request.form["codec"]
        scale = request.form["scale"]
        container = request.form["container"]

        # Get quality settings (either CRF or bitrate)
        use_crf = request.form.get("use_crf", "false") == "true"
        if use_crf:
            crf = int(request.form["crf"])
            bitrate = None
        else:
            crf = None
            bitrate = request.form["bitrate"]

        audio_codec = request.form["audio_codec"]
        audio_bitrate = request.form["audio_bitrate"]

        # Hardware acceleration settings
        force_software = request.form.get("force_software") == "on"
        allow_fallback = request.form.get("allow_fallback") == "on"

        # Update the preset
        preset = {
            "codec": codec,
            "scale": scale,
            "container": container,
            "audio_codec": audio_codec,
            "audio_bitrate": audio_bitrate,
            "force_software": force_software,
            "allow_fallback": allow_fallback,
        }

        # Add either CRF or bitrate
        if use_crf and crf is not None:
            preset["crf"] = crf
        elif bitrate:
            preset["bitrate"] = bitrate

        # Update config
        config.presets[name] = preset
        save_config(config)

        flash(f"Preset {name} updated")
        return redirect(url_for("admin.list_presets"))

    # Determine if preset uses CRF or bitrate
    use_crf = "crf" in preset

    return render_template(
        "admin/edit_preset.html",
        name=name,
        preset=preset,
        use_crf=use_crf,
        codecs=codecs,
        containers=containers,
        scales=scales,
        audio_codecs=audio_codecs,
        audio_bitrates=audio_bitrates,
    )


@admin_bp.route("/presets/<name>/delete", methods=["POST"])
def delete_preset(name):
    """Delete a transcoding preset."""
    config = load_config()
    if name not in config.presets:
        flash(f"Preset {name} not found")
        return redirect(url_for("admin.list_presets"))

    del config.presets[name]
    save_config(config)

    flash(f"Preset {name} deleted")
    return redirect(url_for("admin.list_presets"))


@admin_bp.route("/presets/import", methods=["POST"])
def import_presets():
    """Import presets from a file."""
    if "preset_file" in request.files:
        # Import from user-uploaded file
        preset_file = request.files["preset_file"]
        if preset_file.filename == "":
            flash("No file selected")
            return redirect(url_for("admin.list_presets"))

        try:
            preset_data = json.load(preset_file)
            presets = preset_data.get("presets", {})

            # Validate presets
            from squishy.effeffmpeg import validate_presets_data

            validate_presets_data(presets)

            # Update config with new presets
            config = load_config()

            # Check if we should overwrite or merge
            merge_mode = request.form.get("merge_mode", "overwrite")

            if merge_mode == "merge":
                # Merge presets (keeping existing ones if they conflict)
                for name, preset in presets.items():
                    if name not in config.presets:
                        config.presets[name] = preset
                flash(f"Imported {len(presets)} presets (merged with existing)")
            else:
                # Overwrite presets
                config.presets = presets
                flash(f"Imported {len(presets)} presets (replaced existing)")

            save_config(config)
            return redirect(url_for("admin.list_presets"))
        except Exception as e:
            flash(f"Error importing presets: {str(e)}")
            return redirect(url_for("admin.list_presets"))

    elif "template_file" in request.form:
        # Import from a template file
        template_path = request.form["template_file"]

        try:
            with open(template_path, "r") as f:
                preset_data = json.load(f)
                presets = preset_data.get("presets", {})

                # Validate presets
                from squishy.effeffmpeg import validate_presets_data

                validate_presets_data(presets)

                # Update config with new presets
                config = load_config()

                # Check if we should overwrite or merge
                merge_mode = request.form.get("merge_mode", "overwrite")

                if merge_mode == "merge":
                    # Merge presets (keeping existing ones if they conflict)
                    for name, preset in presets.items():
                        if name not in config.presets:
                            config.presets[name] = preset
                    flash(f"Imported {len(presets)} presets (merged with existing)")
                else:
                    # Overwrite presets
                    config.presets = presets
                    flash(f"Imported {len(presets)} presets (replaced existing)")

                save_config(config)
                return redirect(url_for("admin.list_presets"))
        except Exception as e:
            flash(f"Error importing presets: {str(e)}")
            return redirect(url_for("admin.list_presets"))

    flash("No preset file specified")
    return redirect(url_for("admin.list_presets"))


@admin_bp.route("/presets/export", methods=["GET"])
def export_presets():
    """Export presets to a JSON file."""
    config = load_config()

    # Create a JSON object with the presets
    export_data = {"presets": config.presets}

    # Create the response with the JSON data
    response = jsonify(export_data)
    response.headers["Content-Disposition"] = (
        "attachment; filename=squishy-presets.json"
    )
    return response


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
            if entry.startswith("."):
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

        return jsonify({"path": path, "directories": directories, "files": files})
    except (FileNotFoundError, PermissionError) as e:
        return jsonify({"error": f"Could not access directory: {str(e)}"}), 400


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
            response = requests.get(
                f"{config.plex_url}/library/sections", headers=headers
            )

            if response.status_code == 200:
                data = response.json()
                sections = data.get("MediaContainer", {}).get("Directory", [])

                for section in sections:
                    section_id = section.get("key")
                    if section_id:
                        libraries.append(
                            {
                                "id": section_id,
                                "title": section.get("title", "Unknown"),
                                "type": section.get("type", "unknown"),
                                "enabled": config.enabled_libraries.get(
                                    section_id, True
                                ),
                                "server": "plex",
                            }
                        )

        elif config.jellyfin_url and config.jellyfin_api_key:
            # Get Jellyfin libraries
            headers = {
                "X-MediaBrowser-Token": config.jellyfin_api_key,
                "Content-Type": "application/json",
            }
            response = requests.get(
                f"{config.jellyfin_url}/Library/VirtualFolders", headers=headers
            )

            if response.status_code == 200:
                sections = response.json()

                for section in sections:
                    section_id = section.get("ItemId")
                    if section_id:
                        libraries.append(
                            {
                                "id": section_id,
                                "title": section.get("Name", "Unknown"),
                                "type": section.get(
                                    "CollectionType", "unknown"
                                ).lower(),
                                "enabled": config.enabled_libraries.get(
                                    section_id, True
                                ),
                                "server": "jellyfin",
                            }
                        )

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
        response = requests.get(
            f"{config.jellyfin_url}/Library/VirtualFolders", headers=headers
        )

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


@admin_bp.route("/update_log_level", methods=["POST"])
def update_log_level():
    """Update application log level."""
    config = load_config()

    # Get the new log level
    log_level = request.form["log_level"].upper()

    # Validate log level
    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if log_level not in valid_levels:
        flash(f"Invalid log level: {log_level}. Using INFO instead.")
        log_level = "INFO"

    # Update config
    config.log_level = log_level
    save_config(config)

    # Update the current application's log level
    import logging

    logging.getLogger().setLevel(getattr(logging, log_level))

    flash(f"Log level updated to {log_level}")
    return redirect(url_for("admin.index"))


@admin_bp.route("/update_paths_and_hw", methods=["POST"])
def update_paths_and_hw():
    """Update path configuration."""
    config = load_config()

    # Get media and transcode paths
    media_path = request.form["media_path"].strip()
    transcode_path = request.form["transcode_path"].strip()
    ffmpeg_path = request.form["ffmpeg_path"].strip()
    ffprobe_path = request.form["ffprobe_path"].strip()

    # Get max concurrent jobs
    try:
        max_concurrent_jobs = int(request.form["max_concurrent_jobs"])
        if max_concurrent_jobs < 1:
            max_concurrent_jobs = 1
    except (ValueError, KeyError):
        max_concurrent_jobs = 1

    # Get path mappings
    path_mappings = {}

    # Process all source_path_X and target_path_X pairs
    # We'll look for all source_path_0, source_path_1, etc.
    i = 0
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
    config.ffprobe_path = ffprobe_path
    config.max_concurrent_jobs = new_max_concurrent_jobs
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
        pending_jobs = get_pending_jobs()

        if new_max_concurrent_jobs > old_max_concurrent_jobs:
            # If limit was increased, process the queue to start pending jobs
            current_app.logger.info(
                f"Concurrent job limit increased from {old_max_concurrent_jobs} to {new_max_concurrent_jobs}. Processing job queue with {len(pending_jobs)} pending jobs."
            )

            # Process the job queue immediately
            process_job_queue()

            if pending_jobs:
                flash(
                    f"Increased concurrent job limit to {new_max_concurrent_jobs}. Starting pending jobs ({len(pending_jobs)})."
                )
            else:
                flash(
                    f"Increased concurrent job limit to {new_max_concurrent_jobs}. No pending jobs to start."
                )
        elif new_max_concurrent_jobs < current_job_count:
            # If limit was reduced and we have more running jobs than the new limit,
            # we don't automatically cancel jobs, but inform the user
            current_app.logger.info(
                f"Concurrent job limit decreased from {old_max_concurrent_jobs} to {new_max_concurrent_jobs}. Currently running {current_job_count} jobs."
            )
            flash(
                f"Reduced concurrent job limit to {new_max_concurrent_jobs}. Currently running {current_job_count} jobs. New jobs will only start when current ones complete."
            )
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

    # Include the raw capabilities JSON from effeffmpeg detection
    from squishy.effeffmpeg import detect_capabilities

    detected_capabilities = detect_capabilities(quiet=True)
    hw_accel_info["capabilities_json"] = detected_capabilities

    # If we already have capabilities saved in config, include them as well
    if config.hw_capabilities:
        hw_accel_info["stored_capabilities"] = config.hw_capabilities

    return jsonify(hw_accel_info)


@admin_bp.route("/save_hw_capabilities", methods=["POST"])
def save_hw_capabilities():
    """Save custom hardware capabilities JSON to the config."""
    try:
        # Get the capabilities JSON from the request
        capabilities_json = request.json.get("capabilities")
        if not capabilities_json:
            return jsonify(
                {"success": False, "error": "No capabilities data provided"}
            ), 400

        # Validate the capabilities JSON structure
        try:
            if not isinstance(capabilities_json, dict):
                return jsonify(
                    {
                        "success": False,
                        "error": "Capabilities data must be a dictionary",
                    }
                ), 400

            required_keys = ["hwaccel", "device", "encoders", "fallback_encoders"]
            for key in required_keys:
                if key not in capabilities_json:
                    return jsonify(
                        {"success": False, "error": f"Missing required key: {key}"}
                    ), 400

            # Validate encoders and fallback_encoders are dictionaries
            if not isinstance(capabilities_json["encoders"], dict):
                return jsonify(
                    {"success": False, "error": "encoders must be a dictionary"}
                ), 400

            if not isinstance(capabilities_json["fallback_encoders"], dict):
                return jsonify(
                    {
                        "success": False,
                        "error": "fallback_encoders must be a dictionary",
                    }
                ), 400

        except Exception as e:
            return jsonify(
                {"success": False, "error": f"Validation error: {str(e)}"}
            ), 400

        # Update config with the hardware capabilities
        config = load_config()
        config.hw_capabilities = capabilities_json

        # Extract hardware acceleration method and device from capabilities
        hw_accel = capabilities_json.get("hwaccel")
        hw_device = capabilities_json.get("device")

        # Update the hw_accel and hw_device fields for backward compatibility
        if hw_accel:
            config.hw_accel = hw_accel
        if hw_device:
            config.hw_device = hw_device

        # Save the config
        save_config(config)

        # Return both success flag and the stored capabilities for UI update
        return jsonify(
            {
                "success": True,
                "message": "Hardware capabilities saved successfully",
                "capabilities": capabilities_json,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
