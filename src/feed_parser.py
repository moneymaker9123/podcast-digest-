import logging
import re
from datetime import datetime, timezone, timedelta
from time import mktime

import feedparser
import requests

from .models import Episode, PodcastConfig

logger = logging.getLogger(__name__)


def _sanitize_xml(content: str) -> str:
    """Fix common XML issues like unescaped ampersands."""
    return re.sub(r'&(?!(?:[a-zA-Z][a-zA-Z0-9]*|#[0-9]+|#x[0-9a-fA-F]+);)', '&amp;', content)


def fetch_new_episodes(
    podcast: PodcastConfig, lookback_hours: int = 24
) -> list[Episode]:
    """Fetch episodes published within the lookback window from an RSS feed."""
    logger.info(f"Fetching feed for '{podcast.name}': {podcast.rss_url}")

    feed = feedparser.parse(podcast.rss_url)

    if feed.bozo and not feed.entries:
        logger.warning(f"  Feed parse failed, retrying with XML sanitization: {feed.bozo_exception}")
        try:
            resp = requests.get(
                podcast.rss_url,
                timeout=15,
                headers={"User-Agent": "python-feedparser/6.0 +https://github.com/kurtmckee/feedparser"},
                allow_redirects=True,
            )
            resp.raise_for_status()
            sanitized = _sanitize_xml(resp.text)
            feed = feedparser.parse(sanitized)
        except Exception as e:
            logger.error(f"Failed to fetch/sanitize feed for '{podcast.name}': {e}")

    if feed.bozo and not feed.entries:
        logger.error(
            f"Failed to parse feed for '{podcast.name}': {feed.bozo_exception}"
        )
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    episodes = []

    for entry in feed.entries:
        published = _parse_publish_date(entry)
        if published is None:
            logger.debug(f"Skipping entry with no date: {entry.get('title', '?')}")
            continue

        if published < cutoff:
            continue

        episode = Episode(
            podcast_name=podcast.name,
            title=entry.get("title", "Untitled"),
            guid=entry.get("id", entry.get("link", entry.get("title", ""))),
            published=published,
            theme=podcast.theme,
            audio_url=_extract_audio_url(entry),
            description=_clean_html(entry.get("summary", "")),
            transcript_url=_extract_transcript_url(entry),
            guest_name=_extract_guest(entry),
        )
        episodes.append(episode)
        logger.info(f"  Found new episode: {episode.title}")

    if not episodes:
        logger.info(f"  No new episodes for '{podcast.name}' in last {lookback_hours}h")

    return episodes


def _parse_publish_date(entry) -> datetime | None:
    """Parse the published date from a feed entry."""
    for date_field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(date_field)
        if parsed:
            return datetime.fromtimestamp(mktime(parsed), tz=timezone.utc)
    return None


def _extract_audio_url(entry) -> str | None:
    """Extract the audio file URL from feed enclosures."""
    for enclosure in entry.get("enclosures", []):
        mime = enclosure.get("type", "")
        if mime.startswith("audio/"):
            return enclosure.get("href")
    # Fallback: check links
    for link in entry.get("links", []):
        if link.get("type", "").startswith("audio/"):
            return link.get("href")
    return None


def _extract_transcript_url(entry) -> str | None:
    """Extract transcript URL from Podcasting 2.0 transcript tag or other sources."""
    # Check for podcast:transcript tag (Podcasting 2.0 namespace)
    for tag_key in ("podcast_transcript", "transcript"):
        transcript = entry.get(tag_key)
        if transcript:
            if isinstance(transcript, list):
                for t in transcript:
                    url = t.get("url") or t.get("href")
                    if url:
                        return url
            elif isinstance(transcript, dict):
                return transcript.get("url") or transcript.get("href")
            elif isinstance(transcript, str):
                return transcript

    # Check content links for transcript references
    for link in entry.get("links", []):
        rel = link.get("rel", "")
        href = link.get("href", "")
        if "transcript" in rel.lower() or "transcript" in href.lower():
            return href

    return None


def _extract_guest(entry) -> str | None:
    """Try to extract guest name from episode title or itunes author."""
    title = entry.get("title", "")

    # Common patterns for guest extraction from titles
    patterns = [
        # "#491 – Topic – Peter Steinberger" — proper name at end after last dash
        r"[-–—]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s*$",
        # "#492 – Rick Beato: Topic" — proper name before colon
        r"#\d+\s*[-–—]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s*:",
        # "Episode Title with Guest Name"
        r"(?:with|w/|ft\.?|feat\.?|featuring)\s+(.+?)(?:\s*[-–—|:]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            guest = match.group(1).strip()
            # Filter out likely non-guest matches
            if len(guest) > 3 and not re.match(r"^(ep\.?|episode|#)\s*\d+", guest, re.IGNORECASE):
                return guest

    return None


def _clean_html(text: str) -> str:
    """Remove HTML tags from text."""
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()
