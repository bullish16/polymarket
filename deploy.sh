#!/bin/bash
# =====================================================
# Polymarket Bot - VPS Deployment Script
# =====================================================
# Run this on your VPS to set up everything.
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh
# =====================================================

set -e

echo "🚀 Polymarket Bot Deployment"
echo "============================="

# 1. System deps
echo "📦 Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv screen

# 2. Create bot directory
BOT_DIR="$HOME/polymarket-bot"
mkdir -p "$BOT_DIR"
cd "$BOT_DIR"

echo "📁 Bot directory: $BOT_DIR"

# 3. Copy files (assumes files are already in this directory)
# If deploying from local, use: scp -r polymarket-bot/* user@vps:~/polymarket-bot/

# 4. Virtual environment
echo "🐍 Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

# 5. Check .env
if [ ! -f .env ]; then
    echo ""
    echo "⚠️  No .env file found!"
    echo "   1. Copy .env.example to .env"
    echo "   2. Fill in your PRIVATE_KEY and other settings"
    echo "   3. Run: python3 setup_creds.py"
    echo "   4. Then restart with: ./start.sh"
    cp .env.example .env
    echo ""
    echo "📝 .env.example copied to .env — edit it now!"
    exit 0
fi

echo "✅ Setup complete!"
echo ""
echo "Commands:"
echo "  ./start.sh          Start bot (live)"
echo "  ./start.sh --dry    Start bot (paper trading)"
echo "  ./stop.sh           Stop bot"
echo "  ./status.sh         Check bot status"
echo "  screen -r polybot   Attach to bot screen"
