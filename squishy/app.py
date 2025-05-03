"""Main Squishy application."""

import os
import logging
from flask import Flask
from flask_socketio import SocketIO

from squishy.config import load_config, Config
from squishy.blueprints.api import api_bp
from squishy.blueprints.ui import ui_bp
from squishy.blueprints.admin import admin_bp
from squishy import scanner

# Initialize SocketIO globally
socketio = SocketIO()

def perform_initial_scan(config: Config):
    """Perform initial scan of media if Jellyfin or Plex is configured."""
    if config.jellyfin_url and config.jellyfin_api_key:
        logging.debug("Jellyfin configuration found. Starting initial scan in background...")
        scanner.scan_jellyfin_async(config.jellyfin_url, config.jellyfin_api_key)
    elif config.plex_url and config.plex_token:
        logging.debug("Plex configuration found. Starting initial scan in background...")
        scanner.scan_plex_async(config.plex_url, config.plex_token)
    else:
        logging.warning("No media server configuration found. Please configure Jellyfin or Plex to use Squishy.")

def create_app(test_config=None):
    """Create and configure the Flask application."""
    app = Flask(__name__)

    # Load configuration from config file
    config = load_config()

    # Load default configuration
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev"),
        MEDIA_PATH=config.media_path,
        TRANSCODE_PATH=config.transcode_path,
    )
    
    # Disable template caching in development mode
    app.config['TEMPLATES_AUTO_RELOAD'] = True

    # Load test configuration if provided
    if test_config is not None:
        app.config.from_mapping(test_config)

    # Ensure the transcode folder exists
    try:
        os.makedirs(app.config["TRANSCODE_PATH"], exist_ok=True)
    except OSError:
        pass

    # Register blueprints
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(ui_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    
    # Initialize SocketIO with the app
    socketio.init_app(app, cors_allowed_origins="*", async_mode="eventlet")
    
    # Import socket events after socketio initialization to avoid circular imports
    from squishy import socket_events  # noqa

    # Perform initial scan if media server is configured
    if not test_config:  # Skip scan during testing
        perform_initial_scan(config)

    return app

def main():
    """Run the application."""
    # Logging is configured in run.py, but update here in case app.py is run directly
    config = load_config()
    log_level = os.environ.get('LOG_LEVEL', config.log_level).upper()
    logging.getLogger().setLevel(getattr(logging, log_level))
    
    # Create Flask app
    app = create_app()

    # Run with SocketIO instead of Flask's built-in server
    socketio.run(app, host="0.0.0.0", port=5101, debug=os.environ.get("DEBUG", "False").lower() == "true")

if __name__ == "__main__":
    main()
