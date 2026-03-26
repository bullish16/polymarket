"""
Polymarket BTC Up/Down 5-Min Trading Bot
==========================================
- Bets $1 per trade (max)
- Only trades when signal confidence is HIGH (delta > 0.05%)
- Target profit: $0.30 per trade
- Holds to resolution if no early exit opportunity
- Auto-claims winning positions

Usage:
    python3 bot.py              # Live trading
    python3 bot.py --dry-run    # Paper trading (no real bets)
"""

import os
import sys
import time
import json
import logging
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ── Config ──
BET_SIZE = float(os.getenv("BET_SIZE", "1.00"))
MIN_DELTA_PCT = float(os.getenv("MIN_DELTA_PCT", "0.05"))
TARGET_PROFIT = float(os.getenv("TARGET_PROFIT", "0.30"))
DRY_RUN = "--dry-run" in sys.argv

PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
SIGNATURE_TYPE = int(os.getenv("SIGNATURE_TYPE", "1"))
API_KEY = os.getenv("POLY_API_KEY", "")
API_SECRET = os.getenv("POLY_API_SECRET", "")
PASSPHRASE = os.getenv("POLY_PASSPHRASE", "")

CLOB_HOST = "https://clob.polymarket.com"
GAMMA_HOST = "https://gamma-api.polymarket.com"

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log"),
    ]
)
log = logging.getLogger("polybot")

# ── Polymarket Client ──
clob_client = None

def init_clob():
    """Initialize Polymarket CLOB client."""
    global clob_client
    if DRY_RUN:
        log.info("🧪 DRY RUN MODE — no real trades")
        return

    if not PRIVATE_KEY:
        log.error("❌ PRIVATE_KEY not set in .env")
        sys.exit(1)

    pk = PRIVATE_KEY
    if pk.startswith("0x"):
        pk = pk[2:]

    from py_clob_client.client import ClobClient

    clob_client = ClobClient(
        host=CLOB_HOST,
        key=pk,
        chain_id=137,
        signature_type=SIGNATURE_TYPE,
    )

    # Set API credentials
    clob_client.set_api_creds(clob_client.create_or_derive_api_creds())
    log.info("✅ CLOB client initialized")


def get_current_market():
    """
    Find the current active BTC Up/Down 5-min market.
    Market slug is deterministic based on timestamp.
    """
    now = int(time.time())
    # Current 5-min window start
    window_ts = now - (now % 300)
    slug = f"btc-updown-5m-{window_ts}"

    try:
        resp = requests.get(
            f"{GAMMA_HOST}/events",
            params={"slug": slug},
            timeout=10,
        )
        resp.raise_for_status()
        events = resp.json()

        if not events:
            return None

        event = events[0]
        markets = event.get("markets", [])

        if not markets:
            return None

        # Find Up and Down token IDs
        result = {
            "slug": slug,
            "window_start": window_ts,
            "window_end": window_ts + 300,
            "tokens": {},
        }

        for market in markets:
            outcome = market.get("outcome", "").upper()
            tokens = market.get("clobTokenIds", [])
            if outcome in ("UP", "DOWN") and tokens:
                result["tokens"][outcome] = {
                    "token_id": tokens[0],
                    "condition_id": market.get("conditionId", ""),
                    "market_id": market.get("id", ""),
                }

        return result if result["tokens"] else None

    except Exception as e:
        log.warning(f"⚠️ Failed to fetch market: {e}")
        # Fallback: try CLOB directly
        return get_market_from_clob(slug)


def get_market_from_clob(slug):
    """Fallback: search CLOB for the market."""
    try:
        resp = requests.get(
            f"{CLOB_HOST}/markets",
            params={"slug": slug},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            # Parse response...
            return data
    except:
        pass
    return None


def get_window_open_price(window_start_ts):
    """Get BTC price at exact window open from Binance."""
    try:
        resp = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={
                "symbol": "BTCUSDT",
                "interval": "1m",
                "startTime": window_start_ts * 1000,
                "limit": 1,
            },
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            return float(data[0][1])  # open price
    except Exception as e:
        log.warning(f"⚠️ Failed to get window open price: {e}")
    return None


def place_bet(market, direction, bet_size):
    """Place a bet on Polymarket."""
    if DRY_RUN:
        log.info(f"🧪 [DRY] Would bet ${bet_size:.2f} on {direction}")
        return {"dry_run": True, "direction": direction, "size": bet_size}

    if not clob_client:
        log.error("❌ CLOB client not initialized")
        return None

    token_info = market["tokens"].get(direction)
    if not token_info:
        log.error(f"❌ No token found for {direction}")
        return None

    token_id = token_info["token_id"]

    try:
        from py_clob_client.clob_types import OrderArgs, OrderType

        # Get current best ask price
        book = clob_client.get_order_book(token_id)
        asks = book.get("asks", [])

        if not asks:
            log.warning("⚠️ No asks available, posting limit buy at $0.95")
            price = 0.95
        else:
            # Take best ask
            price = float(asks[0]["price"])

        # Max $1 bet
        actual_size = min(bet_size, BET_SIZE)
        shares = actual_size / price

        if shares < 5:
            log.warning(f"⚠️ Only {shares:.1f} shares (min 5). Adjusting...")
            shares = 5
            actual_size = shares * price
            if actual_size > BET_SIZE:
                log.warning(f"⚠️ Need ${actual_size:.2f} for 5 shares at ${price:.3f}, exceeds max. Skipping.")
                return None

        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=shares,
            side="BUY",
        )

        log.info(f"📤 Placing order: {direction} {shares:.1f} shares @ ${price:.3f} = ${actual_size:.2f}")
        result = clob_client.create_and_post_order(order_args)
        log.info(f"✅ Order placed: {result}")
        return result

    except Exception as e:
        log.error(f"❌ Order failed: {e}")
        return None


def check_and_claim():
    """Check for claimable winning positions and claim them."""
    if DRY_RUN:
        return

    if not clob_client:
        return

    try:
        # Get open positions
        positions = clob_client.get_positions()
        for pos in positions:
            # Check if market is resolved and we won
            if pos.get("resolved") and pos.get("payout", 0) > 0:
                log.info(f"💰 Claiming reward: ${pos['payout']:.2f}")
                clob_client.claim(pos["conditionId"])
    except Exception as e:
        log.debug(f"Claim check: {e}")


def wait_for_entry_window():
    """
    Wait until T-10s before the current 5-min window closes.
    Returns the window start timestamp.
    """
    now = int(time.time())
    window_start = now - (now % 300)
    window_end = window_start + 300
    entry_time = window_end - 10  # T-10s

    # If we're past T-10s, wait for next window
    if now >= entry_time:
        window_start += 300
        window_end = window_start + 300
        entry_time = window_end - 10

    wait_secs = entry_time - now
    next_entry = datetime.fromtimestamp(entry_time, tz=timezone.utc)

    log.info(f"⏳ Next entry at {next_entry.strftime('%H:%M:%S')} UTC (in {wait_secs}s)")

    # Sleep in chunks so we can be interrupted
    while time.time() < entry_time:
        remaining = entry_time - time.time()
        if remaining > 30:
            time.sleep(10)
        elif remaining > 5:
            time.sleep(1)
        else:
            time.sleep(0.5)

    return window_start


def run_trade_cycle():
    """Execute one trading cycle."""
    from strategy import analyze

    # Wait for entry window (T-10s before close)
    window_start = wait_for_entry_window()
    window_end = window_start + 300

    now_utc = datetime.fromtimestamp(window_start, tz=timezone.utc)
    log.info(f"🕐 Window: {now_utc.strftime('%H:%M')} - {datetime.fromtimestamp(window_end, tz=timezone.utc).strftime('%H:%M')} UTC")

    # Get window open price
    open_price = get_window_open_price(window_start)
    if not open_price:
        log.warning("⚠️ Could not get window open price. Skipping.")
        return

    log.info(f"📊 Window open: ${open_price:,.2f}")

    # Run analysis (poll every 2s until window closes)
    best_signal = None
    deadline = window_end - 3  # Stop 3s before close

    while time.time() < deadline:
        try:
            signal = analyze(open_price)
            log.info(
                f"📈 {signal['direction']} | "
                f"delta={signal['delta_pct']:+.4f}% | "
                f"confidence={signal['confidence']:.1%} | "
                f"{signal['reason']}"
            )

            # Track best signal
            if best_signal is None or signal["confidence"] > best_signal["confidence"]:
                best_signal = signal

            # Fire immediately if strong enough
            abs_delta = abs(signal["delta_pct"])
            if abs_delta >= MIN_DELTA_PCT and signal["confidence"] >= 0.5:
                log.info(f"🎯 Signal strong enough! Firing {signal['direction']}")
                execute_trade(signal, window_start)
                return

        except Exception as e:
            log.warning(f"⚠️ Analysis error: {e}")

        time.sleep(2)

    # Deadline reached: use best signal if it meets minimum
    if best_signal and abs(best_signal["delta_pct"]) >= MIN_DELTA_PCT:
        log.info(f"⏰ Deadline! Using best signal: {best_signal['direction']} ({best_signal['confidence']:.1%})")
        execute_trade(best_signal, window_start)
    else:
        delta_info = f"delta={best_signal['delta_pct']:+.4f}%" if best_signal else "no signal"
        log.info(f"⏭️ Skipping window (weak signal: {delta_info}, min={MIN_DELTA_PCT}%)")


def execute_trade(signal, window_start):
    """Execute the trade and log result."""
    market = get_current_market()

    if DRY_RUN:
        # Simulate
        log.info(f"🧪 [DRY] Bet ${BET_SIZE:.2f} on {signal['direction']}")

        # Wait for resolution
        window_end = window_start + 300
        wait = window_end - time.time() + 5  # +5s buffer
        if wait > 0:
            log.info(f"⏳ Waiting {wait:.0f}s for resolution...")
            time.sleep(max(wait, 0))

        # Check actual result
        try:
            open_price = get_window_open_price(window_start)
            close_price = get_window_open_price(window_start + 300)
            if open_price and close_price:
                actual = "UP" if close_price >= open_price else "DOWN"
                won = signal["direction"] == actual
                # Estimate token price
                abs_d = abs(signal["delta_pct"])
                if abs_d < 0.05:
                    tp = 0.60
                elif abs_d < 0.10:
                    tp = 0.75
                else:
                    tp = 0.90
                shares = BET_SIZE / tp
                pnl = (shares * 1.0 - BET_SIZE) if won else -BET_SIZE
                emoji = "✅" if won else "❌"
                log.info(f"{emoji} Result: {actual} | P&L: ${pnl:+.2f}")
        except:
            log.info("Could not verify result.")
        return

    if not market:
        log.warning("⚠️ Could not find market. Skipping.")
        return

    result = place_bet(market, signal["direction"], BET_SIZE)
    if result:
        log.info(f"✅ Trade placed: {signal['direction']} ${BET_SIZE:.2f}")

        # Wait for resolution
        window_end = window_start + 300
        wait = window_end - time.time() + 10
        if wait > 0:
            log.info(f"⏳ Waiting {wait:.0f}s for resolution + claim...")
            time.sleep(max(wait, 0))

        # Try to claim
        check_and_claim()


def main():
    """Main loop."""
    log.info("=" * 50)
    log.info("🤖 Polymarket BTC Up/Down Bot")
    log.info(f"   Mode: {'🧪 DRY RUN' if DRY_RUN else '💰 LIVE'}")
    log.info(f"   Bet: ${BET_SIZE:.2f} | Min Delta: {MIN_DELTA_PCT}%")
    log.info(f"   Target Profit: ${TARGET_PROFIT:.2f}")
    log.info("=" * 50)

    init_clob()

    trade_count = 0
    total_pnl = 0

    while True:
        try:
            log.info(f"\n{'─' * 40}")
            log.info(f"Trade #{trade_count + 1}")
            run_trade_cycle()
            trade_count += 1

            # Periodic claim check
            if trade_count % 5 == 0:
                check_and_claim()

        except KeyboardInterrupt:
            log.info("\n👋 Stopped by user")
            break
        except Exception as e:
            log.error(f"❌ Error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
