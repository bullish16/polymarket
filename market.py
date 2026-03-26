"""
Market discovery for Polymarket BTC Up/Down 5-min markets.
"""

import time
import requests
import logging

GAMMA_HOST = "https://gamma-api.polymarket.com"
log = logging.getLogger("polybot")


def get_current_market():
    """
    Find the current active BTC Up/Down 5-min market.
    Returns dict with token IDs for UP and DOWN, or None.
    """
    now = int(time.time())
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
            log.warning(f"⚠️ No event found for slug: {slug}")
            return None

        event = events[0]
        markets = event.get("markets", [])

        if not markets:
            log.warning(f"⚠️ No markets in event")
            return None

        # BTC Up/Down has 1 market with 2 tokens (outcomes)
        market = markets[0]

        # Parse clobTokenIds - can be a JSON string or list
        clob_token_ids = market.get("clobTokenIds", [])
        if isinstance(clob_token_ids, str):
            import json
            clob_token_ids = json.loads(clob_token_ids)

        if len(clob_token_ids) < 2:
            log.warning(f"⚠️ Expected 2 tokens, got {len(clob_token_ids)}")
            return None

        # outcomes[0] = Up (Yes), outcomes[1] = Down (No)
        # In Polymarket binary markets:
        # - Token 0 = Yes/Up
        # - Token 1 = No/Down
        condition_id = market.get("conditionId", "")

        result = {
            "slug": slug,
            "window_start": window_ts,
            "window_end": window_ts + 300,
            "condition_id": condition_id,
            "market_id": market.get("id", ""),
            "tokens": {
                "UP": {
                    "token_id": clob_token_ids[0],
                    "condition_id": condition_id,
                },
                "DOWN": {
                    "token_id": clob_token_ids[1],
                    "condition_id": condition_id,
                },
            },
        }

        log.info(f"✅ Market found: {slug}")
        log.debug(f"   UP token: {clob_token_ids[0][:20]}...")
        log.debug(f"   DOWN token: {clob_token_ids[1][:20]}...")

        return result

    except Exception as e:
        log.warning(f"⚠️ Market fetch error: {e}")
        return None
