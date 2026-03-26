#!/bin/bash
# Check bot status
echo "📊 Bot Status"
echo "============="

if screen -list | grep -q polybot; then
    echo "🤖 Bot: RUNNING"
    echo "   Last log:"
    tail -3 bot.log 2>/dev/null || echo "   (no log yet)"
else
    echo "🤖 Bot: STOPPED"
fi

echo ""

if screen -list | grep -q polyclaim; then
    echo "💰 Claim: RUNNING"
    echo "   Last log:"
    tail -3 claim.log 2>/dev/null || echo "   (no log yet)"
else
    echo "💰 Claim: STOPPED"
fi
