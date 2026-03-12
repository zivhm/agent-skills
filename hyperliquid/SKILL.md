---
name: hyperliquid
description: Fetch live market and account data from Hyperliquid with a local Python CLI. Use when Codex or a human operator needs deterministic, script-based access to prices, order books, candles, funding, positions, balances, open orders, or market listings from the Hyperliquid public API.
metadata: {"openclaw": {"emoji": "🧪", "requires": {"bins": ["python3"]}}}
---

# Hyperliquid

Run the bundled CLI directly:

```powershell
python scripts/hyperliquid.py --help
```

## Commands

```powershell
python scripts/hyperliquid.py mids
python scripts/hyperliquid.py book BTC
python scripts/hyperliquid.py book xyz:PLATINUM
python scripts/hyperliquid.py markets
python scripts/hyperliquid.py ticker BTC
python scripts/hyperliquid.py scan-funding --limit 25
python scripts/hyperliquid.py candles BTC --interval 15m --limit 200
python scripts/hyperliquid.py meta-ctx --json
python scripts/hyperliquid.py predicted-funding --json
python scripts/hyperliquid.py user 0xADDR --json
python scripts/hyperliquid.py dash 0xADDR
python scripts/hyperliquid.py open-orders 0xADDR --json
python scripts/hyperliquid.py snapshot --output hl-snapshot.json
python scripts/hyperliquid.py diff old-snapshot.json new-snapshot.json
```

## Notes

- No API key needed
- Prefer `--json` when another tool will consume the output
- Use `snapshot` and `diff` for repeatable monitoring workflows
- Use `xyz:SYMBOL` format for HIP-3 markets (e.g., `xyz:PLATINUM`, `xyz:GOLD`, `xyz:NVDA`)
- Run `markets` to see all available assets
- Default: mainnet. Use `--base-url` for testnet
