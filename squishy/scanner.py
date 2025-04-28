"""Media library scanner."""

import os
import re
import uuid
import threading
import time
from typing import Dict, List, Optional, Tuple

import requests

from squishy.models import MediaItem, Episode, TVShow
from squishy.config import load_config

# In-memory media store - in a real application, this would be in a database
MEDIA: Dict[str, MediaItem] = {}
TV_SHOWS: Dict[str, TVShow] = {}

# Scanning status tracker
SCAN_STATUS = {
    "in_progress": False,
    "source": None,
    "started_at": None,
    "completed_at": None,
    "item_count": 0
}

def extract_season_episode(filename: str) -> Tuple[Optional[int], Optional[int]]:
    """Extract season and episode numbers from filename."""
    # Common patterns: S01E01, 1x01, etc.
    patterns = [
        r'S(\d+)E(\d+)',          # S01E01
        r'(\d+)x(\d+)',           # 1x01
        r'Season\s*(\d+).*?Episode\s*(\d+)',  # Season 1 Episode 1
        r'E(\d+)',                # E01 (assumes season 1)
    ]
    
    for pattern in patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            season = int(match.group(1)) if len(match.groups()) > 1 else 1
            episode = int(match.group(2 if len(match.groups()) > 1 else 1))
            return season, episode
    
    return None, None

def apply_path_mapping(path: str) -> str:
    """Apply path mapping to convert media server paths to local paths."""
    config = load_config()
    
    if not config.path_mappings:
        return path
    
    # Get the single path mapping
    if config.path_mappings:
        source_path = next(iter(config.path_mappings.keys()), None)
        target_path = next(iter(config.path_mappings.values()), None)
        
        if source_path and target_path and path.startswith(source_path):
            return path.replace(source_path, target_path, 1)
    
    return path

def scan_filesystem(media_paths: List[str]) -> List[MediaItem]:
    """Scan the filesystem for media files."""
    media_items = []
    shows_by_name: Dict[str, TVShow] = {}
    
    # Clear existing TV shows
    TV_SHOWS.clear()
    
    for base_path in media_paths:
        for root, _, files in os.walk(base_path):
            for file in files:
                if file.endswith(('.mkv', '.mp4', '.avi', '.mov')):
                    # Extract title and year from filename using regex
                    match = re.match(r'(.*?)(?:\s*\((\d{4})\))?\..*', file)
                    if match:
                        title, year_str = match.groups()
                        title = title.replace(".", " ").strip()
                        year = int(year_str) if year_str else None
                        
                        media_id = str(uuid.uuid4())
                        full_path = os.path.join(root, file)
                        
                        # Ensure the file actually exists before adding
                        if os.path.exists(full_path):
                            # Determine if it's a movie or TV show based on path
                            if "tv" in root.lower():
                                # Try to extract season and episode info
                                season_num, episode_num = extract_season_episode(file)
                                
                                # Extract show name (usually the parent directory)
                                show_name = os.path.basename(os.path.dirname(root))
                                if show_name.lower() in ('season', 'seasons', 'episodes'):
                                    show_name = os.path.basename(os.path.dirname(os.path.dirname(root)))
                                    
                                # Create or get TV show
                                if show_name not in shows_by_name:
                                    show_id = str(uuid.uuid4())
                                    shows_by_name[show_name] = TVShow(
                                        id=show_id,
                                        title=show_name,
                                        year=year
                                    )
                                    TV_SHOWS[show_id] = shows_by_name[show_name]
                                
                                show = shows_by_name[show_name]
                                
                                # Create episode with best-effort title extraction
                                if season_num is not None:
                                    episode_title = title
                                    # Try to extract episode title 
                                    if episode_num is not None:
                                        pattern = rf'S{season_num:02d}E{episode_num:02d}\s*-?\s*(.*)'
                                        title_match = re.search(pattern, title, re.IGNORECASE)
                                        if title_match:
                                            episode_title = title_match.group(1).strip()
                                    
                                    # Create and add the episode
                                    episode = Episode(
                                        id=media_id,
                                        season_number=season_num,
                                        episode_number=episode_num,
                                        title=episode_title,
                                        year=year,
                                        path=full_path
                                    )
                                    show.add_episode(episode)
                                    
                                    # Also create a MediaItem for the episode
                                    media_item = MediaItem(
                                        id=media_id,
                                        title=episode_title,
                                        year=year,
                                        type="episode",
                                        path=full_path,
                                        show_id=show.id,
                                        season_number=season_num,
                                        episode_number=episode_num
                                    )
                                    media_items.append(media_item)
                                    MEDIA[media_id] = media_item
                            else:
                                # It's a movie
                                media_item = MediaItem(
                                    id=media_id,
                                    title=title,
                                    year=year,
                                    type="movie",
                                    path=full_path,
                                )
                                media_items.append(media_item)
                                MEDIA[media_id] = media_item
    
    return media_items

def scan_jellyfin(url: str, api_key: str) -> List[MediaItem]:
    """Scan a Jellyfin server for media."""
    media_items = []
    shows_by_id: Dict[str, TVShow] = {}
    
    # Clear existing TV shows
    TV_SHOWS.clear()
    
    headers = {
        "X-MediaBrowser-Token": api_key,
        "Content-Type": "application/json",
    }
    
    # Fetch movies
    response = requests.get(f"{url}/Items", params={
        "IncludeItemTypes": "Movie",
        "Recursive": "true",
        "Fields": "Path,Year",
    }, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        for item in data.get("Items", []):
            if "Path" in item:
                media_id = str(uuid.uuid4())
                
                # Apply path mapping to convert media server path to local path
                mapped_path = apply_path_mapping(item["Path"])
                
                # Only add if the path exists
                if mapped_path and os.path.exists(mapped_path):
                    media_item = MediaItem(
                        id=media_id,
                        title=item.get("Name", ""),
                        year=item.get("ProductionYear"),
                        type="movie",
                        path=mapped_path,
                        poster_url=f"{url.rstrip('/')}/Items/{item['Id']}/Images/Primary?API_KEY={api_key}",
                    )
                    media_items.append(media_item)
                    MEDIA[media_id] = media_item
    
    # First fetch TV series to get their metadata
    response = requests.get(f"{url}/Items", params={
        "IncludeItemTypes": "Series",
        "Recursive": "true",
        "Fields": "Path,Year",
    }, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        for item in data.get("Items", []):
            series_id = item["Id"]
            show_id = str(uuid.uuid4())
            shows_by_id[series_id] = TVShow(
                id=show_id,
                title=item.get("Name", ""),
                year=item.get("ProductionYear"),
                poster_url=f"{url.rstrip('/')}/Items/{series_id}/Images/Primary?API_KEY={api_key}",
            )
            TV_SHOWS[show_id] = shows_by_id[series_id]
    
    # Now fetch episodes
    response = requests.get(f"{url}/Items", params={
        "IncludeItemTypes": "Episode",
        "Recursive": "true",
        "Fields": "Path,SeriesName,SeasonName,ParentIndexNumber,IndexNumber,Year",
    }, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        for item in data.get("Items", []):
            if "Path" in item and "SeriesId" in item:
                media_id = str(uuid.uuid4())
                series_id = item["SeriesId"]
                
                # Apply path mapping to convert media server path to local path
                mapped_path = apply_path_mapping(item["Path"])
                
                # Only add if the path exists
                if mapped_path and os.path.exists(mapped_path) and series_id in shows_by_id:
                    show = shows_by_id[series_id]
                    season_num = item.get("ParentIndexNumber", 0)
                    episode_num = item.get("IndexNumber")
                    
                    # Create the episode
                    episode = Episode(
                        id=media_id,
                        season_number=season_num,
                        episode_number=episode_num,
                        title=item.get("Name", ""),
                        year=item.get("ProductionYear"),
                        path=mapped_path
                    )
                    show.add_episode(episode)
                    
                    # Also create a MediaItem for the episode
                    media_item = MediaItem(
                        id=media_id,
                        title=item.get("Name", ""),
                        year=item.get("ProductionYear"),
                        type="episode",
                        path=mapped_path,
                        poster_url=f"{url.rstrip('/')}/Items/{item['Id']}/Images/Primary?API_KEY={api_key}",
                        show_id=show.id,
                        season_number=season_num,
                        episode_number=episode_num
                    )
                    media_items.append(media_item)
                    MEDIA[media_id] = media_item
    
    return media_items

def scan_plex(url: str, token: str) -> List[MediaItem]:
    """Scan a Plex server for media."""
    media_items = []
    shows_by_key: Dict[str, TVShow] = {}
    
    # Clear existing TV shows
    TV_SHOWS.clear()
    
    headers = {
        "X-Plex-Token": token,
        "Accept": "application/json",
    }
    
    # Fetch libraries
    response = requests.get(f"{url}/library/sections", headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        for section in data["MediaContainer"]["Directory"]:
            section_id = section["key"]
            section_type = section["type"]
            
            if section_type == "movie":
                # Process movies
                items_response = requests.get(
                    f"{url}/library/sections/{section_id}/all",
                    headers=headers
                )
                
                if items_response.status_code == 200:
                    items_data = items_response.json()
                    for item in items_data["MediaContainer"]["Metadata"]:
                        if "Media" in item and len(item["Media"]) > 0:
                            for media in item["Media"]:
                                if "Part" in media and len(media["Part"]) > 0:
                                    file_path = media["Part"][0]["file"]
                                    
                                    # Apply path mapping to convert media server path to local path
                                    mapped_path = apply_path_mapping(file_path)
                                    
                                    # Only add if the path exists
                                    if mapped_path and os.path.exists(mapped_path):
                                        media_id = str(uuid.uuid4())
                                        media_item = MediaItem(
                                            id=media_id,
                                            title=item.get("title", ""),
                                            year=item.get("year"),
                                            type="movie",
                                            path=mapped_path,
                                            poster_url=f"{url}{item.get('thumb')}?X-Plex-Token={token}" if "thumb" in item else None,
                                        )
                                        media_items.append(media_item)
                                        MEDIA[media_id] = media_item
            
            elif section_type == "show":
                # First get all shows in the section
                shows_response = requests.get(
                    f"{url}/library/sections/{section_id}/all",
                    headers=headers
                )
                
                if shows_response.status_code == 200:
                    shows_data = shows_response.json()
                    for show in shows_data["MediaContainer"]["Metadata"]:
                        show_id = str(uuid.uuid4())
                        show_key = show["ratingKey"]
                        shows_by_key[show_key] = TVShow(
                            id=show_id,
                            title=show.get("title", ""),
                            year=show.get("year"),
                            poster_url=f"{url}{show.get('thumb')}?X-Plex-Token={token}" if "thumb" in show else None,
                        )
                        TV_SHOWS[show_id] = shows_by_key[show_key]
                        
                        # Get episodes for this show
                        episodes_response = requests.get(
                            f"{url}/library/metadata/{show_key}/allLeaves",
                            headers=headers
                        )
                        
                        if episodes_response.status_code == 200:
                            episodes_data = episodes_response.json()
                            for episode in episodes_data["MediaContainer"]["Metadata"]:
                                if "Media" in episode and len(episode["Media"]) > 0:
                                    for media in episode["Media"]:
                                        if "Part" in media and len(media["Part"]) > 0:
                                            media_id = str(uuid.uuid4())
                                            file_path = media["Part"][0]["file"]
                                            
                                            season_num = episode.get("parentIndex", 0)
                                            episode_num = episode.get("index")
                                            
                                            # Apply path mapping to convert media server path to local path
                                            mapped_path = apply_path_mapping(file_path)
                                            
                                            # Only add if the path exists
                                            if mapped_path and os.path.exists(mapped_path):
                                                # Create the Episode object
                                                ep = Episode(
                                                    id=media_id,
                                                    season_number=season_num,
                                                    episode_number=episode_num,
                                                    title=episode.get("title", ""),
                                                    year=episode.get("year"),
                                                    path=mapped_path
                                                )
                                                shows_by_key[show_key].add_episode(ep)
                                                
                                                # Create the MediaItem
                                                media_item = MediaItem(
                                                    id=media_id,
                                                    title=episode.get("title", ""),
                                                    year=episode.get("year"),
                                                    type="episode",
                                                    path=mapped_path,
                                                    poster_url=f"{url}{episode.get('thumb')}?X-Plex-Token={token}" if "thumb" in episode else None,
                                                    show_id=show_id,
                                                    season_number=season_num,
                                                    episode_number=episode_num
                                                )
                                                media_items.append(media_item)
                                                MEDIA[media_id] = media_item
    
    return media_items

def get_media(media_id: str) -> Optional[MediaItem]:
    """Get a media item by ID."""
    return MEDIA.get(media_id)

def get_all_media() -> List[MediaItem]:
    """Get all media items."""
    return list(MEDIA.values())

def get_all_shows() -> List[TVShow]:
    """Get all TV shows."""
    return list(TV_SHOWS.values())

def get_show(show_id: str) -> Optional[TVShow]:
    """Get a TV show by ID."""
    return TV_SHOWS.get(show_id)

def get_shows_and_movies() -> Tuple[List[TVShow], List[MediaItem]]:
    """
    Get all TV shows and movies.
    
    Filters out:
    - TV shows with no episodes
    - Movies with no video file (missing path)
    """
    # Filter TV shows to only include those with episodes
    shows_with_episodes = [show for show in TV_SHOWS.values() if show.seasons and any(season.episodes for season in show.seasons.values())]
    
    # Filter movies to only include those with a valid path (skipping os.path.exists check which is slow)
    valid_movies = [
        item for item in MEDIA.values() 
        if item.type == "movie" and item.path
    ]
    
    return shows_with_episodes, valid_movies

def get_scan_status():
    """Get the current scanning status."""
    return SCAN_STATUS

def _run_scan_filesystem(media_paths: List[str]):
    """Run filesystem scan in a separate thread."""
    global SCAN_STATUS
    
    SCAN_STATUS["in_progress"] = True
    SCAN_STATUS["source"] = "filesystem"
    SCAN_STATUS["started_at"] = time.time()
    SCAN_STATUS["item_count"] = 0
    
    try:
        media_items = scan_filesystem(media_paths)
        SCAN_STATUS["item_count"] = len(media_items)
    except Exception as e:
        import logging
        logging.error(f"Error during filesystem scan: {str(e)}")
    finally:
        SCAN_STATUS["in_progress"] = False
        SCAN_STATUS["completed_at"] = time.time()

def _run_scan_jellyfin(url: str, api_key: str):
    """Run Jellyfin scan in a separate thread."""
    global SCAN_STATUS
    
    SCAN_STATUS["in_progress"] = True
    SCAN_STATUS["source"] = "jellyfin"
    SCAN_STATUS["started_at"] = time.time()
    SCAN_STATUS["item_count"] = 0
    
    try:
        media_items = scan_jellyfin(url, api_key)
        SCAN_STATUS["item_count"] = len(media_items)
    except Exception as e:
        import logging
        logging.error(f"Error during Jellyfin scan: {str(e)}")
    finally:
        SCAN_STATUS["in_progress"] = False
        SCAN_STATUS["completed_at"] = time.time()

def _run_scan_plex(url: str, token: str):
    """Run Plex scan in a separate thread."""
    global SCAN_STATUS
    
    SCAN_STATUS["in_progress"] = True
    SCAN_STATUS["source"] = "plex"
    SCAN_STATUS["started_at"] = time.time()
    SCAN_STATUS["item_count"] = 0
    
    try:
        media_items = scan_plex(url, token)
        SCAN_STATUS["item_count"] = len(media_items)
    except Exception as e:
        import logging
        logging.error(f"Error during Plex scan: {str(e)}")
    finally:
        SCAN_STATUS["in_progress"] = False
        SCAN_STATUS["completed_at"] = time.time()

def scan_filesystem_async(media_paths: List[str]):
    """Start filesystem scan in a non-blocking thread."""
    thread = threading.Thread(target=_run_scan_filesystem, args=(media_paths,))
    thread.daemon = True
    thread.start()
    return thread

def scan_jellyfin_async(url: str, api_key: str):
    """Start Jellyfin scan in a non-blocking thread."""
    thread = threading.Thread(target=_run_scan_jellyfin, args=(url, api_key))
    thread.daemon = True
    thread.start()
    return thread

def scan_plex_async(url: str, token: str):
    """Start Plex scan in a non-blocking thread."""
    thread = threading.Thread(target=_run_scan_plex, args=(url, token))
    thread.daemon = True
    thread.start()
    return thread