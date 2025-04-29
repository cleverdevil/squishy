#!/usr/bin/env python3
"""Entry point for the Squishy application."""

import os
import logging
import eventlet

# Patch stdlib for eventlet/WebSocket support
eventlet.monkey_patch()

from squishy.app import main

if __name__ == "__main__":
    # Configure logging
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Start the app
    main()
