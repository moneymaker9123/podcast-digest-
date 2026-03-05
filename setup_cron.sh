#!/bin/bash
# Setup cron job for daily podcast digest
# Usage: bash setup_cron.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/venv/bin/python"

echo "Podcast Digest — Cron Setup"
echo "==========================="
echo ""
echo "Project directory: $SCRIPT_DIR"
echo "Python: $PYTHON"
echo ""

# Check dependencies
echo "Checking dependencies..."
cd "$SCRIPT_DIR"
$PYTHON -c "import feedparser, requests, anthropic, jinja2, yaml, dotenv" 2>/dev/null || {
    echo "ERROR: Missing Python dependencies. Run:"
    echo "  pip install -r requirements.txt"
    exit 1
}
echo "  Dependencies OK"

# Check .env
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo ""
    echo "WARNING: No .env file found. Copy the example and fill in your keys:"
    echo "  cp .env.example .env"
    echo "  nano .env"
    echo ""
fi

# Create logs dir
mkdir -p "$SCRIPT_DIR/logs"

# Build cron entry (6:00 AM local time, every day)
CRON_CMD="0 6 * * * cd $SCRIPT_DIR && $PYTHON -m src.main >> $SCRIPT_DIR/logs/digest.log 2>&1"

echo ""
echo "Cron entry to install:"
echo "  $CRON_CMD"
echo ""

read -p "Install this cron job? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Add cron job (avoid duplicates)
    (crontab -l 2>/dev/null | grep -v "podcast-digest" ; echo "$CRON_CMD") | crontab -
    echo "Cron job installed! The digest will run daily at 6:00 AM."
    echo ""
    echo "To verify: crontab -l"
    echo "To remove: crontab -l | grep -v podcast-digest | crontab -"
    echo "Logs: $SCRIPT_DIR/logs/digest.log"
else
    echo "Skipped. You can manually add this line to your crontab (crontab -e):"
    echo "  $CRON_CMD"
fi
