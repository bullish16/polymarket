"""
Polymarket BTC Up/Down 5-Min Trading Bot
==========================================
STRATEGY: Bet 10 seconds after market opens.
- Token price cheap (~$0.50) at this point
- If profit reaches $0.30, close position early
- If not profitable, hold to resolution
- Max bet: $1

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
os.environ["HTTP_PROXY"] = "socks5://127.0.0.1:40000"
os.environ["HTTPS_PROXY"] = "socks5://127.0.0.1:40000"

# ── Config ──
BET_SIZE = float(os.getenv("BET_SIZE", "1.00"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.0"))  # Always bet
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
    ]
)
log = logging.getLogger("polybot")

# ── Polymarket Client ──
clob_client = None


def init_clob():
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
    clob_client.set_api_creds(clob_client.create_or_derive_api_creds())
    log.info("✅ CLOB client initialized")


def get_current_market():
    """Find current active BTC Up/Down 5-min market."""
    from market import get_current_market as _get_market
    return _get_market()


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
            return float(data[0][1])
    except Exception as e:
        log.warning(f"⚠️ Failed to get window open price: {e}")
    return None


def get_orderbook_price(market, direction):
    """Get best ask price from the orderbook."""
    if DRY_RUN or not clob_client:
        return 0.50  # estimate for dry run

    token_info = market["tokens"].get(direction)
    if not token_info:
        return 0.50

    try:
        book = clob_client.get_order_book(token_info["token_id"])
        asks = book.asks or []
        if asks:
            return float(asks[0].price)
    except:
        pass
    return 0.50


def place_bet(market, direction, bet_size):
    """Place a bet on Polymarket. Buys whatever shares $bet_size can afford."""
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
        from py_clob_client.clob_types import OrderArgs

        book = clob_client.get_order_book(token_id)
        asks = book.asks or []

        # Get min order size from book (default 1)
        min_size = float(book.min_order_size) if book.min_order_size else 1.0

        if not asks:
            log.warning("⚠️ No asks in book, posting limit @ $0.55")
            price = 0.55
        else:
            price = float(asks[0].price)
            log.info(f"📊 Best ask: ${price:.4f}")

        # Skip if price too high (>$0.95 = almost no upside)
        if price > 0.95:
            log.warning(f"⚠️ Price too high ${price:.2f} (max upside ${1-price:.2f}). Posting limit @ $0.55")
            price = 0.55

        # Calculate shares from budget
        actual_size = min(bet_size, BET_SIZE)
        shares = actual_size / price

        # Ensure minimum order size
        if shares < min_size:
            shares = min_size
            actual_size = shares * price

        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=round(shares, 2),
            side="BUY",
        )

        log.info(f"📤 BUY {direction}: {shares:.1f} shares @ ${price:.3f} = ${actual_size:.2f}")
        result = clob_client.create_and_post_order(order_args)
        log.info(f"✅ Order placed: {result}")
        return {"result": result, "price": price, "shares": round(shares, 2), "cost": actual_size}

    except Exception as e:
        log.error(f"❌ Order failed: {e}")
        return None


def try_early_exit(market, direction, entry_price, shares):
    """
    Try to sell position early if profit target is met.
    Monitor every 5 seconds. If token price >= entry + target_profit_per_share, sell.
    """
    if DRY_RUN:
        return False

    if not clob_client or not market:
        return False

    token_info = market["tokens"].get(direction)
    if not token_info:
        return False

    target_sell_price = entry_price + (TARGET_PROFIT / shares)

    try:
        book = clob_client.get_order_book(token_info["token_id"])
        bids = book.bids or []
        if bids:
            best_bid = float(bids[0].price)
            potential_profit = (best_bid - entry_price) * shares

            if potential_profit >= TARGET_PROFIT:
                from py_clob_client.clob_types import OrderArgs
                order_args = OrderArgs(
                    token_id=token_info["token_id"],
                    price=best_bid,
                    size=shares,
                    side="SELL",
                )
                result = clob_client.create_and_post_order(order_args)
                log.info(f"💰 EARLY EXIT! Sold @ ${best_bid:.3f}, profit: ${potential_profit:.2f}")
                return True
    except Exception as e:
        log.debug(f"Exit check error: {e}")

    return False


def check_and_claim():
    """Check for claimable winning positions and claim them."""
    if DRY_RUN or not clob_client:
        return

    try:
        positions = clob_client.get_positions()
        for pos in positions:
            if pos.get("resolved") and pos.get("claimable", False):
                payout = pos.get("payout", 0)
                cid = pos.get("conditionId", "")
                if payout > 0 and cid:
                    log.info(f"💰 Claiming ${payout:.4f}")
                    clob_client.claim(cid)
    except Exception as e:
        log.debug(f"Claim check: {e}")


def wait_for_window_open():
    """
    Wait for the NEXT 5-min window to open, then wait 10 more seconds.
    Returns the window start timestamp.
    """
    now = int(time.time())
    current_window = now - (now % 300)
    next_window = current_window + 300

    # We want to bet at T+10s after next window opens
    entry_time = next_window + 10

    # If we're already past T+10s of current window but before next,
    # use next window
    if now < current_window + 10:
        entry_time = current_window + 10
        next_window = current_window

    wait_secs = entry_time - now
    if wait_secs < 0:
        # Already past entry for current window, wait for next
        next_window = current_window + 300
        entry_time = next_window + 10
        wait_secs = entry_time - now

    entry_dt = datetime.fromtimestamp(entry_time, tz=timezone.utc)
    log.info(f"⏳ Next entry at {entry_dt.strftime('%H:%M:%S')} UTC (T+10s) — waiting {wait_secs}s")

    while time.time() < entry_time:
        remaining = entry_time - time.time()
        if remaining > 30:
            time.sleep(10)
        elif remaining > 5:
            time.sleep(1)
        else:
            time.sleep(0.5)

    return next_window


def run_trade_cycle():
    """Execute one trading cycle: bet at T+10s, monitor for early exit, hold to resolution."""
    from strategy import analyze

    # Wait for window open + 10s
    window_start = wait_for_window_open()
    window_end = window_start + 300

    ws_dt = datetime.fromtimestamp(window_start, tz=timezone.utc)
    we_dt = datetime.fromtimestamp(window_end, tz=timezone.utc)
    log.info(f"🕐 Window: {ws_dt.strftime('%H:%M')} - {we_dt.strftime('%H:%M')} UTC")

    # Get window open price
    open_price = get_window_open_price(window_start)
    if not open_price:
        # Fallback: use current price minus a small buffer
        from strategy import get_btc_price
        open_price = get_btc_price()
        log.warning(f"⚠️ Using current price as proxy: ${open_price:,.2f}")
    else:
        log.info(f"📊 Window open: ${open_price:,.2f}")

    # Run analysis at T+10s
    signal = analyze(open_price)
    log.info(
        f"📈 {signal['direction']} | "
        f"confidence={signal['confidence']:.1%} | "
        f"score={signal['score']} | "
        f"{signal['reason']}"
    )

    # Check confidence threshold
    if signal["confidence"] < MIN_CONFIDENCE:
        log.info(f"⏭️ Skipping (confidence {signal['confidence']:.1%} < {MIN_CONFIDENCE:.0%})")
        return

    # Place bet
    direction = signal["direction"]
    market = get_current_market()

    if DRY_RUN:
        entry_price = 0.50  # early entry = cheap tokens
        shares = BET_SIZE / entry_price
        log.info(f"🧪 [DRY] Bet ${BET_SIZE:.2f} on {direction} @ ~${entry_price:.2f} ({shares:.1f} shares)")

        # Monitor for early exit (dry run simulation)
        exited_early = False
        check_interval = 15  # check every 15s
        remaining = window_end - time.time()

        while remaining > 5:
            time.sleep(min(check_interval, remaining - 5))
            remaining = window_end - time.time()

            # Check current price for simulated early exit
            try:
                from strategy import get_btc_price
                current = get_btc_price()
                current_delta = (current - open_price) / open_price * 100

                # Estimate token value
                abs_d = abs(current_delta)
                if direction == "UP":
                    token_val = 0.50 + min(abs_d * 5, 0.47) if current_delta > 0 else max(0.50 - abs_d * 5, 0.03)
                else:
                    token_val = 0.50 + min(abs_d * 5, 0.47) if current_delta < 0 else max(0.50 - abs_d * 5, 0.03)

                sim_profit = (token_val - entry_price) * shares
                log.info(f"   📊 BTC delta={current_delta:+.4f}% | token~${token_val:.2f} | unrealized=${sim_profit:+.2f}")

                if sim_profit >= TARGET_PROFIT:
                    log.info(f"   💰 [DRY] EARLY EXIT! Profit: ${sim_profit:+.2f} ≥ ${TARGET_PROFIT}")
                    exited_early = True
                    break
            except:
                pass

        if not exited_early:
            # Wait for resolution
            wait = window_end - time.time() + 5
            if wait > 0:
                log.info(f"   ⏳ Holding to resolution ({wait:.0f}s)...")
                time.sleep(max(wait, 0))

            # Check result
            try:
                close_price = get_window_open_price(window_start + 300)
                if not close_price:
                    from strategy import get_btc_price
                    close_price = get_btc_price()

                actual = "UP" if close_price >= open_price else "DOWN"
                won = direction == actual
                pnl = (shares * 1.0 - BET_SIZE) if won else -BET_SIZE
                emoji = "✅" if won else "❌"
                log.info(f"   {emoji} Resolution: {actual} | P&L: ${pnl:+.2f}")
            except Exception as e:
                log.warning(f"   ⚠️ Could not verify: {e}")
        return

    # LIVE trading
    if not market:
        log.warning("⚠️ Could not find market. Skipping.")
        return

    order = place_bet(market, direction, BET_SIZE)
    if not order:
        return

    entry_price = order.get("price", 0.50)
    shares = order.get("shares", BET_SIZE / 0.50)

    # Monitor for early exit
    log.info(f"👁️ Monitoring for early exit (target +${TARGET_PROFIT:.2f})...")
    exited_early = False

    while time.time() < window_end - 10:
        time.sleep(5)
        if try_early_exit(market, direction, entry_price, shares):
            exited_early = True
            break

    if not exited_early:
        log.info("⏳ Holding to resolution...")
        wait = window_end - time.time() + 10
        if wait > 0:
            time.sleep(max(wait, 0))

    # Claim
    check_and_claim()


# ── Stats tracking ──
stats = {"trades": 0, "wins": 0, "losses": 0, "skips": 0, "total_pnl": 0.0}


def main():
    log.info("=" * 55)
    log.info("🤖 Polymarket BTC Up/Down Bot (T+10s Strategy)")
    log.info(f"   Mode: {'🧪 DRY RUN' if DRY_RUN else '💰 LIVE'}")
    log.info(f"   Bet: ${BET_SIZE:.2f} max | Confidence min: {MIN_CONFIDENCE:.0%}")
    log.info(f"   Target Profit: ${TARGET_PROFIT:.2f} (early exit)")
    log.info(f"   If no profit → hold to resolution")
    log.info("=" * 55)

    init_clob()

    trade_count = 0

    while True:
        try:
            trade_count += 1
            log.info(f"\n{'─' * 45}")
            log.info(f"Trade #{trade_count}")
            run_trade_cycle()

            if trade_count % 5 == 0:
                check_and_claim()

        except KeyboardInterrupt:
            log.info("\n👋 Stopped by user")
            break
        except Exception as e:
            log.error(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(10)


if __name__ == "__main__":
    main()
