"""Media library scanner."""

import os
import re
import uuid
import logging
import threading
import time
from typing import Dict, List, Optional, Tuple, Any

import requests

from squishy.models import MediaItem, Movie, Episode, TVShow
from squishy.config import load_config

# In-memory media store - in a real application, this would be in a database
MEDIA: Dict[str, MediaItem] = {}
TV_SHOWS: Dict[str, TVShow] = {}

# Thread locks for shared dictionaries
MEDIA_LOCK = threading.RLock()  # Use RLock to allow re-entry from the same thread
TV_SHOWS_LOCK = threading.RLock()

# Scanning status tracker
SCAN_STATUS = {
    "in_progress": False,
    "source": None,
    "started_at": None,
    "completed_at": None,
    "item_count": 0
}
SCAN_STATUS_LOCK = threading.RLock()

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

def scan_jellyfin(url: str, api_key: str) -> List[MediaItem]:
    """Scan a Jellyfin server for media."""
    media_items = []
    shows_by_id: Dict[str, TVShow] = {}

    # Clear all existing media data (thread-safe)
    with MEDIA_LOCK:
        media_count = len(MEDIA)
        MEDIA.clear()
        logging.info(f"Cleared {media_count} existing media items before starting Jellyfin scan")
        
    with TV_SHOWS_LOCK:
        shows_count = len(TV_SHOWS)
        TV_SHOWS.clear()
        logging.info(f"Cleared {shows_count} existing TV shows before starting Jellyfin scan")

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
                # Check if this library is enabled (only if explicitly True)
                if library_id in config.enabled_libraries and config.enabled_libraries.get(library_id) is True:
                    enabled_library_ids.append(library_id)
                    logging.debug(f"Including enabled Jellyfin library: {library.get('Name', 'Unknown')} (id: {library_id})")
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
                    
                    # Create a Movie instance
                    movie = Movie(
                        id=media_id,
                        title=item.get("Name", ""),
                        path=mapped_path,
                        year=item.get("ProductionYear"),
                        poster_url=f"{url.rstrip('/')}/Items/{item['Id']}/Images/Primary?API_KEY={api_key}",
                        # Use Backdrop for thumbnail - it's typically a landscape image that works well as thumbnail
                        thumbnail_url=f"{url.rstrip('/')}/Items/{item['Id']}/Images/Backdrop?API_KEY={api_key}",
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
                    media_items.append(movie)
                    with MEDIA_LOCK:
                        MEDIA[media_id] = movie
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
            with TV_SHOWS_LOCK:
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

            # Create an Episode instance (inherits from MediaItem)
            episode = Episode(
                id=media_id,
                title=item.get("Name", ""),
                path=mapped_path,
                year=item.get("ProductionYear"),
                season_number=season_num,
                show_id=show.id,
                episode_number=episode_num,
                # For episodes, the primary image is actually a thumbnail/screenshot
                poster_url=f"{url.rstrip('/')}/Items/{item['Id']}/Images/Primary?API_KEY={api_key}",
                # For episodes in Jellyfin, Primary also contains the landscape artwork
                thumbnail_url=f"{url.rstrip('/')}/Items/{item['Id']}/Images/Primary?API_KEY={api_key}",
                overview=item.get("Overview"),
                air_date=item.get("PremiereDate")
            )
            
            # Add to TV show
            show.add_episode(episode)
            
            # Add to media items
            media_items.append(episode)
            with MEDIA_LOCK:
                MEDIA[media_id] = episode
            stats["added_episodes"] += 1

    # Log statistics
    logging.info(f"Jellyfin scan statistics: {stats}")
    logging.info(f"Total media items added: {len(media_items)}")

    return media_items

def scan_plex(url: str, token: str) -> List[MediaItem]:
    """Scan a Plex server for media."""
    media_items = []
    shows_by_key: Dict[str, TVShow] = {}

    # Clear all existing media data (thread-safe)
    with MEDIA_LOCK:
        media_count = len(MEDIA)
        MEDIA.clear()
        logging.info(f"Cleared {media_count} existing media items before starting Plex scan")
        
    with TV_SHOWS_LOCK:
        shows_count = len(TV_SHOWS)
        TV_SHOWS.clear()
        logging.info(f"Cleared {shows_count} existing TV shows before starting Plex scan")

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

                        # Check if this library is enabled (only if explicitly True)
                        if section_id in config.enabled_libraries:
                            # Only include if explicitly True
                            if config.enabled_libraries.get(section_id) is not True:
                                logging.debug(f"Skipping disabled Plex library: {section_title} (id: {section_id})")
                                stats["skipped_libraries"] += 1
                                continue
                        # For libraries not in config, skip them (default to disabled)
                        else:
                            logging.debug(f"Skipping unconfigured Plex library: {section_title} (id: {section_id})")
                            stats["skipped_libraries"] += 1
                            continue

                        logging.debug(f"Processing Plex library: {section_title} (type: {section_type})")

                        if section_type == "movie":
                            stats["movie_sections"] += 1
                            # Process movies with all needed metadata
                            items_response = requests.get(
                                f"{url}/library/sections/{section_id}/all",
                                params={
                                    "includeFields": "summary,originallyAvailableAt,rating,contentRating,thumb,art,tagline,studio,genre,director,role,year"
                                },
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
                                                
                                                # Extract directors, actors, genres
                                                directors = []
                                                actors = []
                                                genres = []
                                                
                                                # Extract directors
                                                if "Director" in item and isinstance(item["Director"], list):
                                                    directors = [director.get("tag") for director in item["Director"] if director.get("tag")]
                                                
                                                # Extract actors/roles
                                                if "Role" in item and isinstance(item["Role"], list):
                                                    actors = [role.get("tag") for role in item["Role"] if role.get("tag")][:5]  # limit to 5 actors
                                                
                                                # Extract genres
                                                if "Genre" in item and isinstance(item["Genre"], list):
                                                    genres = [genre.get("tag") for genre in item["Genre"] if genre.get("tag")]
                                                
                                                # Create a Movie instance with all metadata
                                                movie = Movie(
                                                    id=media_id,
                                                    title=item.get("title", "Unknown Movie"),
                                                    path=mapped_path,
                                                    year=item.get("year"),
                                                    poster_url=f"{url}{item.get('thumb')}?X-Plex-Token={token}" if "thumb" in item else None,
                                                    # Use art or backdrop for thumbnail if available, fallback to poster/thumb
                                                    thumbnail_url=f"{url}{item.get('art')}?X-Plex-Token={token}" if "art" in item else (
                                                        f"{url}{item.get('thumb')}?X-Plex-Token={token}" if "thumb" in item else None
                                                    ),
                                                    # Add additional metadata
                                                    overview=item.get("summary"),
                                                    tagline=item.get("tagline"),
                                                    genres=genres,
                                                    directors=directors,
                                                    actors=actors,
                                                    release_date=item.get("originallyAvailableAt"),
                                                    rating=item.get("rating"),
                                                    content_rating=item.get("contentRating"),
                                                    studio=item.get("studio")
                                                )
                                                media_items.append(movie)
                                                with MEDIA_LOCK:
                                                    MEDIA[media_id] = movie
                                                stats["added_movies"] += 1
                                        except Exception as item_error:
                                            logging.error(f"Error processing movie item: {str(item_error)}")
                                except Exception as json_error:
                                    logging.error(f"Error parsing movie section JSON: {str(json_error)}")
                            else:
                                logging.error(f"Failed to fetch movies from section {section_id}: {items_response.status_code}")

                        elif section_type == "show":
                            stats["tv_sections"] += 1
                            # First get all shows in the section with all needed metadata
                            shows_response = requests.get(
                                f"{url}/library/sections/{section_id}/all",
                                params={
                                    "includeFields": "summary,originallyAvailableAt,rating,contentRating,thumb,art,tagline,studio,genre,director,writer,producer,role,year"
                                },
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
                                            # Extract genres, directors/creators, actors
                                            genres = []
                                            creators = []
                                            actors = []
                                            
                                            # If show has genre tags, add them
                                            if "Genre" in show and isinstance(show["Genre"], list):
                                                genres = [genre.get("tag") for genre in show["Genre"] if genre.get("tag")]
                                            
                                            # If show has director/writer/producer tags, add them as creators
                                            if "Director" in show and isinstance(show["Director"], list):
                                                creators.extend([director.get("tag") for director in show["Director"] if director.get("tag")])
                                            if "Writer" in show and isinstance(show["Writer"], list):
                                                creators.extend([writer.get("tag") for writer in show["Writer"] if writer.get("tag")])
                                            if "Producer" in show and isinstance(show["Producer"], list):
                                                creators.extend([producer.get("tag") for producer in show["Producer"] if producer.get("tag")])
                                            
                                            # If show has role/actor tags, add them
                                            if "Role" in show and isinstance(show["Role"], list):
                                                actors = [role.get("tag") for role in show["Role"] if role.get("tag")][:5]  # limit to 5 actors
                                            
                                            # Create the TV show with all available metadata
                                            shows_by_key[show_key] = TVShow(
                                                id=show_id,
                                                title=show.get("title", "Unknown Show"),
                                                year=show.get("year"),
                                                poster_url=f"{url}{show.get('thumb')}?X-Plex-Token={token}" if "thumb" in show else None,
                                                overview=show.get("summary"),
                                                tagline=show.get("tagline"),
                                                genres=genres,
                                                creators=creators,
                                                actors=actors,
                                                first_air_date=show.get("originallyAvailableAt"),
                                                rating=show.get("rating"),
                                                content_rating=show.get("contentRating"),
                                                studio=show.get("studio"),
                                            )
                                            with TV_SHOWS_LOCK:
                                                TV_SHOWS[show_id] = shows_by_key[show_key]

                                            # Get episodes for this show with all required fields
                                            episodes_response = requests.get(
                                                f"{url}/library/metadata/{show_key}/allLeaves",
                                                params={
                                                    "includeFields": "summary,originallyAvailableAt,rating,contentRating,thumb,art,year,index,parentIndex"
                                                },
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

                                                                # Create an Episode instance (inherits from MediaItem)
                                                                episode_obj = Episode(
                                                                    id=media_id,
                                                                    title=episode.get("title", f"Episode {episode_num}"),
                                                                    path=mapped_path,
                                                                    year=episode.get("year"),
                                                                    season_number=season_num,
                                                                    show_id=show_id,
                                                                    episode_number=episode_num,
                                                                    # For episodes, thumb is actually the thumbnail (screenshot from episode)
                                                                    poster_url=f"{url}{episode.get('thumb')}?X-Plex-Token={token}" if "thumb" in episode else None,
                                                                    # Use thumb as thumbnail for episodes (it's the episode screenshot)
                                                                    # Fall back to art if thumb is missing
                                                                    thumbnail_url=f"{url}{episode.get('thumb')}?X-Plex-Token={token}" if "thumb" in episode else (
                                                                        f"{url}{episode.get('art')}?X-Plex-Token={token}" if "art" in episode else None
                                                                    ),
                                                                    # Add episode details
                                                                    overview=episode.get("summary"),
                                                                    air_date=episode.get("originallyAvailableAt"),
                                                                    rating=episode.get("rating")
                                                                )
                                                                
                                                                # Add to TV show
                                                                shows_by_key[show_key].add_episode(episode_obj)
                                                                
                                                                # Add to media items
                                                                media_items.append(episode_obj)
                                                                with MEDIA_LOCK:
                                                                    MEDIA[media_id] = episode_obj
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
    with MEDIA_LOCK:
        return MEDIA.get(media_id)

def get_all_media() -> List[MediaItem]:
    """Get all media items."""
    with MEDIA_LOCK:
        return list(MEDIA.values())

def get_all_shows() -> List[TVShow]:
    """Get all TV shows."""
    with TV_SHOWS_LOCK:
        return list(TV_SHOWS.values())

def get_show(show_id: str) -> Optional[TVShow]:
    """Get a TV show by ID."""
    with TV_SHOWS_LOCK:
        return TV_SHOWS.get(show_id)

def get_shows_and_movies() -> Tuple[List[TVShow], List[MediaItem]]:
    """
    Get all TV shows and movies.

    Filters out:
    - TV shows with no episodes
    - Movies with no video file (missing path)
    """
    # Get thread-safe copies of the data
    with TV_SHOWS_LOCK:
        # Filter TV shows to only include those with episodes
        shows_with_episodes = [show for show in TV_SHOWS.values() if show.seasons and any(season.episodes for season in show.seasons.values())]

    with MEDIA_LOCK:
        # Filter movies to only include those with a valid path (skipping os.path.exists check which is slow)
        valid_movies = [
            item for item in MEDIA.values()
            if isinstance(item, Movie) and item.path
        ]

    return shows_with_episodes, valid_movies

def get_scan_status():
    """Get the current scanning status."""
    with SCAN_STATUS_LOCK:
        # Return a copy to avoid race conditions with modifications after returning
        return dict(SCAN_STATUS)


def _run_scan_jellyfin(url: str, api_key: str):
    """Run Jellyfin scan in a separate thread."""
    global SCAN_STATUS

    # Import here to avoid circular imports
    from squishy.socket_events import emit_scan_status

    # Update scan status with thread safety
    with SCAN_STATUS_LOCK:
        SCAN_STATUS["in_progress"] = True
        SCAN_STATUS["source"] = "jellyfin"
        SCAN_STATUS["started_at"] = time.time()
        SCAN_STATUS["item_count"] = 0
        
        # Get a copy for emitting
        status_copy = dict(SCAN_STATUS)

    # Emit status update
    emit_scan_status(status_copy)

    try:
        media_items = scan_jellyfin(url, api_key)
        
        # Update item count with thread safety
        with SCAN_STATUS_LOCK:
            SCAN_STATUS["item_count"] = len(media_items)
    except Exception as e:
        logging.error(f"Error during Jellyfin scan: {str(e)}")
    finally:
        # Update completion status with thread safety
        with SCAN_STATUS_LOCK:
            SCAN_STATUS["in_progress"] = False
            SCAN_STATUS["completed_at"] = time.time()
            
            # Get a copy for emitting
            status_copy = dict(SCAN_STATUS)
            
        # Emit final status update
        emit_scan_status(status_copy)

def _run_scan_plex(url: str, token: str):
    """Run Plex scan in a separate thread."""
    global SCAN_STATUS

    # Import here to avoid circular imports
    from squishy.socket_events import emit_scan_status

    # Update scan status with thread safety
    with SCAN_STATUS_LOCK:
        SCAN_STATUS["in_progress"] = True
        SCAN_STATUS["source"] = "plex"
        SCAN_STATUS["started_at"] = time.time()
        SCAN_STATUS["item_count"] = 0
        
        # Get a copy for emitting
        status_copy = dict(SCAN_STATUS)

    # Emit status update
    emit_scan_status(status_copy)

    try:
        media_items = scan_plex(url, token)
        
        # Update item count with thread safety
        with SCAN_STATUS_LOCK:
            SCAN_STATUS["item_count"] = len(media_items)
    except Exception as e:
        logging.error(f"Error during Plex scan: {str(e)}")
    finally:
        # Update completion status with thread safety
        with SCAN_STATUS_LOCK:
            SCAN_STATUS["in_progress"] = False
            SCAN_STATUS["completed_at"] = time.time()
            
            # Get a copy for emitting
            status_copy = dict(SCAN_STATUS)
            
        # Emit final status update
        emit_scan_status(status_copy)


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


def get_jellyfin_libraries(url: str, api_key: str) -> List[Dict[str, Any]]:
    """
    Get list of libraries from Jellyfin.
    
    Args:
        url: Jellyfin server URL
        api_key: Jellyfin API key
        
    Returns:
        List of library dictionaries with id, name, and enabled status
    """
    config = load_config()
    headers = {
        "X-MediaBrowser-Token": api_key,
        "Content-Type": "application/json",
    }
    
    libraries = []
    
    try:
        response = requests.get(f"{url}/Library/VirtualFolders", headers=headers)
        if response.status_code == 200:
            libraries_data = response.json()
            
            for library in libraries_data:
                library_id = library.get("ItemId")
                library_name = library.get("Name", "Unknown")
                library_type = library.get("CollectionType", "Unknown")
                
                if library_id:
                    # Check if this library is enabled in our config
                    # Only True if explicitly set to True in config
                    enabled = config.enabled_libraries.get(library_id, True) is True
                        
                    libraries.append({
                        "id": library_id,
                        "name": library_name,
                        "type": library_type,
                        "enabled": enabled
                    })
        else:
            logging.error(f"Failed to get Jellyfin libraries: {response.status_code}")
    except Exception as e:
        logging.error(f"Error getting Jellyfin libraries: {str(e)}")
    
    return libraries


def get_plex_libraries(url: str, token: str) -> List[Dict[str, Any]]:
    """
    Get list of libraries from Plex.
    
    Args:
        url: Plex server URL
        token: Plex authentication token
        
    Returns:
        List of library dictionaries with id, name, and enabled status
    """
    config = load_config()
    headers = {
        "X-Plex-Token": token,
        "Accept": "application/json"
    }
    
    libraries = []
    
    try:
        # Plex uses a different endpoint to list libraries
        response = requests.get(f"{url}/library/sections", headers=headers)
        if response.status_code == 200:
            data = response.json()
            sections = data.get("MediaContainer", {}).get("Directory", [])
            
            for section in sections:
                section_id = section.get("key")
                section_title = section.get("title", "Unknown")
                section_type = section.get("type", "Unknown")
                
                if section_id:
                    # Check if this library is enabled in our config
                    # Only True if explicitly set to True in config
                    enabled = config.enabled_libraries.get(section_id, True) is True
                        
                    libraries.append({
                        "id": section_id,
                        "name": section_title,
                        "type": section_type,
                        "enabled": enabled
                    })
        else:
            logging.error(f"Failed to get Plex libraries: {response.status_code}")
    except Exception as e:
        logging.error(f"Error getting Plex libraries: {str(e)}")
    
    return libraries