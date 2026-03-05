from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PodcastConfig:
    name: str
    rss_url: str
    theme: str = "General"


@dataclass
class Episode:
    podcast_name: str
    title: str
    guid: str
    published: datetime
    theme: str = "General"
    audio_url: str | None = None
    description: str = ""
    transcript_url: str | None = None
    guest_name: str | None = None


@dataclass
class Summary:
    episode: Episode
    content: str
    transcript_source: str  # "transcript", "show_notes", "whisper"
