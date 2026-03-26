#!/bin/bash
# Start the bot in a screen session
cd "$(dirname "$0")"
source venv/bin/activate

MODE=""
if [ "$1" = "--dry" ]; then
    MODE="--dry-run"
    echo "🧪 Starting in DRY RUN mode..."
else
    echo "💰 Starting in LIVE mode..."
    echo "⚠️  Real money will be used! Press Ctrl+C within 5s to cancel."
    sleep 5
fi

# Kill existing sessions
screen -S polybot -X quit 2>/dev/null || true
screen -S polyclaim -X quit 2>/dev/null || true

# Start bot
screen -dmS polybot bash -c "source venv/bin/activate && python3 bot.py $MODE 2>&1 | tee -a bot.log"
echo "✅ Bot started in screen 'polybot'"

# Start auto-claim (only in live mode)
if [ -z "$MODE" ]; then
    screen -dmS polyclaim bash -c "source venv/bin/activate && python3 auto_claim.py 2>&1 | tee -a claim.log"
    echo "✅ Auto-claim started in screen 'polyclaim'"
fi

echo ""
echo "📋 Commands:"
echo "  screen -r polybot    View bot output"
echo "  screen -r polyclaim  View claim output"
echo "  ./stop.sh            Stop everything"
echo "  tail -f bot.log      Follow bot log"
