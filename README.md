# Podcast Digest Agent

Daily podcast summarization agent. Pulls new episodes from RSS feeds, gets transcripts (published or via Whisper), summarizes with Claude, and emails you a formatted digest every morning.

## Quick Start

### 1. Install dependencies

```bash
cd ~/podcast-digest
pip install -r requirements.txt
```

You also need `ffmpeg` for audio processing (Whisper fallback):

```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

### 2. Configure API keys

```bash
cp .env.example .env
```

Edit `.env` with your keys:
- **ANTHROPIC_API_KEY** — Required. Get one at [console.anthropic.com](https://console.anthropic.com)
- **OPENAI_API_KEY** — Optional. Only needed if podcasts lack transcripts (Whisper fallback)
- **GMAIL_ADDRESS** — Your Gmail address
- **GMAIL_APP_PASSWORD** — Gmail app password ([generate here](https://myaccount.google.com/apppasswords), requires 2FA)

### 3. Add your podcasts

Edit `config/podcasts.yaml`:

```yaml
podcasts:
  - name: "All-In Podcast"
    rss_url: "https://feeds.megaphone.fm/all-in-with-chamath-jason-sacks-and-friedberg"

  - name: "Huberman Lab"
    rss_url: "https://feeds.megaphone.fm/hubermanlab"
```

To find RSS feeds: search `"<podcast name> RSS feed"` or use [podcastindex.org](https://podcastindex.org).

### 4. Set your email

Edit `config/settings.yaml` and fill in the `email.recipient` field.

### 5. Test it

```bash
# Dry run — fetches and summarizes but doesn't send email
python -m src.main --dry-run

# Look back further if no episodes in last 24h
python -m src.main --dry-run --lookback 72

# Full run with email
python -m src.main
```

### 6. Set up daily cron

```bash
bash setup_cron.sh
```

This installs a cron job that runs at 6:00 AM daily.

## How It Works

1. **Fetches RSS feeds** for each podcast in your config
2. **Filters** for episodes published in the last 24 hours
3. **Gets transcripts** — checks for published transcripts first, falls back to OpenAI Whisper
4. **Summarizes** each episode using Claude with a structured prompt template
5. **Sends an HTML email** with all summaries via Gmail SMTP
6. **Tracks history** so episodes are never processed twice

## Project Structure

```
config/
  podcasts.yaml       # Your podcast list
  settings.yaml       # Email, model, and other settings
src/
  main.py             # Entry point
  feed_parser.py      # RSS feed fetching & filtering
  transcript.py       # Transcript extraction (RSS/Whisper)
  summarizer.py       # Claude API summarization
  email_sender.py     # Gmail SMTP delivery
  models.py           # Data models
prompts/
  summary_prompt.txt  # Customizable summary template
templates/
  email_template.html # Email HTML template
data/
  history.json        # Processed episode tracking
```

## Customization

- **Summary format**: Edit `prompts/summary_prompt.txt` to change the summary structure
- **Email template**: Edit `templates/email_template.html` to change the email design
- **Schedule**: Edit the cron time in `setup_cron.sh` or run `crontab -e`
- **Lookback window**: Change `lookback_hours` in `config/settings.yaml`

## Cost Estimates

- **Claude API**: ~$0.01–0.05 per episode summary
- **Whisper API**: ~$0.36 per hour of audio (only for episodes without transcripts)
- **Typical day** (5–10 episodes): ~$1–4
