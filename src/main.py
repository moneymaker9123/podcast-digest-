#!/usr/bin/env python3
"""
Podcast Digest Agent — Daily podcast summarization and email delivery.

Usage:
    python -m src.main              # Run the daily digest
    python -m src.main --dry-run    # Run without sending email
    python -m src.main --lookback 48  # Look back 48 hours instead of 24
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .email_sender import send_digest_email
from .feed_parser import fetch_new_episodes
from .models import PodcastConfig, Summary
from .summarizer import summarize_episode
from .transcript import get_transcript

# Project root
PROJECT_DIR = Path(__file__).parent.parent
DATA_DIR = PROJECT_DIR / "data"
CONFIG_DIR = PROJECT_DIR / "config"

# Load .env from project root
load_dotenv(PROJECT_DIR / ".env")

logger = logging.getLogger("podcast_digest")


def main():
    args = parse_args()
    setup_logging(verbose=args.verbose)

    logger.info("=" * 50)
    logger.info(f"Podcast Digest — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    logger.info("=" * 50)

    # Load config
    podcasts, settings = load_config()
    if not podcasts:
        logger.error("No podcasts configured. Edit config/podcasts.yaml to add podcasts.")
        sys.exit(1)

    # Load API keys
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    gmail_address = os.getenv("GMAIL_ADDRESS")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")

    if not anthropic_key:
        logger.error("ANTHROPIC_API_KEY not set. Add it to .env file.")
        sys.exit(1)

    # Load history
    history = load_history()

    lookback = args.lookback or settings.get("lookback_hours", 24)
    model = settings.get("summarizer", {}).get("model", "claude-sonnet-4-5-20250929")

    # Process each podcast
    all_summaries: list[Summary] = []

    for podcast in podcasts:
        try:
            episodes = fetch_new_episodes(podcast, lookback_hours=lookback)

            for episode in episodes:
                # Skip already processed
                if episode.guid in history:
                    logger.info(f"  Skipping (already processed): {episode.title}")
                    continue

                # Get transcript
                transcript, source = get_transcript(episode, openai_key)
                if not transcript:
                    logger.warning(f"  No transcript available for: {episode.title}")
                    continue

                # Summarize
                summary_text = summarize_episode(
                    episode=episode,
                    transcript=transcript,
                    transcript_source=source,
                    api_key=anthropic_key,
                    model=model,
                )

                all_summaries.append(
                    Summary(
                        episode=episode,
                        content=summary_text,
                        transcript_source=source,
                    )
                )

                # Mark as processed
                history[episode.guid] = {
                    "title": episode.title,
                    "podcast": episode.podcast_name,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                }

        except Exception as e:
            logger.error(f"Error processing '{podcast.name}': {e}", exc_info=True)
            continue

    # Send email
    if all_summaries:
        logger.info(f"\n{'=' * 50}")
        logger.info(f"Generated {len(all_summaries)} summaries")

        if args.dry_run:
            logger.info("DRY RUN — not sending email. Summaries:")
            for s in all_summaries:
                print(f"\n--- {s.episode.podcast_name}: {s.episode.title} ---")
                print(s.content)
                print()
        else:
            if not gmail_address or not gmail_password:
                logger.error(
                    "Gmail credentials not set. Add GMAIL_ADDRESS and "
                    "GMAIL_APP_PASSWORD to .env file."
                )
            else:
                email_settings = settings.get("email", {})
                recipient = email_settings.get("recipient") or gmail_address
                subject_prefix = email_settings.get("subject_prefix", "Podcast Digest")

                send_digest_email(
                    summaries=all_summaries,
                    sender=gmail_address,
                    recipient=recipient,
                    app_password=gmail_password,
                    subject_prefix=subject_prefix,
                )

        # Save history after successful run
        save_history(history)
    else:
        logger.info("No new episodes found. Nothing to send.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Podcast Digest Agent")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without sending email (print summaries to stdout)",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=None,
        help="Hours to look back for new episodes (default: from settings.yaml)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_config() -> tuple[list[PodcastConfig], dict]:
    """Load podcast list and settings from YAML config files."""
    # Load podcasts
    podcasts_path = CONFIG_DIR / "podcasts.yaml"
    with open(podcasts_path) as f:
        podcasts_data = yaml.safe_load(f)

    podcasts = []
    for p in podcasts_data.get("podcasts") or []:
        if p and p.get("name") and p.get("rss_url"):
            podcasts.append(PodcastConfig(
                name=p["name"],
                rss_url=p["rss_url"],
                theme=p.get("theme", "General"),
            ))

    # Load settings
    settings_path = CONFIG_DIR / "settings.yaml"
    with open(settings_path) as f:
        settings = yaml.safe_load(f) or {}

    return podcasts, settings


def load_history() -> dict:
    """Load processed episode history."""
    history_path = DATA_DIR / "history.json"
    if history_path.exists():
        with open(history_path) as f:
            return json.load(f)
    return {}


def save_history(history: dict):
    """Save processed episode history."""
    history_path = DATA_DIR / "history.json"
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)
    logger.info(f"History saved ({len(history)} episodes tracked)")


if __name__ == "__main__":
    main()
