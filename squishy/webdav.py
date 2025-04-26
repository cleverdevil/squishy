"""WebDAV server for Squishy."""

import threading
from wsgidav.wsgidav_app import WsgiDAVApp
from wsgidav.fs_dav_provider import FilesystemProvider
from wsgidav.http_authenticator import HTTPAuthenticator

def start_webdav_server(root_path, port=8080):
    """Start a WebDAV server in a separate thread."""
    
    config = {
        "provider_mapping": {"/": FilesystemProvider(root_path)},
        "http_authenticator": {
            "domain_controller": None,  # No authentication for now
            "accept_basic": False,
            "accept_digest": False,
            "default_to_digest": False,
        },
        "simple_dc": {"user_mapping": {"*": True}},  # Allow anonymous access
        "verbose": 1,
        "port": port,
        "host": "0.0.0.0",
    }
    
    app = WsgiDAVApp(config)
    
    def run_server():
        """Run the WebDAV server."""
        from wsgiref.simple_server import make_server
        server = make_server(config["host"], config["port"], app)
        server.serve_forever()
    
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    
    return thread