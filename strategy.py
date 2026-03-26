"""
Strategy module for BTC Up/Down 5-min prediction.
=================================================
STRATEGY: Bet 10 seconds after market opens.
At T+10s, use early momentum + recent trend to predict direction.
Token price is cheap (~$0.50) = bigger profit if correct.

Signals:
1. Early delta (first 10s direction)
2. Pre-window momentum (trend leading into this window)
3. Micro trend from recent candles
"""

import requests
import time

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
BINANCE_TICKER = "https://api.binance.com/api/v3/ticker/price"


def get_btc_price():
    """Get current BTC/USDT price from Binance."""
    resp = requests.get(BINANCE_TICKER, params={"symbol": "BTCUSDT"}, timeout=5)
    resp.raise_for_status()
    return float(resp.json()["price"])


def get_recent_candles(minutes=15):
    """Get recent 1-min BTC candles from Binance."""
    resp = requests.get(BINANCE_KLINES, params={
        "symbol": "BTCUSDT",
        "interval": "1m",
        "limit": minutes,
    }, timeout=5)
    resp.raise_for_status()
    return [
        {
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "volume": float(c[5]),
        }
        for c in resp.json()
    ]


def analyze(window_open_price: float) -> dict:
    """
    Analyze at T+10s after window open.
    Uses early momentum + recent trend to predict 5-min direction.
    """
    current_price = get_btc_price()
    candles = get_recent_candles(15)

    score = 0.0
    reasons = []

    # ── 1. Early Delta (weight 3) ──
    # How much has BTC moved in first 10 seconds?
    early_delta = (current_price - window_open_price) / window_open_price * 100
    abs_early = abs(early_delta)

    if abs_early > 0.02:
        score += 3.0 * (1 if early_delta > 0 else -1)
        reasons.append(f"early_delta={early_delta:+.4f}% (strong)")
    elif abs_early > 0.005:
        score += 1.5 * (1 if early_delta > 0 else -1)
        reasons.append(f"early_delta={early_delta:+.4f}% (moderate)")
    else:
        reasons.append(f"early_delta={early_delta:+.4f}% (flat)")

    # ── 2. Pre-window Momentum (weight 4) — DOMINANT ──
    # What was BTC doing in the 5 minutes BEFORE this window?
    # Strong momentum tends to continue into the next window
    if len(candles) >= 10:
        pre_window_start = candles[-10]["open"]  # ~10 min ago
        pre_window_end = candles[-5]["close"]     # ~5 min ago (window open)
        pre_momentum = (pre_window_end - pre_window_start) / pre_window_start * 100

        if abs(pre_momentum) > 0.10:
            score += 4.0 * (1 if pre_momentum > 0 else -1)
            reasons.append(f"pre_momentum={pre_momentum:+.4f}% (STRONG trend)")
        elif abs(pre_momentum) > 0.05:
            score += 2.5 * (1 if pre_momentum > 0 else -1)
            reasons.append(f"pre_momentum={pre_momentum:+.4f}% (trend)")
        elif abs(pre_momentum) > 0.02:
            score += 1.0 * (1 if pre_momentum > 0 else -1)
            reasons.append(f"pre_momentum={pre_momentum:+.4f}% (slight)")

    # ── 3. Last 3 candles direction (weight 2) ──
    if len(candles) >= 3:
        ups = 0
        for c in candles[-3:]:
            if c["close"] > c["open"]:
                ups += 1
        if ups >= 3:
            score += 2.0
            reasons.append("last_3_candles=ALL UP")
        elif ups == 0:
            score -= 2.0
            reasons.append("last_3_candles=ALL DOWN")
        elif ups >= 2:
            score += 1.0
            reasons.append("last_3_candles=mostly up")
        else:
            score -= 1.0
            reasons.append("last_3_candles=mostly down")

    # ── 4. Volume trend (weight 1) ──
    if len(candles) >= 6:
        recent_vol = sum(c["volume"] for c in candles[-3:]) / 3
        prior_vol = sum(c["volume"] for c in candles[-6:-3]) / 3
        if prior_vol > 0 and recent_vol > prior_vol * 1.5:
            if score > 0:
                score += 1.0
            elif score < 0:
                score -= 1.0
            reasons.append("volume_surge=YES (confirms)")

    # ── 5. EMA trend (weight 1.5) ──
    if len(candles) >= 10:
        ema_short = sum(c["close"] for c in candles[-5:]) / 5
        ema_long = sum(c["close"] for c in candles[-10:]) / 10
        if ema_short > ema_long:
            score += 1.5
            reasons.append("ema5>ema10=bullish")
        elif ema_short < ema_long:
            score -= 1.5
            reasons.append("ema5<ema10=bearish")

    # ── Confidence ──
    confidence = min(abs(score) / 6.0, 1.0)
    direction = "UP" if score > 0 else "DOWN"

    return {
        "direction": direction,
        "confidence": round(confidence, 3),
        "delta_pct": round(early_delta, 4),
        "score": round(score, 2),
        "current_price": current_price,
        "reason": " | ".join(reasons),
    }
