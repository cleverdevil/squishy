"""Data models for Squishy."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class MediaItem:
    """Base class for video media items (movies and TV episodes)."""

    id: str
    title: str
    path: str
    year: Optional[int] = None
    poster_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    overview: Optional[str] = None
    tagline: Optional[str] = None
    genres: List[str] = field(default_factory=list)
    actors: List[str] = field(default_factory=list)
    rating: Optional[float] = None
    content_rating: Optional[str] = None
    studio: Optional[str] = None

    @property
    def display_name(self) -> str:
        """Get a display name for the media item."""
        if self.year:
            return f"{self.title} ({self.year})"
        return self.title


@dataclass(kw_only=True)
class Movie(MediaItem):
    """Represents a movie."""

    directors: List[str] = field(default_factory=list)
    release_date: Optional[str] = None

    @property
    def type(self) -> str:
        """Get the media type."""
        return "movie"


@dataclass(kw_only=True)
class Episode(MediaItem):
    """Represents a TV show episode."""
    
    season_number: int
    show_id: str
    episode_number: Optional[int] = None
    air_date: Optional[str] = None
    
    @property
    def type(self) -> str:
        """Get the media type."""
        return "episode"
    
    @property
    def display_name(self) -> str:
        """Get a display name for the episode."""
        if self.episode_number:
            return f"S{self.season_number:02d}E{self.episode_number:02d} - {self.title}"
        return self.title


@dataclass
class Season:
    """Represents a TV show season."""

    number: int
    episodes: Dict[int, Episode] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """Get a display name for the season."""
        return f"Season {self.number}"

    @property
    def sorted_episodes(self) -> List[Episode]:
        """Get episodes sorted by episode number."""
        return sorted(self.episodes.values(), key=lambda e: e.episode_number or 0)


@dataclass
class TVShow:
    """Represents a TV show."""

    id: str
    title: str
    year: Optional[int] = None
    poster_url: Optional[str] = None
    seasons: Dict[int, Season] = field(default_factory=dict)
    # Extended metadata
    overview: Optional[str] = None
    tagline: Optional[str] = None
    genres: List[str] = field(default_factory=list)
    creators: List[str] = field(default_factory=list)
    actors: List[str] = field(default_factory=list)
    first_air_date: Optional[str] = None
    rating: Optional[float] = None
    content_rating: Optional[str] = None
    studio: Optional[str] = None

    @property
    def display_name(self) -> str:
        """Get a display name for the TV show."""
        if self.year:
            return f"{self.title} ({self.year})"
        return self.title

    @property
    def sorted_seasons(self) -> List[Season]:
        """Get seasons sorted by season number."""
        return sorted(self.seasons.values(), key=lambda s: s.number)

    def add_episode(self, episode: Episode) -> None:
        """Add an episode to the show."""
        season_num = episode.season_number
        if season_num not in self.seasons:
            self.seasons[season_num] = Season(number=season_num)

        self.seasons[season_num].episodes[episode.episode_number or 0] = episode


@dataclass
class TranscodeJob:
    """Represents a transcoding job."""

    id: str
    media_id: str
    preset_name: str
    status: str  # "pending", "processing", "completed", "failed", "cancelled"
    progress: float = 0.0
    output_path: Optional[str] = None
    error_message: Optional[str] = None
    output_size: Optional[str] = None
    duration: Optional[float] = None
    current_time: Optional[float] = None
    process_id: Optional[int] = None  # Store process ID for cancellation
    ffmpeg_command: Optional[str] = None  # Store the FFmpeg command for reference
    ffmpeg_logs: List[str] = field(default_factory=list)  # Store FFmpeg logs
    
    def __post_init__(self):
        """Initialize a lock for thread-safe attribute updates."""
        import threading
        self._lock = threading.RLock()
    
    def update_progress(self, current_time: float):
        """Thread-safe update of progress."""
        with self._lock:
            self.current_time = current_time
            if self.duration:
                self.progress = min(current_time / self.duration, 0.99)
                
    def update_status(self, status: str):
        """Thread-safe update of job status."""
        with self._lock:
            self.status = status
            
    def update_output_size(self, size: str):
        """Thread-safe update of output size."""
        with self._lock:
            self.output_size = size
            
    def update_logs(self, logs: List[str]):
        """Thread-safe update of logs."""
        with self._lock:
            self.ffmpeg_logs = logs

    @property
    def is_complete(self) -> bool:
        """Check if the job is complete."""
        with self._lock:
            return self.status == "completed"

    @property
    def is_active(self) -> bool:
        """Check if the job is active (pending or processing)."""
        with self._lock:
            return self.status in ("pending", "processing")
