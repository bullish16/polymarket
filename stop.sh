#!/bin/bash
# Stop all bot processes
echo "🛑 Stopping bot..."
screen -S polybot -X quit 2>/dev/null && echo "   Bot stopped" || echo "   Bot not running"
screen -S polyclaim -X quit 2>/dev/null && echo "   Claim stopped" || echo "   Claim not running"
echo "✅ Done"
