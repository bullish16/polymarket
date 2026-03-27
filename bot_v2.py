#!/usr/bin/env python3
"""
Polymarket BTC Up/Down 5-Min Trading Bot v2
=============================================
Clean rewrite. Single file. Tested order placement.

Strategy: Bet at T+10s after window opens, hold or early exit at +$0.30.
"""

import os, sys, time, json, logging, requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ── Config ──
BET_SIZE = float(os.getenv("BET_SIZE", "1.00"))
TARGET_PROFIT = float(os.getenv("TARGET_PROFIT", "0.30"))
DRY_RUN = "--dry-run" in sys.argv

PK = os.getenv("PRIVATE_KEY", "")
SIG_TYPE = int(os.getenv("SIGNATURE_TYPE", "1"))



# ── Logging (single handler to avoid duplicates) ──
log = logging.getLogger("polybot")
log.setLevel(logging.INFO)
# Remove any existing handlers
log.handlers.clear()
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
fh = logging.FileHandler("bot.log")
fh.setFormatter(formatter)
sh = logging.StreamHandler()
sh.setFormatter(formatter)
log.addHandler(fh)
log.addHandler(sh)
# Suppress noisy httpx/httpcore logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ── Globals ──
clob = None
GAMMA = "https://gamma-api.polymarket.com"
BINANCE_TICKER = "https://api.binance.com/api/v3/ticker/price"
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"


def init_clob():
    global clob
    if DRY_RUN:
        log.info("🧪 DRY RUN — no real trades")
        return
    if not PK:
        log.error("❌ No PRIVATE_KEY in .env")
        sys.exit(1)
    from py_clob_client.client import ClobClient
    clob = ClobClient(
        host="https://clob.polymarket.com",
        key=PK if not PK.startswith("0x") else PK[2:],
        chain_id=137,
        signature_type=SIG_TYPE,
    )
    clob.set_api_creds(clob.create_or_derive_api_creds())
    log.info("✅ CLOB connected")


def btc_price():
    r = requests.get(BINANCE_TICKER, params={"symbol": "BTCUSDT"}, timeout=5)
    return float(r.json()["price"])


def btc_candles(n=10):
    r = requests.get(BINANCE_KLINES, params={"symbol": "BTCUSDT", "interval": "1m", "limit": n}, timeout=5)
    return [{"open": float(c[1]), "close": float(c[4]), "volume": float(c[5])} for c in r.json()]


def window_open_price(ts):
    try:
        r = requests.get(BINANCE_KLINES, params={
            "symbol": "BTCUSDT", "interval": "1m", "startTime": ts * 1000, "limit": 1
        }, timeout=5)
        return float(r.json()[0][1])
    except:
        return btc_price()


def find_market(window_ts):
    """Find Polymarket event for this 5-min window."""
    slug = f"btc-updown-5m-{window_ts}"
    try:
        r = requests.get(f"{GAMMA}/events", params={"slug": slug}, timeout=10)
        events = r.json()
        if not events:
            return None
        m = events[0]["markets"][0]
        tids = m.get("clobTokenIds", [])
        if isinstance(tids, str):
            tids = json.loads(tids)
        if len(tids) < 2:
            return None
        return {
            "up_token": tids[0],
            "down_token": tids[1],
            "condition_id": m.get("conditionId", ""),
        }
    except Exception as e:
        log.warning(f"⚠️ Market lookup: {e}")
        return None


def predict(open_price):
    """Predict UP or DOWN using momentum + early delta."""
    price = btc_price()
    candles = btc_candles(10)
    score = 0.0

    # Early delta
    delta = (price - open_price) / open_price * 100
    if abs(delta) > 0.02:
        score += 3.0 * (1 if delta > 0 else -1)
    elif abs(delta) > 0.005:
        score += 1.5 * (1 if delta > 0 else -1)

    # Pre-window momentum (last 5-10 candles)
    if len(candles) >= 10:
        pre = (candles[-5]["close"] - candles[-10]["open"]) / candles[-10]["open"] * 100
        if abs(pre) > 0.10:
            score += 4.0 * (1 if pre > 0 else -1)
        elif abs(pre) > 0.05:
            score += 2.5 * (1 if pre > 0 else -1)
        elif abs(pre) > 0.02:
            score += 1.0 * (1 if pre > 0 else -1)

    # Last 3 candles
    if len(candles) >= 3:
        ups = sum(1 for c in candles[-3:] if c["close"] > c["open"])
        if ups >= 3: score += 2.0
        elif ups == 0: score -= 2.0
        elif ups >= 2: score += 1.0
        else: score -= 1.0

    # EMA
    if len(candles) >= 10:
        ema5 = sum(c["close"] for c in candles[-5:]) / 5
        ema10 = sum(c["close"] for c in candles[-10:]) / 10
        if ema5 > ema10: score += 1.5
        else: score -= 1.5

    direction = "UP" if score >= 0 else "DOWN"
    confidence = min(abs(score) / 6.0, 1.0)
    return direction, confidence, score, delta


def place_order(token_id, direction):
    """Place a limit buy order at ~$0.50. Returns order info or None."""
    if DRY_RUN:
        log.info(f"🧪 [DRY] BUY {direction} $1.00 @ $0.50")
        return {"dry": True, "price": 0.50, "shares": 2.0}

    from py_clob_client.clob_types import OrderArgs
    from py_clob_client.order_builder.constants import BUY

    try:
        book = clob.get_order_book(token_id)
        tick = float(book.tick_size) if book.tick_size else 0.01
        min_sz = float(book.min_order_size) if book.min_order_size else 5.0

        # At T+10s, orderbook is thin. Post limit order at reasonable price.
        # Check if there's a reasonable ask (<$0.70)
        best_ask = float(book.asks[0].price) if book.asks else 1.0
        best_bid = float(book.bids[0].price) if book.bids else 0.0

        if best_ask <= 0.65:
            # Reasonable ask exists — take it
            price = best_ask
            log.info(f"📊 Taking ask @ ${price:.2f}")
        elif best_bid >= 0.35 and best_bid <= 0.65:
            # Reasonable bid exists — join it or improve slightly
            price = min(best_bid + tick, 0.55)
            log.info(f"📊 Improving bid @ ${price:.2f}")
        else:
            # No liquidity — post at $0.50
            price = 0.50
            log.info(f"📊 No liquidity — limit @ ${price:.2f}")

        # Round to tick
        price = round(round(price / tick) * tick, 4)

        shares = BET_SIZE / price
        if shares < min_sz:
            shares = min_sz

        cost = shares * price
        log.info(f"📤 BUY {direction}: {shares:.1f}sh @ ${price} = ${cost:.2f}")

        args = OrderArgs(token_id=token_id, price=price, size=shares, side=BUY)
        result = clob.create_and_post_order(args)
        log.info(f"✅ Order posted: {result}")

        # Wait up to 30s for fill
        log.info("⏳ Waiting for fill...")
        time.sleep(5)

        return {"price": price, "shares": shares, "result": result}

    except Exception as e:
        log.error(f"❌ Order error: {e}")
        import traceback; traceback.print_exc()
        return None


def trade_cycle():
    """One full trade cycle."""
    now = int(time.time())
    current_window = now - (now % 300)

    # Figure out which window to target
    # If we're <10s into current window, use current window
    # Otherwise, wait for next
    elapsed = now - current_window
    if elapsed < 10:
        target_window = current_window
        entry_time = current_window + 10
    else:
        target_window = current_window + 300
        entry_time = target_window + 10

    wait = entry_time - time.time()
    if wait > 0:
        wdt = datetime.fromtimestamp(entry_time, tz=timezone.utc)
        log.info(f"⏳ Entry at {wdt.strftime('%H:%M:%S')} UTC ({wait:.0f}s)")
        while time.time() < entry_time:
            time.sleep(min(10, entry_time - time.time()))

    window_end = target_window + 300
    wdt = datetime.fromtimestamp(target_window, tz=timezone.utc)
    log.info(f"🕐 Window {wdt.strftime('%H:%M')}-{datetime.fromtimestamp(window_end, tz=timezone.utc).strftime('%H:%M')} UTC")

    # Get open price
    open_price = window_open_price(target_window)
    log.info(f"📊 Open: ${open_price:,.2f}")

    # Predict
    direction, confidence, score, delta = predict(open_price)
    log.info(f"📈 {direction} | conf={confidence:.0%} | score={score:.1f} | delta={delta:+.4f}%")

    # Find market
    market = find_market(target_window)
    if not market:
        log.warning("⚠️ No market found — skipping")
        return

    token_id = market["up_token"] if direction == "UP" else market["down_token"]
    log.info(f"🎯 Token: {token_id[:20]}...")

    # Place order
    order = place_order(token_id, direction)
    if not order:
        log.warning("⚠️ Order failed — skipping")
        return

    entry_price = order.get("price", 0.50)
    shares = order.get("shares", 2.0)

    # Monitor for early exit or hold to resolution
    log.info(f"👁️ Monitoring... (target +${TARGET_PROFIT})")
    exited = False

    while time.time() < window_end - 3:
        time.sleep(15)
        try:
            cur = btc_price()
            cur_delta = (cur - open_price) / open_price * 100

            # Estimate token value
            if direction == "UP":
                tv = 0.50 + min(abs(cur_delta) * 5, 0.47) if cur_delta > 0 else max(0.50 - abs(cur_delta) * 5, 0.03)
            else:
                tv = 0.50 + min(abs(cur_delta) * 5, 0.47) if cur_delta < 0 else max(0.50 - abs(cur_delta) * 5, 0.03)

            profit = (tv - entry_price) * shares
            log.info(f"   Δ={cur_delta:+.4f}% | ~${tv:.2f} | P&L=${profit:+.2f}")

            if profit >= TARGET_PROFIT:
                if DRY_RUN:
                    log.info(f"💰 EARLY EXIT! +${profit:.2f}")
                else:
                    # Try to sell
                    try:
                        from py_clob_client.clob_types import OrderArgs
                        from py_clob_client.order_builder.constants import SELL
                        sell_book = clob.get_order_book(token_id)
                        if sell_book.bids:
                            bid = float(sell_book.bids[0].price)
                            sell_profit = (bid - entry_price) * shares
                            if sell_profit >= TARGET_PROFIT * 0.8:
                                tick = float(sell_book.tick_size) if sell_book.tick_size else 0.01
                                bid = round(round(bid / tick) * tick, 4)
                                args = OrderArgs(token_id=token_id, price=bid, size=shares, side=SELL)
                                clob.create_and_post_order(args)
                                log.info(f"💰 SOLD @ ${bid} | profit=${sell_profit:+.2f}")
                    except Exception as e:
                        log.warning(f"⚠️ Sell error: {e}")
                exited = True
                break
        except Exception as e:
            log.debug(f"Monitor: {e}")

    if not exited:
        wait = window_end - time.time() + 5
        if wait > 0:
            log.info(f"⏳ Hold to resolution ({wait:.0f}s)...")
            time.sleep(max(wait, 0))

        try:
            close = btc_price()
            actual = "UP" if close >= open_price else "DOWN"
            won = direction == actual
            pnl = (shares * 1.0 - shares * entry_price) if won else -(shares * entry_price)
            log.info(f"{'✅' if won else '❌'} Result: {actual} | P&L: ${pnl:+.2f}")
        except:
            log.info("⏳ Resolution complete")

    # Try claim
    if not DRY_RUN and clob:
        try:
            # Simple claim attempt
            pass  # auto_claim.py handles this
        except:
            pass


def main():
    log.info("=" * 50)
    log.info(f"🤖 Polymarket BTC Bot v2 ({'🧪 DRY' if DRY_RUN else '💰 LIVE'})")
    log.info(f"   Bet: ${BET_SIZE} | Target: +${TARGET_PROFIT}")
    log.info("=" * 50)

    init_clob()
    n = 0

    while True:
        try:
            n += 1
            log.info(f"\n{'─' * 40}")
            log.info(f"Trade #{n}")
            trade_cycle()
        except KeyboardInterrupt:
            log.info("👋 Bye")
            break
        except Exception as e:
            log.error(f"❌ {e}")
            import traceback; traceback.print_exc()
            time.sleep(10)


if __name__ == "__main__":
    main()
