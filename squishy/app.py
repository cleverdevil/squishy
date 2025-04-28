"""Main Squishy application."""

import os
import logging
from flask import Flask

from squishy.config import load_config, Config
from squishy.blueprints.api import api_bp
from squishy.blueprints.ui import ui_bp
from squishy.blueprints.admin import admin_bp
from squishy import scanner

def perform_initial_scan(config: Config):
    """Perform initial scan of media if Jellyfin or Plex is configured."""
    if config.jellyfin_url and config.jellyfin_api_key:
        logging.info("Jellyfin configuration found. Starting initial scan in background...")
        scanner.scan_jellyfin_async(config.jellyfin_url, config.jellyfin_api_key)
    elif config.plex_url and config.plex_token:
        logging.info("Plex configuration found. Starting initial scan in background...")
        scanner.scan_plex_async(config.plex_url, config.plex_token)
    else:
        logging.info("No media server configuration found. Skipping initial scan.")

def create_app(test_config=None):
    """Create and configure the Flask application."""
    app = Flask(__name__, instance_relative_config=True)

    # Load configuration from config file
    config = load_config()

    # Load default configuration
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev"),
        DATABASE=os.path.join(app.instance_path, "squishy.sqlite"),
        MEDIA_PATH=config.media_path,
        TRANSCODE_PATH=config.transcode_path,
    )

    # Load the instance config, if it exists
    if test_config is None:
        app.config.from_pyfile("config.py", silent=True)
    else:
        app.config.from_mapping(test_config)

    # Ensure the instance folder exists
    try:
        os.makedirs(app.instance_path, exist_ok=True)
        os.makedirs(app.config["TRANSCODE_PATH"], exist_ok=True)
    except OSError:
        pass

    # Register blueprints
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(ui_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    # Perform initial scan if media server is configured
    if not test_config:  # Skip scan during testing
        perform_initial_scan(config)

    return app

def main():
    """Run the application."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    app = create_app()

    # Run Flask app
    app.run(host="0.0.0.0", port=5101)

if __name__ == "__main__":
    main()
