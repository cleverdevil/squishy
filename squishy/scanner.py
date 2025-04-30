"""Media library scanner."""

import os
import re
import uuid
import logging
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

    # Try all path mappings in order (most specific first to avoid partial matches)
    # Sort by length of source path (descending) to match more specific paths first
    sorted_mappings = sorted(
        config.path_mappings.items(),
        key=lambda x: len(x[0]),
        reverse=True
    )

    # Before we apply any mappings, log the original path
    logging.debug(f"Applying path mapping to: {path}")

    # Try each mapping
    for source_path, target_path in sorted_mappings:
        if source_path and target_path and path.startswith(source_path):
            new_path = path.replace(source_path, target_path, 1)
            logging.debug(f"Path mapped: {path} -> {new_path}")
            return new_path

    # No mapping applied
    logging.debug(f"No path mapping applied, using original: {path}")
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

    # Load config to check enabled libraries
    config = load_config()

    # Track statistics
    stats = {
        "total_movies_found": 0,
        "skipped_movies": 0,
        "total_episodes_found": 0,
        "skipped_episodes": 0,
        "path_not_found": 0,
        "library_sections": 0,
        "movie_sections": 0,
        "tv_sections": 0,
        "added_movies": 0,
        "added_episodes": 0,
        "skipped_libraries": 0
    }

    headers = {
        "X-MediaBrowser-Token": api_key,
        "Content-Type": "application/json",
    }

    # First get all libraries to check which ones are enabled
    libraries_response = requests.get(f"{url}/Library/VirtualFolders", headers=headers)
    enabled_library_ids = []

    if libraries_response.status_code == 200:
        libraries = libraries_response.json()
        for library in libraries:
            library_id = library.get("ItemId")
            if library_id:
                # Check if this library is enabled (default to True if not specified)
                if library_id not in config.enabled_libraries or config.enabled_libraries.get(library_id, True):
                    enabled_library_ids.append(library_id)
                else:
                    logging.debug(f"Skipping disabled Jellyfin library: {library.get('Name', 'Unknown')} (id: {library_id})")
                    stats["skipped_libraries"] += 1

    # Fetch movies - for Jellyfin API, we need to query each library separately
    movie_items = []
    
    # If no enabled libraries, skip scanning
    if not enabled_library_ids:
        logging.warning("No enabled Jellyfin libraries found to scan")
    else:
        for library_id in enabled_library_ids:
            response = requests.get(f"{url}/Items", params={
                "IncludeItemTypes": "Movie",
                "Recursive": "true",
                "Fields": "Path,Year,Overview,Genres,Studios,OfficialRating,CommunityRating,PremiereDate,Taglines,People",
                "ParentId": library_id,
            }, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                items = data.get("Items", [])
                movie_items.extend(items)
                logging.debug(f"Found {len(items)} movies in library {library_id}")
            else:
                logging.error(f"Failed to retrieve movies from library {library_id}: HTTP {response.status_code}")
    
    stats["total_movies_found"] = len(movie_items)
    
    if movie_items:

        for item in movie_items:
            if "Path" in item:
                media_id = str(uuid.uuid4())

                # Apply path mapping to convert media server path to local path
                mapped_path = apply_path_mapping(item["Path"])

                # Only add if the path exists
                if mapped_path and os.path.exists(mapped_path):
                    # Extract directors and actors
                    directors = []
                    actors = []
                    if "People" in item:
                        for person in item.get("People", []):
                            if person.get("Type") == "Director":
                                directors.append(person.get("Name"))
                            elif person.get("Type") == "Actor":
                                actors.append(person.get("Name"))
                    
                    # Get studio
                    studio = None
                    if item.get("Studios") and len(item.get("Studios")) > 0:
                        studio = item.get("Studios")[0].get("Name")
                    
                    # Handle taglines safely
                    tagline = None
                    if item.get("Taglines") and isinstance(item.get("Taglines"), list) and len(item.get("Taglines")) > 0:
                        tagline = item.get("Taglines")[0]
                    
                    # Handle genres safely
                    genres = []
                    if item.get("Genres") and isinstance(item.get("Genres"), list):
                        genres = [g.get("Name") for g in item.get("Genres") if isinstance(g, dict) and g.get("Name")]
                    
                    media_item = MediaItem(
                        id=media_id,
                        title=item.get("Name", ""),
                        year=item.get("ProductionYear"),
                        type="movie",
                        path=mapped_path,
                        poster_url=f"{url.rstrip('/')}/Items/{item['Id']}/Images/Primary?API_KEY={api_key}",
                        overview=item.get("Overview"),
                        tagline=tagline,
                        genres=genres,
                        directors=directors,
                        actors=actors[:5],  # Limit to top 5 actors
                        release_date=item.get("PremiereDate"),
                        rating=item.get("CommunityRating"),
                        content_rating=item.get("OfficialRating"),
                        studio=studio
                    )
                    media_items.append(media_item)
                    MEDIA[media_id] = media_item
                    stats["added_movies"] += 1
                else:
                    stats["path_not_found"] += 1
                    stats["skipped_movies"] += 1

    # First fetch TV series to get their metadata - query each library separately
    series_items = []
    
    if enabled_library_ids:
        for library_id in enabled_library_ids:
            response = requests.get(f"{url}/Items", params={
                "IncludeItemTypes": "Series",
                "Recursive": "true",
                "Fields": "Path,Year,Overview,Genres,Studios,OfficialRating,CommunityRating,PremiereDate,Taglines,People",
                "ParentId": library_id,
            }, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                items = data.get("Items", [])
                series_items.extend(items)
                logging.debug(f"Found {len(items)} TV series in library {library_id}")
            else:
                logging.error(f"Failed to retrieve TV series from library {library_id}: HTTP {response.status_code}")
    
    for item in series_items:
            series_id = item["Id"]
            show_id = str(uuid.uuid4())
            
            # Extract directors and actors
            creators = []
            actors = []
            if "People" in item:
                for person in item.get("People", []):
                    if person.get("Type") == "Director" or person.get("Type") == "Creator":
                        creators.append(person.get("Name"))
                    elif person.get("Type") == "Actor":
                        actors.append(person.get("Name"))
            
            # Get studio
            studio = None
            if item.get("Studios") and isinstance(item.get("Studios"), list) and len(item.get("Studios")) > 0:
                studio_obj = item.get("Studios")[0]
                if isinstance(studio_obj, dict):
                    studio = studio_obj.get("Name")
            
            # Handle taglines safely
            tagline = None
            if item.get("Taglines") and isinstance(item.get("Taglines"), list) and len(item.get("Taglines")) > 0:
                tagline = item.get("Taglines")[0]
            
            # Handle genres safely
            genres = []
            if item.get("Genres") and isinstance(item.get("Genres"), list):
                genres = [g.get("Name") for g in item.get("Genres") if isinstance(g, dict) and g.get("Name")]
                
            shows_by_id[series_id] = TVShow(
                id=show_id,
                title=item.get("Name", ""),
                year=item.get("ProductionYear"),
                poster_url=f"{url.rstrip('/')}/Items/{series_id}/Images/Primary?API_KEY={api_key}",
                overview=item.get("Overview"),
                tagline=tagline,
                genres=genres,
                creators=creators,
                actors=actors[:5],  # Limit to top 5 actors
                first_air_date=item.get("PremiereDate"),
                rating=item.get("CommunityRating"),
                content_rating=item.get("OfficialRating"),
                studio=studio
            )
            TV_SHOWS[show_id] = shows_by_id[series_id]

    # Now fetch episodes - query each library separately
    episode_items = []
    
    if enabled_library_ids:
        for library_id in enabled_library_ids:
            response = requests.get(f"{url}/Items", params={
                "IncludeItemTypes": "Episode",
                "Recursive": "true",
                "Fields": "Path,SeriesName,SeasonName,ParentIndexNumber,IndexNumber,Year,Overview,PremiereDate",
                "ParentId": library_id,
            }, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                items = data.get("Items", [])
                episode_items.extend(items)
                logging.debug(f"Found {len(items)} episodes in library {library_id}")
            else:
                logging.error(f"Failed to retrieve episodes from library {library_id}: HTTP {response.status_code}")
    
    stats["total_episodes_found"] = len(episode_items)

    for item in episode_items:
        if "Path" in item and "SeriesId" in item:
            media_id = str(uuid.uuid4())
            series_id = item["SeriesId"]

            # Apply path mapping to convert media server path to local path
            mapped_path = apply_path_mapping(item["Path"])

            # Only add if the path exists
            if not mapped_path or not os.path.exists(mapped_path) or series_id not in shows_by_id:
                logging.debug(f"Episode path not found or series ID not found: {mapped_path}")
                stats["path_not_found"] += 1
                stats["skipped_episodes"] += 1
                continue

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
                path=mapped_path,
                overview=item.get("Overview"),
                air_date=item.get("PremiereDate")
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
                episode_number=episode_num,
                overview=item.get("Overview"),
                release_date=item.get("PremiereDate")
            )
            media_items.append(media_item)
            MEDIA[media_id] = media_item
            stats["added_episodes"] += 1

    # Log statistics
    logging.info(f"Jellyfin scan statistics: {stats}")
    logging.info(f"Total media items added: {len(media_items)}")

    return media_items

def scan_plex(url: str, token: str) -> List[MediaItem]:
    """Scan a Plex server for media."""
    media_items = []
    shows_by_key: Dict[str, TVShow] = {}

    # Clear existing TV shows
    TV_SHOWS.clear()

    # Load config to check enabled libraries
    config = load_config()

    # Track statistics to help with debugging
    stats = {
        "total_movies_found": 0,
        "skipped_movies": 0,
        "total_episodes_found": 0,
        "skipped_episodes": 0,
        "path_not_found": 0,
        "library_sections": 0,
        "movie_sections": 0,
        "tv_sections": 0,
        "added_movies": 0,
        "added_episodes": 0,
        "skipped_libraries": 0
    }

    # Check environment variable to bypass path existence check (for testing)
    skip_path_check = os.environ.get("SQUISHY_SKIP_PATH_CHECK", "").lower() in ("true", "1", "yes")
    if skip_path_check:
        logging.debug("Path existence check disabled via SQUISHY_SKIP_PATH_CHECK")

    headers = {
        "X-Plex-Token": token,
        "Accept": "application/json",
    }

    try:
        # Fetch libraries
        logging.debug(f"Connecting to Plex server at {url}")
        response = requests.get(f"{url}/library/sections", headers=headers)

        if response.status_code == 200:
            try:
                data = response.json()
                sections = data.get("MediaContainer", {}).get("Directory", [])
                stats["library_sections"] = len(sections)
                logging.debug(f"Found {len(sections)} library sections in Plex")

                for section in sections:
                    try:
                        section_id = section.get("key")
                        section_type = section.get("type")
                        section_title = section.get("title", "Unknown")

                        if not section_id:
                            logging.warning(f"Missing section key in section: {section_title}")
                            continue

                        # Check if this library is enabled (default to True if not specified)
                        if section_id in config.enabled_libraries and not config.enabled_libraries.get(section_id, True):
                            logging.debug(f"Skipping disabled Plex library: {section_title} (id: {section_id})")
                            stats["skipped_libraries"] += 1
                            continue

                        logging.debug(f"Processing Plex library: {section_title} (type: {section_type})")

                        if section_type == "movie":
                            stats["movie_sections"] += 1
                            # Process movies
                            items_response = requests.get(
                                f"{url}/library/sections/{section_id}/all",
                                headers=headers
                            )

                            if items_response.status_code == 200:
                                try:
                                    items_data = items_response.json()
                                    metadata_items = items_data.get("MediaContainer", {}).get("Metadata", [])
                                    stats["total_movies_found"] += len(metadata_items)
                                    logging.debug(f"Found {len(metadata_items)} movies in section {section_title}")

                                    for item in metadata_items:
                                        try:
                                            media_list = item.get("Media", [])
                                            if not media_list:
                                                continue

                                            for media in media_list:
                                                parts = media.get("Part", [])
                                                if not parts:
                                                    continue

                                                file_path = parts[0].get("file")
                                                if not file_path:
                                                    continue

                                                # Apply path mapping to convert media server path to local path
                                                mapped_path = apply_path_mapping(file_path)

                                                # Check if the path exists, unless we're skipping that check
                                                path_exists = skip_path_check or os.path.exists(mapped_path)
                                                if not path_exists:
                                                    logging.debug(f"Movie path not found: {mapped_path}")
                                                    stats["path_not_found"] += 1
                                                    stats["skipped_movies"] += 1
                                                    continue

                                                media_id = str(uuid.uuid4())
                                                media_item = MediaItem(
                                                    id=media_id,
                                                    title=item.get("title", "Unknown Movie"),
                                                    year=item.get("year"),
                                                    type="movie",
                                                    path=mapped_path,
                                                    poster_url=f"{url}{item.get('thumb')}?X-Plex-Token={token}" if "thumb" in item else None,
                                                )
                                                media_items.append(media_item)
                                                MEDIA[media_id] = media_item
                                                stats["added_movies"] += 1
                                        except Exception as item_error:
                                            logging.error(f"Error processing movie item: {str(item_error)}")
                                except Exception as json_error:
                                    logging.error(f"Error parsing movie section JSON: {str(json_error)}")
                            else:
                                logging.error(f"Failed to fetch movies from section {section_id}: {items_response.status_code}")

                        elif section_type == "show":
                            stats["tv_sections"] += 1
                            # First get all shows in the section
                            shows_response = requests.get(
                                f"{url}/library/sections/{section_id}/all",
                                headers=headers
                            )

                            if shows_response.status_code == 200:
                                try:
                                    shows_data = shows_response.json()
                                    shows_list = shows_data.get("MediaContainer", {}).get("Metadata", [])
                                    logging.debug(f"Found {len(shows_list)} TV shows in section {section_title}")

                                    for show in shows_list:
                                        try:
                                            show_key = show.get("ratingKey")
                                            if not show_key:
                                                continue

                                            show_id = str(uuid.uuid4())
                                            shows_by_key[show_key] = TVShow(
                                                id=show_id,
                                                title=show.get("title", "Unknown Show"),
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
                                                try:
                                                    episodes_data = episodes_response.json()
                                                    episode_list = episodes_data.get("MediaContainer", {}).get("Metadata", [])
                                                    stats["total_episodes_found"] += len(episode_list)

                                                    logging.debug(f"Found {len(episode_list)} episodes for show {show.get('title', 'Unknown')}")

                                                    for episode in episode_list:
                                                        try:
                                                            media_list = episode.get("Media", [])
                                                            if not media_list:
                                                                continue

                                                            for media in media_list:
                                                                parts = media.get("Part", [])
                                                                if not parts:
                                                                    continue

                                                                file_path = parts[0].get("file")
                                                                if not file_path:
                                                                    continue

                                                                season_num = episode.get("parentIndex", 0)
                                                                episode_num = episode.get("index")

                                                                # Apply path mapping to convert media server path to local path
                                                                mapped_path = apply_path_mapping(file_path)

                                                                # Check if the path exists, unless we're skipping that check
                                                                path_exists = skip_path_check or os.path.exists(mapped_path)
                                                                if not path_exists:
                                                                    logging.debug(f"Episode path not found: {mapped_path}")
                                                                    stats["path_not_found"] += 1
                                                                    stats["skipped_episodes"] += 1
                                                                    continue

                                                                # Create a unique ID for this episode
                                                                media_id = str(uuid.uuid4())

                                                                # Create the Episode object
                                                                ep = Episode(
                                                                    id=media_id,
                                                                    season_number=season_num,
                                                                    episode_number=episode_num,
                                                                    title=episode.get("title", f"Episode {episode_num}"),
                                                                    year=episode.get("year"),
                                                                    path=mapped_path
                                                                )
                                                                shows_by_key[show_key].add_episode(ep)

                                                                # Create the MediaItem
                                                                media_item = MediaItem(
                                                                    id=media_id,
                                                                    title=episode.get("title", f"Episode {episode_num}"),
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
                                                                stats["added_episodes"] += 1
                                                        except Exception as episode_error:
                                                            logging.error(f"Error processing episode: {str(episode_error)}")
                                                except Exception as episodes_json_error:
                                                    logging.error(f"Error parsing episodes JSON: {str(episodes_json_error)}")
                                            else:
                                                logging.error(f"Failed to fetch episodes for show {show_key}: {episodes_response.status_code}")
                                        except Exception as show_error:
                                            logging.error(f"Error processing show: {str(show_error)}")
                                except Exception as shows_json_error:
                                    logging.error(f"Error parsing shows JSON: {str(shows_json_error)}")
                            else:
                                logging.error(f"Failed to fetch shows from section {section_id}: {shows_response.status_code}")
                    except Exception as section_error:
                        logging.error(f"Error processing library section: {str(section_error)}")
            except Exception as data_error:
                logging.error(f"Error processing library sections data: {str(data_error)}")
        else:
            logging.error(f"Failed to fetch library sections: {response.status_code}")
    except Exception as e:
        logging.error(f"Error scanning Plex: {str(e)}")

    # Log statistics
    logging.info(f"Plex scan statistics: {stats}")
    logging.info(f"Total media items added: {len(media_items)}")

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

    # Import here to avoid circular imports
    from squishy.socket_events import emit_scan_status

    SCAN_STATUS["in_progress"] = True
    SCAN_STATUS["source"] = "filesystem"
    SCAN_STATUS["started_at"] = time.time()
    SCAN_STATUS["item_count"] = 0

    # Emit status update
    emit_scan_status(SCAN_STATUS)

    try:
        media_items = scan_filesystem(media_paths)
        SCAN_STATUS["item_count"] = len(media_items)
    except Exception as e:
        logging.error(f"Error during filesystem scan: {str(e)}")
    finally:
        SCAN_STATUS["in_progress"] = False
        SCAN_STATUS["completed_at"] = time.time()
        # Emit final status update
        emit_scan_status(SCAN_STATUS)

def _run_scan_jellyfin(url: str, api_key: str):
    """Run Jellyfin scan in a separate thread."""
    global SCAN_STATUS

    # Import here to avoid circular imports
    from squishy.socket_events import emit_scan_status

    SCAN_STATUS["in_progress"] = True
    SCAN_STATUS["source"] = "jellyfin"
    SCAN_STATUS["started_at"] = time.time()
    SCAN_STATUS["item_count"] = 0

    # Emit status update
    emit_scan_status(SCAN_STATUS)

    try:
        media_items = scan_jellyfin(url, api_key)
        SCAN_STATUS["item_count"] = len(media_items)
    except Exception as e:
        logging.error(f"Error during Jellyfin scan: {str(e)}")
    finally:
        SCAN_STATUS["in_progress"] = False
        SCAN_STATUS["completed_at"] = time.time()
        # Emit final status update
        emit_scan_status(SCAN_STATUS)

def _run_scan_plex(url: str, token: str):
    """Run Plex scan in a separate thread."""
    global SCAN_STATUS

    # Import here to avoid circular imports
    from squishy.socket_events import emit_scan_status

    SCAN_STATUS["in_progress"] = True
    SCAN_STATUS["source"] = "plex"
    SCAN_STATUS["started_at"] = time.time()
    SCAN_STATUS["item_count"] = 0

    # Emit status update
    emit_scan_status(SCAN_STATUS)

    try:
        media_items = scan_plex(url, token)
        SCAN_STATUS["item_count"] = len(media_items)
    except Exception as e:
        logging.error(f"Error during Plex scan: {str(e)}")
    finally:
        SCAN_STATUS["in_progress"] = False
        SCAN_STATUS["completed_at"] = time.time()
        # Emit final status update
        emit_scan_status(SCAN_STATUS)

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
