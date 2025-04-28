"""Main Squishy application."""

import os
from flask import Flask

from squishy.config import load_config
from squishy.blueprints.api import api_bp
from squishy.blueprints.ui import ui_bp
from squishy.blueprints.admin import admin_bp
from squishy.webdav import start_webdav_server

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

    return app

def main():
    """Run the application."""
    app = create_app()

    # Start WebDAV server in a separate thread
    # Note: WebDAV is kept for backward compatibility and external tools
    # but direct file download is now preferred for browser downloads
    webdav_port = int(os.environ.get("WEBDAV_PORT", 8983))
    start_webdav_server(app.config["TRANSCODE_PATH"], webdav_port)

    # Run Flask app
    app.run(host="0.0.0.0", port=5101)

if __name__ == "__main__":
    main()
