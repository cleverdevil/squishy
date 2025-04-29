#!/usr/bin/env python3
"""Entry point for the Squishy application."""

import os
import logging
import eventlet

# Patch stdlib for eventlet/WebSocket support
eventlet.monkey_patch()

from squishy.app import main

if __name__ == "__main__":
    # Load config to get log level
    from squishy.config import load_config
    config = load_config()
    
    # Configure logging with level from config, overridden by environment variable if set
    log_level = os.environ.get('LOG_LEVEL', config.log_level).upper()
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Start the app
    main()
