"""
Auto-Claim: Periodically checks and claims winning Polymarket positions.
Runs as a separate process alongside the main bot.

Usage: python3 auto_claim.py
"""

import os
import sys
import time
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
SIGNATURE_TYPE = int(os.getenv("SIGNATURE_TYPE", "1"))
CLOB_HOST = "https://clob.polymarket.com"
CHECK_INTERVAL = 60  # Check every 60 seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CLAIM] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("claim.log"),
    ]
)
log = logging.getLogger("autoclaim")


def init_client():
    if not PRIVATE_KEY:
        log.error("❌ PRIVATE_KEY not set")
        sys.exit(1)

    pk = PRIVATE_KEY
    if pk.startswith("0x"):
        pk = pk[2:]

    from py_clob_client.client import ClobClient

    client = ClobClient(
        host=CLOB_HOST,
        key=pk,
        chain_id=137,
        signature_type=SIGNATURE_TYPE,
    )
    client.set_api_creds(client.create_or_derive_api_creds())
    return client


def claim_all(client):
    """Check for resolved markets and claim winnings."""
    try:
        positions = client.get_positions()
        claimed = 0

        for pos in positions:
            if pos.get("resolved") and pos.get("claimable", False):
                payout = pos.get("payout", 0)
                condition_id = pos.get("conditionId", "")

                if payout > 0 and condition_id:
                    log.info(f"💰 Claiming ${payout:.4f} from {condition_id[:16]}...")
                    try:
                        client.claim(condition_id)
                        claimed += 1
                        log.info(f"   ✅ Claimed!")
                    except Exception as e:
                        log.warning(f"   ⚠️ Claim failed: {e}")

        if claimed:
            log.info(f"💰 Claimed {claimed} position(s)")
        return claimed

    except Exception as e:
        log.debug(f"Check error: {e}")
        return 0


def main():
    log.info("🔄 Auto-Claim started")
    log.info(f"   Checking every {CHECK_INTERVAL}s")

    client = init_client()
    total_claimed = 0

    while True:
        try:
            n = claim_all(client)
            total_claimed += n
            if n:
                log.info(f"📊 Total claimed this session: {total_claimed}")
        except KeyboardInterrupt:
            log.info("👋 Stopped")
            break
        except Exception as e:
            log.error(f"Error: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
