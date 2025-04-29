"""Module for handling completed transcodes."""

import os
import json
import glob
import logging
import shutil
from typing import List, Dict, Any, Tuple, Optional
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
            metadata["sidecar_path"] = sidecar_path
            
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

def delete_transcode(filename: str, transcode_path: str) -> Tuple[bool, str]:
    """
    Delete a completed transcode and its metadata file.
    
    Args:
        filename: The filename of the transcode to delete
        transcode_path: The base path where transcodes are stored
    
    Returns:
        Tuple of (success, message)
    """
    # Full paths to the files
    file_path = os.path.join(transcode_path, filename)
    sidecar_path = file_path + ".json"
    
    # Security check - make sure the files are in the transcode directory
    real_transcode_path = os.path.realpath(transcode_path)
    real_file_path = os.path.realpath(file_path)
    real_sidecar_path = os.path.realpath(sidecar_path)
    
    if not real_file_path.startswith(real_transcode_path) or not real_sidecar_path.startswith(real_transcode_path):
        return False, "Security error: File path is outside the transcode directory"
    
    # Check if files exist
    files_deleted = []
    errors = []
    
    # Try to delete the transcode file
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            files_deleted.append("transcode file")
        except Exception as e:
            errors.append(f"Error deleting transcode file: {str(e)}")
    
    # Try to delete the sidecar file
    if os.path.exists(sidecar_path):
        try:
            os.remove(sidecar_path)
            files_deleted.append("metadata file")
        except Exception as e:
            errors.append(f"Error deleting metadata file: {str(e)}")
    
    # If neither file existed or we couldn't delete them
    if not files_deleted:
        return False, "Files not found or could not be deleted"
    
    # If we had some errors but deleted at least one file
    if errors:
        return True, f"Partial deletion: {', '.join(files_deleted)} deleted. Errors: {', '.join(errors)}"
    
    # All good
    return True, f"Successfully deleted {', '.join(files_deleted)}"
