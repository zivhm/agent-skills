---
name: hyperliquid
description: Fetch live market data and user portfolio/position info from Hyperliquid (perps DEX) via the public API (https://api.hyperliquid.xyz). Use when user asks for Hyperliquid prices, mids, order book, candles, funding, open interest, account state, positions, balances, PnL, or other live Hyperliquid market/account data.
homepage: https://hyperliquid.xyz
metadata: {"openclaw": {"emoji": "🧪", "requires": {"bins": ["python3"]}}}
---

# Hyperliquid (public API)

Hyperliquid provides a public HTTP API (mainnet: `https://api.hyperliquid.xyz`, testnet: `https://api.hyperliquid-testnet.xyz`).

This skill ships a small Python client script:

- Script: `scripts/hyperliquid.py`

## Quick start

```bash
# All mid prices
python3 scripts/hyperliquid.py mids

# Exchange metadata (assets/universe)
python3 scripts/hyperliquid.py meta

# Order book (L2)
python3 scripts/hyperliquid.py book BTC

# Candles
python3 scripts/hyperliquid.py candles BTC --interval 15m --limit 200

# Perps meta+contexts (funding, open interest, mark/mid, etc.)
python3 scripts/hyperliquid.py meta-ctx --json

# Predicted funding (across venues)
python3 scripts/hyperliquid.py predicted-funding --json

# Hyperdash-style dashboard (scannable snapshot)
# Default includes HIP-3 perp DEX scan
python3 scripts/hyperliquid.py dash 0xYOURADDRESS

# Main dex only (faster)
python3 scripts/hyperliquid.py dash 0xYOURADDRESS --main-only

# User state (perps positions/margin + spot balances)
python3 scripts/hyperliquid.py user 0xYOURADDRESS --json

# Also scan HIP-3 perp dexs (some markets like xyz:GOLD live there)
python3 scripts/hyperliquid.py user 0xYOURADDRESS --all-dexs --json

# Open orders
python3 scripts/hyperliquid.py open-orders 0xYOURADDRESS --json
```

## Notes

- No API key is required for public market + user state queries.
- Defaults to mainnet. Override with `--base-url`.
- If Hyperliquid changes API shapes, update `scripts/hyperliquid.py`.
