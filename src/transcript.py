import logging
import os
import re
import tempfile

import requests

from .models import Episode

logger = logging.getLogger(__name__)

# Whisper API limit per request
MAX_AUDIO_SIZE_BYTES = 25 * 1024 * 1024  # 25MB


def get_transcript(episode: Episode, openai_api_key: str | None = None) -> tuple[str, str]:
    """
    Get transcript for an episode. Tries in order:
    1. Published transcript from RSS feed
    2. Show notes (if substantial)
    3. Whisper API transcription

    Returns (transcript_text, source) where source is one of:
    "transcript", "show_notes", "whisper"
    """
    # Path A: Published transcript from RSS feed tag
    if episode.transcript_url:
        logger.info(f"  Fetching published transcript: {episode.transcript_url}")
        text = _fetch_published_transcript(episode.transcript_url)
        if text and len(text.split()) > 100:
            return text, "transcript"
        logger.warning("  Published transcript was empty or too short, trying fallbacks")

    # Path A2: Scan show notes for transcript links
    if episode.description:
        transcript_url = _find_transcript_url_in_text(episode.description)
        if transcript_url:
            logger.info(f"  Found transcript link in show notes: {transcript_url}")
            text = _fetch_web_transcript(transcript_url)
            if text and len(text.split()) > 100:
                return text, "transcript"
            logger.warning("  Web transcript was empty or too short")

    # Path B: Show notes (if substantial enough)
    if episode.description:
        word_count = len(episode.description.split())
        if word_count >= 500:
            logger.info(f"  Using show notes as content ({word_count} words)")
            return episode.description, "show_notes"

    # Path C: Whisper API (disabled — too slow/expensive, revisit later)
    # if episode.audio_url and openai_api_key:
    #     logger.info(f"  Transcribing with Whisper: {episode.audio_url}")
    #     text = _transcribe_with_whisper(episode.audio_url, openai_api_key)
    #     if text:
    #         return text, "whisper"
    #     logger.error("  Whisper transcription failed")
    # elif not episode.audio_url:
    #     logger.warning("  No audio URL available for Whisper fallback")
    # elif not openai_api_key:
    #     logger.warning("  No OpenAI API key — cannot use Whisper fallback")

    # Last resort: use whatever description we have
    if episode.description:
        logger.warning("  Falling back to short show notes")
        return episode.description, "show_notes"

    return "", "none"


def _find_transcript_url_in_text(text: str) -> str | None:
    """Scan text for URLs that look like transcript links."""
    # Match URLs containing "transcript" in the path
    urls = re.findall(r'https?://[^\s<>"\']+transcript[^\s<>"\']*', text, re.IGNORECASE)
    if urls:
        # Clean trailing punctuation
        url = urls[0].rstrip(".,;:)")
        return url
    return None


def _fetch_web_transcript(url: str) -> str | None:
    """Fetch a transcript from a web page, extracting text content."""
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "PodcastDigest/1.0"})
        resp.raise_for_status()
        content = resp.text

        # If it's HTML, try to extract the main text
        if "<html" in content.lower() or "<body" in content.lower():
            return _extract_text_from_html(content)

        return content.strip()
    except requests.RequestException as e:
        logger.error(f"  Failed to fetch web transcript: {e}")
        return None


def _extract_text_from_html(html: str) -> str:
    """Extract readable text from HTML, focusing on transcript content."""
    # Remove script and style tags entirely
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<header[^>]*>.*?</header>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # Convert <p>, <br>, <div> to newlines
    text = re.sub(r"<(?:p|br|div)[^>]*>", "\n", text, flags=re.IGNORECASE)

    # Strip remaining tags
    text = re.sub(r"<[^>]+>", " ", text)

    # Decode HTML entities
    import html
    text = html.unescape(text)

    # Clean up whitespace
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines)


def _fetch_published_transcript(url: str) -> str | None:
    """Fetch and parse a published transcript (plain text, SRT, or VTT)."""
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        content = resp.text

        # Detect and parse SRT/VTT format
        if _is_srt_or_vtt(content):
            return _parse_subtitle_format(content)

        return content.strip()
    except requests.RequestException as e:
        logger.error(f"  Failed to fetch transcript: {e}")
        return None


def _is_srt_or_vtt(text: str) -> bool:
    """Check if text looks like SRT or VTT subtitle format."""
    lines = text.strip().split("\n")[:5]
    for line in lines:
        if line.strip().startswith("WEBVTT") or re.match(r"\d+:\d+:\d+", line.strip()):
            return True
    return False


def _parse_subtitle_format(text: str) -> str:
    """Extract plain text from SRT/VTT subtitle format."""
    lines = text.strip().split("\n")
    content_lines = []
    for line in lines:
        line = line.strip()
        # Skip timestamps, sequence numbers, WEBVTT header, and empty lines
        if not line:
            continue
        if line.startswith("WEBVTT"):
            continue
        if re.match(r"^\d+$", line):
            continue
        if re.match(r"\d{2}:\d{2}", line):
            continue
        if "-->" in line:
            continue
        # Strip HTML-like tags from subtitle text
        line = re.sub(r"<[^>]+>", "", line)
        content_lines.append(line)
    return " ".join(content_lines)


def _transcribe_with_whisper(audio_url: str, api_key: str) -> str | None:
    """Download audio and transcribe with OpenAI Whisper API."""
    try:
        # Download audio to temp file
        logger.info("  Downloading audio file...")
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name
            resp = requests.get(audio_url, stream=True, timeout=60)
            resp.raise_for_status()
            total_size = 0
            for chunk in resp.iter_content(chunk_size=8192):
                tmp.write(chunk)
                total_size += len(chunk)
            logger.info(f"  Downloaded {total_size / 1024 / 1024:.1f}MB")

        # If file is small enough, transcribe directly
        if total_size <= MAX_AUDIO_SIZE_BYTES:
            return _whisper_api_call(tmp_path, api_key)

        # File too large — need to split with pydub
        logger.info("  Audio too large, splitting into chunks...")
        return _transcribe_chunked(tmp_path, api_key)

    except requests.RequestException as e:
        logger.error(f"  Failed to download audio: {e}")
        return None
    except Exception as e:
        logger.error(f"  Whisper transcription error: {e}")
        return None
    finally:
        # Clean up temp file
        if "tmp_path" in locals() and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _whisper_api_call(file_path: str, api_key: str) -> str | None:
    """Call OpenAI Whisper API with a single audio file."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    with open(file_path, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="text",
        )

    return response if isinstance(response, str) else str(response)


def _transcribe_chunked(file_path: str, api_key: str) -> str | None:
    """Split a large audio file and transcribe each chunk."""
    from pydub import AudioSegment

    audio = AudioSegment.from_file(file_path)

    # Split into 20-minute chunks (well under 25MB for most formats)
    chunk_length_ms = 20 * 60 * 1000
    chunks = [audio[i : i + chunk_length_ms] for i in range(0, len(audio), chunk_length_ms)]

    transcripts = []
    for i, chunk in enumerate(chunks):
        logger.info(f"  Transcribing chunk {i + 1}/{len(chunks)}...")
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            chunk_path = tmp.name
            chunk.export(chunk_path, format="mp3")

        try:
            text = _whisper_api_call(chunk_path, api_key)
            if text:
                transcripts.append(text)
        finally:
            if os.path.exists(chunk_path):
                os.unlink(chunk_path)

    return " ".join(transcripts) if transcripts else None
