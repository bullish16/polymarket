"""
Strategy module for BTC Up/Down 5-min prediction.

Uses Binance real-time data to generate a composite signal.
Primary signal: Window Delta (how far BTC has moved from window open).
Secondary: Micro momentum from recent candles.
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


def get_recent_candles(minutes=10):
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
    Analyze current BTC state relative to window open price.

    Returns:
        {
            "direction": "UP" | "DOWN",
            "confidence": 0.0 - 1.0,
            "delta_pct": float,
            "score": float,
            "reason": str,
        }
    """
    current_price = get_btc_price()
    candles = get_recent_candles(5)

    # ── 1. Window Delta (dominant signal, weight 5-7) ──
    delta_pct = (current_price - window_open_price) / window_open_price * 100
    abs_delta = abs(delta_pct)

    if abs_delta > 0.10:
        delta_score = 7.0
    elif abs_delta > 0.05:
        delta_score = 5.0
    elif abs_delta > 0.02:
        delta_score = 3.0
    elif abs_delta > 0.005:
        delta_score = 1.5
    else:
        delta_score = 0.5

    direction = 1 if delta_pct > 0 else -1
    score = delta_score * direction

    # ── 2. Micro Momentum (last 2 candles, weight 2) ──
    if len(candles) >= 2:
        c1 = candles[-2]["close"]
        c2 = candles[-1]["close"]
        if c2 > c1:
            score += 2.0
        elif c2 < c1:
            score -= 2.0

    # ── 3. Acceleration (weight 1.5) ──
    if len(candles) >= 3:
        move_recent = candles[-1]["close"] - candles[-2]["close"]
        move_prior = candles[-2]["close"] - candles[-3]["close"]
        if move_recent > move_prior and move_recent > 0:
            score += 1.5  # accelerating up
        elif move_recent < move_prior and move_recent < 0:
            score -= 1.5  # accelerating down

    # ── 4. Volume surge (weight 1) ──
    if len(candles) >= 6:
        recent_vol = sum(c["volume"] for c in candles[-3:]) / 3
        prior_vol = sum(c["volume"] for c in candles[-6:-3]) / 3
        if prior_vol > 0 and recent_vol > prior_vol * 1.5:
            # Confirms current direction
            if score > 0:
                score += 1.0
            elif score < 0:
                score -= 1.0

    # ── Confidence ──
    confidence = min(abs(score) / 7.0, 1.0)
    pred_direction = "UP" if score > 0 else "DOWN"

    reason_parts = [f"delta={delta_pct:+.4f}%"]
    if abs_delta > 0.10:
        reason_parts.append("STRONG signal")
    elif abs_delta > 0.05:
        reason_parts.append("good signal")
    elif abs_delta > 0.02:
        reason_parts.append("moderate signal")
    else:
        reason_parts.append("weak signal")

    return {
        "direction": pred_direction,
        "confidence": round(confidence, 3),
        "delta_pct": round(delta_pct, 4),
        "score": round(score, 2),
        "current_price": current_price,
        "reason": ", ".join(reason_parts),
    }
