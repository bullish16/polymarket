"""
One-time setup: Derive Polymarket CLOB API credentials from your private key.
Run this once, then copy the output to your .env file.

Usage: python3 setup_creds.py
"""

import os
from dotenv import load_dotenv

load_dotenv()

def main():
    pk = os.getenv("PRIVATE_KEY")
    sig_type = int(os.getenv("SIGNATURE_TYPE", "1"))

    if not pk:
        print("❌ Set PRIVATE_KEY in .env first (without 0x prefix)")
        return

    # Remove 0x prefix if present
    if pk.startswith("0x"):
        pk = pk[2:]

    from py_clob_client.client import ClobClient

    client = ClobClient(
        host="https://clob.polymarket.com",
        key=pk,
        chain_id=137,
        signature_type=sig_type,
    )

    print("🔑 Deriving API credentials...")
    creds = client.derive_api_key()

    print("\n✅ Add these to your .env file:\n")
    print(f"POLY_API_KEY={creds['apiKey']}")
    print(f"POLY_API_SECRET={creds['secret']}")
    print(f"POLY_PASSPHRASE={creds['passphrase']}")
    print("\n⚠️  Keep these secret! Don't share them.")

if __name__ == "__main__":
    main()
