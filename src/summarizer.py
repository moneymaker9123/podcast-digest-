import logging
from pathlib import Path

import anthropic

from .models import Episode

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Rough estimate: 1 token ≈ 4 chars
MAX_CONTENT_CHARS = 400_000  # ~100K tokens


def summarize_episode(
    episode: Episode,
    transcript: str,
    transcript_source: str,
    api_key: str,
    model: str = "claude-sonnet-4-5-20250929",
) -> str:
    """Summarize a podcast episode using Claude API."""
    prompt_template = _load_prompt_template()

    guest_str = episode.guest_name or "N/A"
    content = transcript

    # Add a note about the content source
    source_note = ""
    if transcript_source == "show_notes":
        source_note = (
            "\n[NOTE: This content is from show notes, not a full transcript. "
            "The summary may be less detailed than usual.]\n"
        )
    elif transcript_source == "whisper":
        source_note = (
            "\n[NOTE: This transcript was auto-generated via speech-to-text "
            "and may contain minor errors.]\n"
        )

    # Handle very long transcripts by chunking
    if len(content) > MAX_CONTENT_CHARS:
        logger.info(
            f"  Transcript too long ({len(content)} chars), using progressive summarization"
        )
        content = _progressive_summarize(content, episode, api_key, model)

    prompt = prompt_template.format(
        podcast_name=episode.podcast_name,
        episode_title=episode.title,
        guest_name=guest_str,
        content=source_note + content,
    )

    logger.info(f"  Summarizing '{episode.title}' with {model}...")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    summary = response.content[0].text
    logger.info(f"  Summary generated ({len(summary)} chars)")
    return summary


def _load_prompt_template() -> str:
    """Load the summary prompt template from file."""
    prompt_path = PROMPTS_DIR / "summary_prompt.txt"
    return prompt_path.read_text()


def _progressive_summarize(
    content: str, episode: Episode, api_key: str, model: str
) -> str:
    """Summarize a very long transcript by chunking and then combining."""
    client = anthropic.Anthropic(api_key=api_key)

    # Split into chunks of roughly 300K chars (~75K tokens) with overlap
    chunk_size = 300_000
    overlap = 5_000
    chunks = []
    start = 0
    while start < len(content):
        end = start + chunk_size
        chunks.append(content[start:end])
        start = end - overlap

    logger.info(f"  Split into {len(chunks)} chunks for progressive summarization")

    chunk_summaries = []
    for i, chunk in enumerate(chunks):
        logger.info(f"  Summarizing chunk {i + 1}/{len(chunks)}...")
        response = client.messages.create(
            model=model,
            max_tokens=1500,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"This is part {i + 1} of {len(chunks)} of a podcast transcript "
                        f"from '{episode.podcast_name}' - '{episode.title}'.\n\n"
                        f"Summarize the key points, arguments, data, and insights "
                        f"from this section. Be thorough but concise.\n\n"
                        f"Transcript section:\n{chunk}"
                    ),
                }
            ],
        )
        chunk_summaries.append(response.content[0].text)

    # Combine chunk summaries
    combined = "\n\n---\n\n".join(
        f"[Section {i + 1}]\n{s}" for i, s in enumerate(chunk_summaries)
    )

    return combined
