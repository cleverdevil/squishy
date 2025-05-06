"""Media library scanner."""

import os
import uuid
import logging
import threading
import time
from abc import ABC, abstractmethod
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
    "item_count": 0,
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
        config.path_mappings.items(), key=lambda x: len(x[0]), reverse=True
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


class MediaServerScanner(ABC):
    """Base class for media server scanners."""

    def __init__(self, url: str, token: str, name: str):
        """
        Initialize the scanner.

        Args:
            url: Server URL
            token: Authentication token or API key
            name: Name of the media server (used for logging)
        """
        self.url = url
        self.token = token
        self.name = name
        self.skip_path_check = os.environ.get(
            "SQUISHY_SKIP_PATH_CHECK", ""
        ).lower() in ("true", "1", "yes")
        self.config = load_config()
        self.media_items = []

        # Statistics for debugging
        self.stats = {
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
            "skipped_libraries": 0,
        }

    def clear_existing_data(self):
        """Clear existing media data (thread-safe)."""
        with MEDIA_LOCK:
            media_count = len(MEDIA)
            MEDIA.clear()
            logging.info(
                f"Cleared {media_count} existing media items before starting {self.name} scan"
            )

        with TV_SHOWS_LOCK:
            shows_count = len(TV_SHOWS)
            TV_SHOWS.clear()
            logging.info(
                f"Cleared {shows_count} existing TV shows before starting {self.name} scan"
            )

    def path_exists(self, path: str) -> bool:
        """Check if path exists, respecting skip_path_check flag."""
        return self.skip_path_check or os.path.exists(path)

    def add_movie_to_collection(self, movie: Movie):
        """Add a movie to the collection."""
        self.media_items.append(movie)
        with MEDIA_LOCK:
            MEDIA[movie.id] = movie
        self.stats["added_movies"] += 1

    def add_episode_to_collection(self, episode: Episode):
        """Add an episode to the collection."""
        self.media_items.append(episode)
        with MEDIA_LOCK:
            MEDIA[episode.id] = episode
        self.stats["added_episodes"] += 1

    def add_show_to_collection(self, show_id: str, show: TVShow):
        """Add a show to the collection."""
        with TV_SHOWS_LOCK:
            TV_SHOWS[show_id] = show

    def log_statistics(self):
        """Log scan statistics."""
        logging.info(f"{self.name} scan statistics: {self.stats}")
        logging.info(f"Total media items added: {len(self.media_items)}")

    def get_added_item_count(self) -> int:
        """
        Get the count of actually added items (movies + episodes).
        This is more accurate than total items found as it only counts items
        that passed all filtering and were actually added to the collection.
        """
        return self.stats["added_movies"] + self.stats["added_episodes"]

    @abstractmethod
    def scan(self) -> List[MediaItem]:
        """Scan the media server for media items."""
        pass

    @abstractmethod
    def get_libraries(self) -> List[Dict[str, Any]]:
        """Get list of libraries from the media server."""
        pass


class PlexScanner(MediaServerScanner):
    """Scanner for Plex media servers."""

    def __init__(self, url: str, token: str):
        """Initialize Plex scanner."""
        super().__init__(url, token, "Plex")
        self.shows_by_key = {}

    def get_headers(self) -> Dict[str, str]:
        """Get headers for Plex API requests."""
        return {"X-Plex-Token": self.token, "Accept": "application/json"}

    def process_movie(self, movie_item: Dict) -> Optional[Movie]:
        """Process a single Plex movie item and return a Movie object if valid."""
        try:
            return self._process_movie(movie_item)
        except Exception as item_error:
            logging.error(f"Error processing movie item: {str(item_error)}")

    def _process_movie(self, movie_item: Dict) -> Optional[Movie]:
        media_list = movie_item.get("Media", [])
        if not media_list:
            return None

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
            if not self.path_exists(mapped_path):
                logging.debug(f"Movie path not found: {mapped_path}")
                self.stats["path_not_found"] += 1
                return None

            media_id = str(uuid.uuid4())

            # Extract directors, actors, genres
            directors = []
            actors = []
            genres = []

            # Extract directors
            if "Director" in movie_item and isinstance(movie_item["Director"], list):
                directors = [
                    director.get("tag")
                    for director in movie_item["Director"]
                    if director.get("tag")
                ]

            # Extract actors/roles
            if "Role" in movie_item and isinstance(movie_item["Role"], list):
                actors = [
                    role.get("tag") for role in movie_item["Role"] if role.get("tag")
                ][:5]  # limit to 5 actors

            # Extract genres
            if "Genre" in movie_item and isinstance(movie_item["Genre"], list):
                genres = [
                    genre.get("tag")
                    for genre in movie_item["Genre"]
                    if genre.get("tag")
                ]

            # Create a Movie instance with all metadata
            movie = Movie(
                id=media_id,
                title=movie_item.get("title", "Unknown Movie"),
                path=mapped_path,
                year=movie_item.get("year"),
                poster_url=f"{self.url}{movie_item.get('thumb')}?X-Plex-Token={self.token}"
                if "thumb" in movie_item
                else None,
                # Use art or backdrop for thumbnail if available, fallback to poster/thumb
                thumbnail_url=f"{self.url}{movie_item.get('art')}?X-Plex-Token={self.token}"
                if "art" in movie_item
                else (
                    f"{self.url}{movie_item.get('thumb')}?X-Plex-Token={self.token}"
                    if "thumb" in movie_item
                    else None
                ),
                # Add additional metadata
                overview=movie_item.get("summary"),
                tagline=movie_item.get("tagline"),
                genres=genres,
                directors=directors,
                actors=actors,
                release_date=movie_item.get("originallyAvailableAt"),
                rating=movie_item.get("rating"),
                content_rating=movie_item.get("contentRating"),
                studio=movie_item.get("studio"),
            )

            return movie

        return None

    def process_tv_show(self, show_item: Dict) -> Optional[Tuple[str, TVShow]]:
        """Process a single Plex TV show item and return (show_key, TVShow) tuple if valid."""
        try:
            show_key = show_item.get("ratingKey")
            if not show_key:
                return None

            show_id = str(uuid.uuid4())

            # Extract genres, directors/creators, actors
            genres = []
            creators = []
            actors = []

            # If show has genre tags, add them
            if "Genre" in show_item and isinstance(show_item["Genre"], list):
                genres = [
                    genre.get("tag") for genre in show_item["Genre"] if genre.get("tag")
                ]

            # If show has director/writer/producer tags, add them as creators
            if "Director" in show_item and isinstance(show_item["Director"], list):
                creators.extend(
                    [
                        director.get("tag")
                        for director in show_item["Director"]
                        if director.get("tag")
                    ]
                )
            if "Writer" in show_item and isinstance(show_item["Writer"], list):
                creators.extend(
                    [
                        writer.get("tag")
                        for writer in show_item["Writer"]
                        if writer.get("tag")
                    ]
                )
            if "Producer" in show_item and isinstance(show_item["Producer"], list):
                creators.extend(
                    [
                        producer.get("tag")
                        for producer in show_item["Producer"]
                        if producer.get("tag")
                    ]
                )

            # If show has role/actor tags, add them
            if "Role" in show_item and isinstance(show_item["Role"], list):
                actors = [
                    role.get("tag") for role in show_item["Role"] if role.get("tag")
                ][:5]  # limit to 5 actors

            # Create the TV show with all available metadata
            show = TVShow(
                id=show_id,
                title=show_item.get("title", "Unknown Show"),
                year=show_item.get("year"),
                poster_url=f"{self.url}{show_item.get('thumb')}?X-Plex-Token={self.token}"
                if "thumb" in show_item
                else None,
                overview=show_item.get("summary"),
                tagline=show_item.get("tagline"),
                genres=genres,
                creators=creators,
                actors=actors,
                first_air_date=show_item.get("originallyAvailableAt"),
                rating=show_item.get("rating"),
                content_rating=show_item.get("contentRating"),
                studio=show_item.get("studio"),
            )

            return (show_key, show)
        except Exception as show_error:
            logging.error(f"Error processing show: {str(show_error)}")

        return None

    def process_episode(self, episode_item: Dict, show: TVShow) -> Optional[Episode]:
        """Process a single Plex episode item and return an Episode object if valid."""
        try:
            media_list = episode_item.get("Media", [])
            if not media_list:
                return None

            for media in media_list:
                parts = media.get("Part", [])
                if not parts:
                    continue

                file_path = parts[0].get("file")
                if not file_path:
                    continue

                season_num = episode_item.get("parentIndex", 0)
                episode_num = episode_item.get("index")

                # Apply path mapping to convert media server path to local path
                mapped_path = apply_path_mapping(file_path)

                # Check if the path exists, unless we're skipping that check
                if not self.path_exists(mapped_path):
                    logging.debug(f"Episode path not found: {mapped_path}")
                    self.stats["path_not_found"] += 1
                    return None

                # Create a unique ID for this episode
                media_id = str(uuid.uuid4())

                # Create an Episode instance (inherits from MediaItem)
                episode = Episode(
                    id=media_id,
                    title=episode_item.get("title", f"Episode {episode_num}"),
                    path=mapped_path,
                    year=episode_item.get("year"),
                    season_number=season_num,
                    show_id=show.id,
                    episode_number=episode_num,
                    # For episodes, thumb is actually the thumbnail (screenshot from episode)
                    poster_url=f"{self.url}{episode_item.get('thumb')}?X-Plex-Token={self.token}"
                    if "thumb" in episode_item
                    else None,
                    # Use thumb as thumbnail for episodes (it's the episode screenshot)
                    # Fall back to art if thumb is missing
                    thumbnail_url=f"{self.url}{episode_item.get('thumb')}?X-Plex-Token={self.token}"
                    if "thumb" in episode_item
                    else (
                        f"{self.url}{episode_item.get('art')}?X-Plex-Token={self.token}"
                        if "art" in episode_item
                        else None
                    ),
                    # Add episode details
                    overview=episode_item.get("summary"),
                    air_date=episode_item.get("originallyAvailableAt"),
                    rating=episode_item.get("rating"),
                )

                return episode
        except Exception as episode_error:
            logging.error(f"Error processing episode: {str(episode_error)}")

        return None

    def process_library_section(self, section: Dict) -> List[MediaItem]:
        """Process a single Plex library section and return the media items found."""
        section_media_items = []

        try:
            section_id = section.get("key")
            section_type = section.get("type")
            section_title = section.get("title", "Unknown")

            if not section_id:
                logging.warning(f"Missing section key in section: {section_title}")
                return section_media_items

            # Check if this library is enabled (only if explicitly True)
            if section_id in self.config.enabled_libraries:
                # Only include if explicitly True
                if self.config.enabled_libraries.get(section_id) is not True:
                    logging.debug(
                        f"Skipping disabled Plex library: {section_title} (id: {section_id})"
                    )
                    self.stats["skipped_libraries"] += 1
                    return section_media_items
            # For libraries not in config, skip them (default to disabled)
            else:
                logging.debug(
                    f"Skipping unconfigured Plex library: {section_title} (id: {section_id})"
                )
                self.stats["skipped_libraries"] += 1
                return section_media_items

            logging.debug(
                f"Processing Plex library: {section_title} (type: {section_type})"
            )

            if section_type == "movie":
                self.stats["movie_sections"] += 1
                section_media_items.extend(
                    self.process_movie_section(section_id, section_title)
                )
            elif section_type == "show":
                self.stats["tv_sections"] += 1
                section_media_items.extend(
                    self.process_tv_section(section_id, section_title)
                )
        except Exception as section_error:
            logging.error(f"Error processing library section: {str(section_error)}")

        return section_media_items

    def process_movie_section(
        self, section_id: str, section_title: str
    ) -> List[MediaItem]:
        """Process a movie library section."""
        section_media_items = []

        # Process movies with all needed metadata
        items_response = requests.get(
            f"{self.url}/library/sections/{section_id}/all",
            params={
                "includeFields": "summary,originallyAvailableAt,rating,contentRating,thumb,art,tagline,studio,genre,director,role,year"
            },
            headers=self.get_headers(),
        )

        if items_response.status_code == 200:
            try:
                items_data = items_response.json()
                metadata_items = items_data.get("MediaContainer", {}).get(
                    "Metadata", []
                )
                logging.debug(
                    f"Found {len(metadata_items)} movies in section {section_title}"
                )

                # Only add the count to our stats if the library is enabled
                if (
                    section_id in self.config.enabled_libraries
                    and self.config.enabled_libraries.get(section_id) is True
                ):
                    self.stats["total_movies_found"] += len(metadata_items)

                for item in metadata_items:
                    movie = self.process_movie(item)
                    if movie:
                        self.add_movie_to_collection(movie)
                        section_media_items.append(movie)
                    else:
                        self.stats["skipped_movies"] += 1
            except Exception as json_error:
                logging.error(f"Error parsing movie section JSON: {str(json_error)}")
        else:
            logging.error(
                f"Failed to fetch movies from section {section_id}: {items_response.status_code}"
            )

        return section_media_items

    def process_tv_section(
        self, section_id: str, section_title: str
    ) -> List[MediaItem]:
        """Process a TV library section."""
        section_media_items = []

        # First get all shows in the section with all needed metadata
        shows_response = requests.get(
            f"{self.url}/library/sections/{section_id}/all",
            params={
                "includeFields": "summary,originallyAvailableAt,rating,contentRating,thumb,art,tagline,studio,genre,director,writer,producer,role,year"
            },
            headers=self.get_headers(),
        )

        if shows_response.status_code == 200:
            try:
                shows_data = shows_response.json()
                shows_list = shows_data.get("MediaContainer", {}).get("Metadata", [])
                logging.debug(
                    f"Found {len(shows_list)} TV shows in section {section_title}"
                )

                for show_item in shows_list:
                    show_data = self.process_tv_show(show_item)
                    if not show_data:
                        continue

                    show_key, show = show_data
                    self.shows_by_key[show_key] = show
                    self.add_show_to_collection(show.id, show)

                    # Get episodes for this show
                    section_media_items.extend(
                        self.process_show_episodes(show_key, show)
                    )

            except Exception as shows_json_error:
                logging.error(f"Error parsing shows JSON: {str(shows_json_error)}")
        else:
            logging.error(
                f"Failed to fetch shows from section {section_id}: {shows_response.status_code}"
            )

        return section_media_items

    def process_show_episodes(self, show_key: str, show: TVShow) -> List[Episode]:
        """Process all episodes for a show."""
        episodes = []

        # Get episodes for this show with all required fields
        episodes_response = requests.get(
            f"{self.url}/library/metadata/{show_key}/allLeaves",
            params={
                "includeFields": "summary,originallyAvailableAt,rating,contentRating,thumb,art,year,index,parentIndex"
            },
            headers=self.get_headers(),
        )

        if episodes_response.status_code == 200:
            try:
                episodes_data = episodes_response.json()
                episode_list = episodes_data.get("MediaContainer", {}).get(
                    "Metadata", []
                )

                # Only count episodes from enabled libraries
                logging.debug(
                    f"Found {len(episode_list)} episodes for show {show.title}"
                )
                self.stats["total_episodes_found"] += len(episode_list)

                for episode_item in episode_list:
                    episode = self.process_episode(episode_item, show)
                    if episode:
                        # Add to TV show
                        show.add_episode(episode)

                        # Add to collection
                        self.add_episode_to_collection(episode)
                        episodes.append(episode)
                    else:
                        self.stats["skipped_episodes"] += 1
            except Exception as episodes_json_error:
                logging.error(
                    f"Error parsing episodes JSON: {str(episodes_json_error)}"
                )
        else:
            logging.error(
                f"Failed to fetch episodes for show {show_key}: {episodes_response.status_code}"
            )

        return episodes

    def fetch_library_sections(self) -> List[Dict]:
        """Fetch library sections from Plex server."""
        try:
            response = requests.get(
                f"{self.url}/library/sections", headers=self.get_headers()
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("MediaContainer", {}).get("Directory", [])
            else:
                logging.error(
                    f"Failed to fetch library sections: {response.status_code}"
                )
        except Exception as e:
            logging.error(f"Error fetching Plex library sections: {str(e)}")

        return []

    def scan(self) -> List[MediaItem]:
        """Scan Plex server for media."""
        self.media_items = []
        self.shows_by_key = {}

        # Clear existing data
        self.clear_existing_data()

        if self.skip_path_check:
            logging.debug("Path existence check disabled via SQUISHY_SKIP_PATH_CHECK")

        try:
            # Fetch libraries
            logging.debug(f"Connecting to Plex server at {self.url}")
            sections = self.fetch_library_sections()
            self.stats["library_sections"] = len(sections)
            logging.debug(f"Found {len(sections)} library sections in Plex")

            # Process each library section
            for section in sections:
                section_media_items = self.process_library_section(section)
                self.media_items.extend(section_media_items)

        except Exception as e:
            logging.error(f"Error scanning Plex: {str(e)}")

        # Log statistics
        self.log_statistics()

        return self.media_items

    def get_libraries(self) -> List[Dict[str, Any]]:
        """
        Get list of libraries from Plex.

        Returns:
            List of library dictionaries with id, name, and enabled status
        """
        libraries = []

        try:
            # Plex uses a different endpoint to list libraries
            response = requests.get(
                f"{self.url}/library/sections", headers=self.get_headers()
            )
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
                        enabled = (
                            self.config.enabled_libraries.get(section_id, True) is True
                        )

                        libraries.append(
                            {
                                "id": section_id,
                                "name": section_title,
                                "type": section_type,
                                "enabled": enabled,
                            }
                        )
            else:
                logging.error(f"Failed to get Plex libraries: {response.status_code}")
        except Exception as e:
            logging.error(f"Error getting Plex libraries: {str(e)}")

        return libraries


class JellyfinScanner(MediaServerScanner):
    """Scanner for Jellyfin media servers."""

    def __init__(self, url: str, api_key: str):
        """Initialize Jellyfin scanner."""
        super().__init__(url, api_key, "Jellyfin")
        self.shows_by_id = {}

    def get_headers(self) -> Dict[str, str]:
        """Get headers for Jellyfin API requests."""
        return {
            "X-MediaBrowser-Token": self.token,
            "Content-Type": "application/json",
        }

    def get_enabled_library_ids(self) -> List[str]:
        """Get IDs of enabled libraries."""
        enabled_library_ids = []

        # First get all libraries to check which ones are enabled
        libraries_response = requests.get(
            f"{self.url}/Library/VirtualFolders", headers=self.get_headers()
        )

        if libraries_response.status_code == 200:
            libraries = libraries_response.json()
            for library in libraries:
                library_id = library.get("ItemId")
                if library_id:
                    # Check if this library is enabled (only if explicitly True)
                    if (
                        library_id in self.config.enabled_libraries
                        and self.config.enabled_libraries.get(library_id) is True
                    ):
                        enabled_library_ids.append(library_id)
                        logging.debug(
                            f"Including enabled Jellyfin library: {library.get('Name', 'Unknown')} (id: {library_id})"
                        )
                    else:
                        logging.debug(
                            f"Skipping disabled Jellyfin library: {library.get('Name', 'Unknown')} (id: {library_id})"
                        )
                        self.stats["skipped_libraries"] += 1

        return enabled_library_ids

    def fetch_movies(self, enabled_library_ids: List[str]) -> List[Dict]:
        """Fetch movies from enabled libraries."""
        movie_items = []

        # If no enabled libraries, skip scanning
        if not enabled_library_ids:
            logging.warning("No enabled Jellyfin libraries found to scan")
            return movie_items

        for library_id in enabled_library_ids:
            response = requests.get(
                f"{self.url}/Items",
                params={
                    "IncludeItemTypes": "Movie",
                    "Recursive": "true",
                    "Fields": "Path,Year,Overview,Genres,Studios,OfficialRating,CommunityRating,PremiereDate,Taglines,People",
                    "ParentId": library_id,
                },
                headers=self.get_headers(),
            )

            if response.status_code == 200:
                data = response.json()
                items = data.get("Items", [])
                movie_items.extend(items)
                logging.debug(f"Found {len(items)} movies in library {library_id}")
            else:
                logging.error(
                    f"Failed to retrieve movies from library {library_id}: HTTP {response.status_code}"
                )

        return movie_items

    def process_movies(self, movie_items: List[Dict]) -> List[Movie]:
        """Process movie items into Movie objects."""
        movies = []

        self.stats["total_movies_found"] = len(movie_items)

        if not movie_items:
            return movies

        for item in movie_items:
            if "Path" in item:
                media_id = str(uuid.uuid4())

                # Apply path mapping to convert media server path to local path
                mapped_path = apply_path_mapping(item["Path"])

                # Only add if the path exists
                if mapped_path and self.path_exists(mapped_path):
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
                    if (
                        item.get("Taglines")
                        and isinstance(item.get("Taglines"), list)
                        and len(item.get("Taglines")) > 0
                    ):
                        tagline = item.get("Taglines")[0]

                    # Handle genres safely
                    genres = []
                    if item.get("Genres") and isinstance(item.get("Genres"), list):
                        genres = [
                            g.get("Name")
                            for g in item.get("Genres")
                            if isinstance(g, dict) and g.get("Name")
                        ]

                    # Create a Movie instance
                    movie = Movie(
                        id=media_id,
                        title=item.get("Name", ""),
                        path=mapped_path,
                        year=item.get("ProductionYear"),
                        poster_url=f"{self.url.rstrip('/')}/Items/{item['Id']}/Images/Primary?API_KEY={self.token}",
                        # Use Backdrop for thumbnail - it's typically a landscape image that works well as thumbnail
                        thumbnail_url=f"{self.url.rstrip('/')}/Items/{item['Id']}/Images/Backdrop?API_KEY={self.token}",
                        overview=item.get("Overview"),
                        tagline=tagline,
                        genres=genres,
                        directors=directors,
                        actors=actors[:5],  # Limit to top 5 actors
                        release_date=item.get("PremiereDate"),
                        rating=item.get("CommunityRating"),
                        content_rating=item.get("OfficialRating"),
                        studio=studio,
                    )

                    movies.append(movie)
                    self.add_movie_to_collection(movie)
                else:
                    self.stats["path_not_found"] += 1
                    self.stats["skipped_movies"] += 1

        return movies

    def fetch_tv_series(self, enabled_library_ids: List[str]) -> List[Dict]:
        """Fetch TV series from enabled libraries."""
        series_items = []

        if not enabled_library_ids:
            return series_items

        for library_id in enabled_library_ids:
            response = requests.get(
                f"{self.url}/Items",
                params={
                    "IncludeItemTypes": "Series",
                    "Recursive": "true",
                    "Fields": "Path,Year,Overview,Genres,Studios,OfficialRating,CommunityRating,PremiereDate,Taglines,People",
                    "ParentId": library_id,
                },
                headers=self.get_headers(),
            )

            if response.status_code == 200:
                data = response.json()
                items = data.get("Items", [])
                series_items.extend(items)
                logging.debug(f"Found {len(items)} TV series in library {library_id}")
            else:
                logging.error(
                    f"Failed to retrieve TV series from library {library_id}: HTTP {response.status_code}"
                )

        return series_items

    def process_tv_series(self, series_items: List[Dict]) -> Dict[str, TVShow]:
        """Process TV series items into TVShow objects."""
        shows_by_id = {}

        for item in series_items:
            series_id = item["Id"]
            show_id = str(uuid.uuid4())

            # Extract directors and actors
            creators = []
            actors = []
            if "People" in item:
                for person in item.get("People", []):
                    if (
                        person.get("Type") == "Director"
                        or person.get("Type") == "Creator"
                    ):
                        creators.append(person.get("Name"))
                    elif person.get("Type") == "Actor":
                        actors.append(person.get("Name"))

            # Get studio
            studio = None
            if (
                item.get("Studios")
                and isinstance(item.get("Studios"), list)
                and len(item.get("Studios")) > 0
            ):
                studio_obj = item.get("Studios")[0]
                if isinstance(studio_obj, dict):
                    studio = studio_obj.get("Name")

            # Handle taglines safely
            tagline = None
            if (
                item.get("Taglines")
                and isinstance(item.get("Taglines"), list)
                and len(item.get("Taglines")) > 0
            ):
                tagline = item.get("Taglines")[0]

            # Handle genres safely
            genres = []
            if item.get("Genres") and isinstance(item.get("Genres"), list):
                genres = [
                    g.get("Name")
                    for g in item.get("Genres")
                    if isinstance(g, dict) and g.get("Name")
                ]

            shows_by_id[series_id] = TVShow(
                id=show_id,
                title=item.get("Name", ""),
                year=item.get("ProductionYear"),
                poster_url=f"{self.url.rstrip('/')}/Items/{series_id}/Images/Primary?API_KEY={self.token}",
                overview=item.get("Overview"),
                tagline=tagline,
                genres=genres,
                creators=creators,
                actors=actors[:5],  # Limit to top 5 actors
                first_air_date=item.get("PremiereDate"),
                rating=item.get("CommunityRating"),
                content_rating=item.get("OfficialRating"),
                studio=studio,
            )

            self.add_show_to_collection(show_id, shows_by_id[series_id])

        return shows_by_id

    def fetch_episodes(self, enabled_library_ids: List[str]) -> List[Dict]:
        """Fetch episodes from enabled libraries."""
        episode_items = []

        if not enabled_library_ids:
            return episode_items

        for library_id in enabled_library_ids:
            response = requests.get(
                f"{self.url}/Items",
                params={
                    "IncludeItemTypes": "Episode",
                    "Recursive": "true",
                    "Fields": "Path,SeriesName,SeasonName,ParentIndexNumber,IndexNumber,Year,Overview,PremiereDate",
                    "ParentId": library_id,
                },
                headers=self.get_headers(),
            )

            if response.status_code == 200:
                data = response.json()
                items = data.get("Items", [])
                episode_items.extend(items)
                logging.debug(f"Found {len(items)} episodes in library {library_id}")
            else:
                logging.error(
                    f"Failed to retrieve episodes from library {library_id}: HTTP {response.status_code}"
                )

        return episode_items

    def process_episodes(
        self, episode_items: List[Dict], shows_by_id: Dict[str, TVShow]
    ) -> List[Episode]:
        """Process episode items into Episode objects."""
        episodes = []

        self.stats["total_episodes_found"] = len(episode_items)

        for item in episode_items:
            if "Path" in item and "SeriesId" in item:
                media_id = str(uuid.uuid4())
                series_id = item["SeriesId"]

                # Apply path mapping to convert media server path to local path
                mapped_path = apply_path_mapping(item["Path"])

                # Only add if the path exists and series exists
                if (
                    not mapped_path
                    or not self.path_exists(mapped_path)
                    or series_id not in shows_by_id
                ):
                    logging.debug(
                        f"Episode path not found or series ID not found: {mapped_path}"
                    )
                    self.stats["path_not_found"] += 1
                    self.stats["skipped_episodes"] += 1
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
                    poster_url=f"{self.url.rstrip('/')}/Items/{item['Id']}/Images/Primary?API_KEY={self.token}",
                    # For episodes in Jellyfin, Primary also contains the landscape artwork
                    thumbnail_url=f"{self.url.rstrip('/')}/Items/{item['Id']}/Images/Primary?API_KEY={self.token}",
                    overview=item.get("Overview"),
                    air_date=item.get("PremiereDate"),
                )

                # Add to TV show
                show.add_episode(episode)

                # Add to collection
                episodes.append(episode)
                self.add_episode_to_collection(episode)

        return episodes

    def scan(self) -> List[MediaItem]:
        """Scan Jellyfin server for media."""
        self.media_items = []
        self.shows_by_id = {}

        # Clear existing data
        self.clear_existing_data()

        # Get enabled library IDs
        enabled_library_ids = self.get_enabled_library_ids()

        # Process movies
        movie_items = self.fetch_movies(enabled_library_ids)
        self.process_movies(movie_items)

        # Process TV series
        series_items = self.fetch_tv_series(enabled_library_ids)
        self.shows_by_id = self.process_tv_series(series_items)

        # Process episodes
        episode_items = self.fetch_episodes(enabled_library_ids)
        self.process_episodes(episode_items, self.shows_by_id)

        # Log statistics
        self.log_statistics()

        return self.media_items

    def get_libraries(self) -> List[Dict[str, Any]]:
        """
        Get list of libraries from Jellyfin.

        Returns:
            List of library dictionaries with id, name, and enabled status
        """
        libraries = []

        try:
            response = requests.get(
                f"{self.url}/Library/VirtualFolders", headers=self.get_headers()
            )
            if response.status_code == 200:
                libraries_data = response.json()

                for library in libraries_data:
                    library_id = library.get("ItemId")
                    library_name = library.get("Name", "Unknown")
                    library_type = library.get("CollectionType", "Unknown")

                    if library_id:
                        # Check if this library is enabled in our config
                        # Only True if explicitly set to True in config
                        enabled = (
                            self.config.enabled_libraries.get(library_id, True) is True
                        )

                        libraries.append(
                            {
                                "id": library_id,
                                "name": library_name,
                                "type": library_type,
                                "enabled": enabled,
                            }
                        )
            else:
                logging.error(
                    f"Failed to get Jellyfin libraries: {response.status_code}"
                )
        except Exception as e:
            logging.error(f"Error getting Jellyfin libraries: {str(e)}")

        return libraries


# Public module-level functions that use the scanner classes


def scan_jellyfin(url: str, api_key: str) -> List[MediaItem]:
    """Scan a Jellyfin server for media."""
    scanner = JellyfinScanner(url, api_key)
    return scanner.scan()


def scan_plex(url: str, token: str) -> List[MediaItem]:
    """Scan a Plex server for media."""
    scanner = PlexScanner(url, token)
    return scanner.scan()


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
        shows_with_episodes = [
            show
            for show in TV_SHOWS.values()
            if show.seasons and any(season.episodes for season in show.seasons.values())
        ]

    with MEDIA_LOCK:
        # Filter movies to only include those with a valid path (skipping os.path.exists check which is slow)
        valid_movies = [
            item for item in MEDIA.values() if isinstance(item, Movie) and item.path
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
        scanner = JellyfinScanner(url, api_key)
        scanner.scan()

        # Use the number of items actually added, not the total found/scanned
        item_count = scanner.get_added_item_count()

        # Update item count with thread safety
        with SCAN_STATUS_LOCK:
            SCAN_STATUS["item_count"] = item_count
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
        scanner = PlexScanner(url, token)
        scanner.scan()  # Actually run the scan

        # Use the number of items actually added, not the total found/scanned
        item_count = scanner.get_added_item_count()

        # Update item count with thread safety
        with SCAN_STATUS_LOCK:
            SCAN_STATUS["item_count"] = item_count
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
    scanner = JellyfinScanner(url, api_key)
    return scanner.get_libraries()


def get_plex_libraries(url: str, token: str) -> List[Dict[str, Any]]:
    """
    Get list of libraries from Plex.

    Args:
        url: Plex server URL
        token: Plex authentication token

    Returns:
        List of library dictionaries with id, name, and enabled status
    """
    scanner = PlexScanner(url, token)
    return scanner.get_libraries()
