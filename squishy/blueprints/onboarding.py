"""Onboarding blueprint for Squishy."""

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    jsonify,
    current_app,
    flash,
    session,
)

from squishy.config import load_config, save_config, is_first_run
from squishy.scanner import scan_jellyfin_async, scan_plex_async, get_jellyfin_libraries, get_plex_libraries
from squishy.transcoder import detect_hw_accel

onboarding_bp = Blueprint("onboarding", __name__)


@onboarding_bp.route("/")
def index():
    """Onboarding welcome page."""
    # Check if this is the first run
    first_run = is_first_run()
    
    # If this isn't a first run and we're not in an ongoing onboarding process, redirect to home
    if not first_run and 'onboarding_in_progress' not in session:
        return redirect(url_for("ui.index"))
    
    # Mark that we're in the onboarding process
    session['onboarding_in_progress'] = True
    
    return render_template("onboarding/index.html")


@onboarding_bp.route("/step/<int:step>")
def step(step):
    """Render a specific step of the onboarding process."""
    # If this isn't a first run and we're not in an ongoing onboarding process, redirect to home
    if not is_first_run() and 'onboarding_in_progress' not in session:
        return redirect(url_for("ui.index"))
    
    # Mark that we're in the onboarding process
    session['onboarding_in_progress'] = True
    
    config = load_config()
    
    # Each step has its own template and context
    if step == 1:  # Media Source
        return render_template("onboarding/step1.html", config=config)
    elif step == 2:  # Media Libraries
        return render_template("onboarding/step2.html", config=config)
    elif step == 3:  # Path Configuration
        return render_template("onboarding/step3.html", config=config)
    elif step == 4:  # Library Scan
        return render_template("onboarding/step4.html", config=config)
    elif step == 5:  # Transcoding Presets
        return render_template("onboarding/step5.html", config=config)
    elif step == 6:  # Hardware Acceleration
        return render_template("onboarding/step6.html", config=config)
    elif step == 7:  # Completion
        # Clear the onboarding session when we reach the completion step
        session.pop('onboarding_in_progress', None)
        # Ensure the session change is saved
        session.modified = True
        return render_template("onboarding/complete.html")
    
    # If invalid step, redirect to beginning
    return redirect(url_for("onboarding.index"))


@onboarding_bp.route("/save_media_source", methods=["POST"])
def save_media_source():
    """Save the media source configuration."""
    source = request.form.get("source")
    config = load_config()
    
    if source == "jellyfin":
        jellyfin_url = request.form.get("jellyfin_url")
        jellyfin_api_key = request.form.get("jellyfin_api_key")
        
        # Clear any Plex configuration
        config.plex_url = None
        config.plex_token = None
        
        # Set Jellyfin configuration
        config.jellyfin_url = jellyfin_url
        config.jellyfin_api_key = jellyfin_api_key
    
    elif source == "plex":
        plex_url = request.form.get("plex_url")
        plex_token = request.form.get("plex_token")
        
        # Clear any Jellyfin configuration
        config.jellyfin_url = None
        config.jellyfin_api_key = None
        
        # Set Plex configuration
        config.plex_url = plex_url
        config.plex_token = plex_token
    
    save_config(config)
    return redirect(url_for("onboarding.step", step=2))


@onboarding_bp.route("/get_libraries", methods=["GET"])
def get_libraries():
    """Get libraries from the configured media source."""
    config = load_config()
    libraries = []
    
    if config.jellyfin_url and config.jellyfin_api_key:
        try:
            libraries = get_jellyfin_libraries(config.jellyfin_url, config.jellyfin_api_key)
        except Exception as e:
            current_app.logger.error(f"Error getting Jellyfin libraries: {e}")
            return jsonify({"success": False, "message": str(e), "libraries": []})
    
    elif config.plex_url and config.plex_token:
        try:
            libraries = get_plex_libraries(config.plex_url, config.plex_token)
        except Exception as e:
            current_app.logger.error(f"Error getting Plex libraries: {e}")
            return jsonify({"success": False, "message": str(e), "libraries": []})
    
    return jsonify({
        "success": True,
        "libraries": libraries,
        "enabled_libraries": config.enabled_libraries
    })


@onboarding_bp.route("/save_libraries", methods=["POST"])
def save_libraries():
    """Save enabled libraries configuration."""
    config = load_config()
    
    # Get all enabled libraries from form
    enabled_libraries = {}
    for key, value in request.form.items():
        if key.startswith("library_"):
            library_id = key.replace("library_", "")
            enabled_libraries[library_id] = value == "on"
    
    config.enabled_libraries = enabled_libraries
    save_config(config)
    
    return redirect(url_for("onboarding.step", step=3))


@onboarding_bp.route("/save_paths", methods=["POST"])
def save_paths():
    """Save path configuration."""
    config = load_config()
    
    # Get basic paths
    config.media_path = request.form.get("media_path")
    config.transcode_path = request.form.get("transcode_path")
    config.ffmpeg_path = request.form.get("ffmpeg_path")
    config.ffprobe_path = request.form.get("ffprobe_path")
    
    # Get max concurrent jobs
    try:
        config.max_concurrent_jobs = int(request.form.get("max_concurrent_jobs", 1))
    except ValueError:
        config.max_concurrent_jobs = 1
    
    # Process path mappings
    path_mappings = {}
    for key, value in request.form.items():
        if key.startswith("source_path_") and value:
            idx = key.replace("source_path_", "")
            target_key = f"target_path_{idx}"
            if target_key in request.form and request.form[target_key]:
                path_mappings[value] = request.form[target_key]
    
    config.path_mappings = path_mappings
    save_config(config)
    
    return redirect(url_for("onboarding.step", step=4))


@onboarding_bp.route("/scan_library", methods=["POST"])
def scan_library():
    """Start a library scan."""
    config = load_config()
    
    if config.jellyfin_url and config.jellyfin_api_key:
        scan_jellyfin_async(config.jellyfin_url, config.jellyfin_api_key)
    elif config.plex_url and config.plex_token:
        scan_plex_async(config.plex_url, config.plex_token)
    
    return jsonify({"success": True})


@onboarding_bp.route("/skip_scan", methods=["POST"])
def skip_scan():
    """Skip the library scan step."""
    return redirect(url_for("onboarding.step", step=5))


@onboarding_bp.route("/save_presets", methods=["POST"])
def save_presets():
    """Save transcoding preset configuration."""
    preset_type = request.form.get("preset_type")
    config = load_config()
    
    # In the onboarding process, we'll use one of the bundled presets or defaults
    from squishy.effeffmpeg import validate_presets_data
    
    if preset_type == "quality":
        # Use quality-focused presets (HEVC/CRF)
        try:
            import os
            import json
            presets_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 
                                       "presets", "presets-quality.json")
            with open(presets_path, "r") as f:
                presets_data = json.load(f)
                if "presets" in presets_data:
                    config.presets = presets_data["presets"]
        except Exception as e:
            current_app.logger.error(f"Error loading quality presets: {e}")
            flash("Error loading quality presets, using defaults", "error")
    
    elif preset_type == "compatible":
        # Use compatibility-focused presets (H264/Bitrate)
        try:
            import os
            import json
            presets_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 
                                       "presets", "presets-compatible.json")
            with open(presets_path, "r") as f:
                presets_data = json.load(f)
                if "presets" in presets_data:
                    config.presets = presets_data["presets"]
        except Exception as e:
            current_app.logger.error(f"Error loading compatible presets: {e}")
            flash("Error loading compatible presets, using defaults", "error")
    
    # Otherwise keep default presets
    save_config(config)
    
    return redirect(url_for("onboarding.step", step=6))


@onboarding_bp.route("/detect_hw_accel", methods=["GET"])
def detect_hw_accel_route():
    """Detect hardware acceleration capabilities."""
    # Load config to get ffmpeg_path
    config = load_config()
    ffmpeg_path = config.ffmpeg_path or "ffmpeg"  # Use default if not set
    
    # Call detect_hw_accel with the ffmpeg_path parameter
    capabilities = detect_hw_accel(ffmpeg_path)
    
    # Save the capabilities to the config
    config.hw_capabilities = capabilities
    save_config(config)
    
    return jsonify(capabilities)


@onboarding_bp.route("/save_hw_capabilities", methods=["POST"])
def save_hw_capabilities():
    """Save hardware capabilities configuration."""
    try:
        capabilities_json = request.json
        
        if not capabilities_json:
            return jsonify({"success": False, "message": "No capabilities data provided"})
        
        # Validate the JSON format
        if not isinstance(capabilities_json, dict):
            return jsonify({"success": False, "message": "Invalid capabilities format"})
        
        # Update config with the hardware capabilities
        config = load_config()
        config.hw_capabilities = capabilities_json
        save_config(config)
        
        return jsonify({
            "success": True, 
            "message": "Hardware capabilities saved successfully",
            "capabilities": capabilities_json
        })
    except Exception as e:
        current_app.logger.error(f"Error saving hardware capabilities: {e}")
        return jsonify({"success": False, "message": str(e)})


@onboarding_bp.route("/complete", methods=["POST"])
def complete():
    """Complete the onboarding process."""
    # Mark onboarding as completed by removing the flag from the session
    if 'onboarding_in_progress' in session:
        session.pop('onboarding_in_progress')
        # Ensure the session change is saved
        session.modified = True
        
    # At this point, all configuration should be saved
    # Redirect to the home page with splash screen flag
    return redirect(url_for("ui.index", show_splash=True))