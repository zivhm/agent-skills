---
name: ccxt-exchanges
description: Fetch crypto exchange market data with a local Python CLI built on ccxt. Use when Codex or a human operator needs deterministic, script-based access to exchange listings, markets, tickers, order books, OHLCV candles, funding rates, or JSON snapshots across supported centralized and derivative exchanges.
---

# Ccxt Exchanges

Run the bundled CLI directly:

```powershell
python scripts/ccxt_exchanges.py --help
```

## Commands

```powershell
python scripts/ccxt_exchanges.py exchanges
python scripts/ccxt_exchanges.py markets binance --quote USDT
python scripts/ccxt_exchanges.py ticker bybit BTC/USDT:USDT
python scripts/ccxt_exchanges.py book binance BTC/USDT --depth 10
python scripts/ccxt_exchanges.py candles okx ETH/USDT --timeframe 1h --limit 24
python scripts/ccxt_exchanges.py funding bybit BTC/USDT:USDT
python scripts/ccxt_exchanges.py snapshot binance BTC/USDT ETH/USDT --output binance-snapshot.json
```

## Notes

- Use exchange ids exactly as ccxt expects, such as `binance`, `bybit`, `okx`, or `kraken`
- Symbols must match the selected exchange's market format
- Use `markets` first when you are unsure about the exact symbol naming
- `funding` only works on exchanges and markets where ccxt exposes funding-rate methods
- `snapshot` saves a reusable JSON artifact for later analysis or diffing
