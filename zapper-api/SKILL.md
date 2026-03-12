---
name: zapper-api
description: Query DeFi portfolios, token holdings, NFTs, transactions, prices, claimables, and token search results through a local Python CLI for the Zapper GraphQL API. Use when Codex or a human operator needs deterministic, script-based access to wallet or token data with JSON, chain filtering, and CSV export.
metadata: {"openclaw":{"emoji":"🟪","requires":{"bins":["python3"]},"primaryEnv":"ZAPPER_API_KEY"}}
---

# Zapper API

Run the bundled CLI directly:

```powershell
python scripts/zapper.py --help
```

## Setup

Set an API key, then pass either an address or a config file when needed.

```json
{
  "apiKey": "your-api-key",
  "wallets": [
    {"label": "Main", "address": "0x..."},
    {"label": "DeFi", "address": "0x..."}
  ]
}
```

```powershell
$env:ZAPPER_API_KEY = "your-api-key"
python scripts/zapper.py config
python scripts/zapper.py --config .\addresses.json config
```

## Commands

```powershell
python scripts/zapper.py portfolio 0xADDR
python scripts/zapper.py portfolio 0xADDR --chain ethereum
python scripts/zapper.py --config .\addresses.json portfolio --per-wallet
python scripts/zapper.py tokens 0xADDR --24h
python scripts/zapper.py tokens 0xADDR --csv export.csv
python scripts/zapper.py apps 0xADDR --chain base
python scripts/zapper.py nfts 0xADDR
python scripts/zapper.py claimables 0xADDR
python scripts/zapper.py wallet-summary
python scripts/zapper.py allocations 0xADDR --group-by network
python scripts/zapper.py price ETH
python scripts/zapper.py price 0xA0b8... --chain ethereum
python scripts/zapper.py search aave
python scripts/zapper.py top-movers 0xADDR
python scripts/zapper.py tx 0xADDR
python scripts/zapper.py tx 0xADDR --csv export.csv
python scripts/zapper.py snapshot --config .\addresses.json --output zapper-snapshot.json
python scripts/zapper.py diff old-snapshot.json new-snapshot.json
python scripts/zapper.py config
python scripts/zapper.py validate-config
```

## Chain Names

ethereum, base, arbitrum, optimism, polygon, avalanche, solana, bnb

## Notes

- Use `--json` for raw API output
- Use `--config <path>` for a self-contained wallet file instead of relying on `~/.config/zapper/addresses.json`
- Wallet labels work instead of addresses when they exist in the selected config file
- CSV export available for tokens, apps, and transactions
- Use `snapshot`, `diff`, and `wallet-summary` for repeatable portfolio monitoring
