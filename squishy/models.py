"""Data models for Squishy."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class Episode:
    """Represents a TV show episode."""
    
    id: str
    season_number: int
    episode_number: Optional[int] = None
    title: str = ""
    year: Optional[int] = None
    path: str = ""
    
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
class MediaItem:
    """Represents a media item (movie or TV show episode)."""
    
    id: str
    title: str
    year: Optional[int]
    type: str  # "movie" or "episode"
    path: str
    poster_url: Optional[str] = None
    # For TV show episodes
    show_id: Optional[str] = None
    season_number: Optional[int] = None
    episode_number: Optional[int] = None
    
    @property
    def display_name(self) -> str:
        """Get a display name for the media item."""
        if self.type == "movie" and self.year:
            return f"{self.title} ({self.year})"
        elif self.type == "episode" and self.season_number and self.episode_number:
            return f"S{self.season_number:02d}E{self.episode_number:02d} - {self.title}"
        return self.title

@dataclass
class TranscodeJob:
    """Represents a transcoding job."""
    
    id: str
    media_id: str
    profile_name: str
    status: str  # "pending", "processing", "completed", "failed"
    progress: float = 0.0
    output_path: Optional[str] = None
    error_message: Optional[str] = None
    
    @property
    def is_complete(self) -> bool:
        """Check if the job is complete."""
        return self.status == "completed"