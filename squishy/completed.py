"""Module for handling completed transcodes."""

import os
import json
import glob
import logging
from typing import List, Dict, Any
from datetime import datetime

def get_completed_transcodes(transcode_path: str) -> List[Dict[str, Any]]:
    """Get all completed transcodes with metadata."""
    # Find all JSON sidecar files
    sidecar_files = glob.glob(os.path.join(transcode_path, "*.json"))
    
    completed = []
    for sidecar_path in sidecar_files:
        try:
            # Check if the media file exists
            media_path = sidecar_path[:-5]  # Remove .json extension
            if not os.path.exists(media_path):
                continue
                
            # Read metadata from sidecar file
            with open(sidecar_path, "r") as f:
                metadata = json.load(f)
            
            # Add file path and name
            metadata["file_path"] = media_path
            metadata["file_name"] = os.path.basename(media_path)
            
            # Parse completed_at date for sorting
            if "completed_at" in metadata:
                try:
                    completed_at = datetime.fromisoformat(metadata["completed_at"])
                    metadata["completed_at_datetime"] = completed_at
                except (ValueError, TypeError):
                    metadata["completed_at_datetime"] = datetime.fromtimestamp(0)
            
            completed.append(metadata)
        except Exception as e:
            logging.error(f"Error reading sidecar file {sidecar_path}: {e}")
    
    # Sort by completion date, newest first
    completed.sort(key=lambda x: x.get("completed_at_datetime", datetime.fromtimestamp(0)), reverse=True)
    
    return completed
