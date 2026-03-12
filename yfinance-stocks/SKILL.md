---
name: yfinance-stocks
description: Fetch stock market data with a local Python CLI built on yfinance. Use when Codex or a human operator needs deterministic, script-based access to stock quotes, price history, company metadata, financial statements, option expirations, or JSON snapshots for equities and ETFs.
---

# Yfinance Stocks

Run the bundled CLI directly:

```powershell
python scripts/yfinance_stocks.py --help
```

## Commands

```powershell
python scripts/yfinance_stocks.py quote AAPL MSFT
python scripts/yfinance_stocks.py history AAPL --period 6mo --interval 1d
python scripts/yfinance_stocks.py history SPY --period 1y --csv spy.csv
python scripts/yfinance_stocks.py info NVDA --keys sector industry marketCap
python scripts/yfinance_stocks.py financials AMZN --statement income --frequency annual
python scripts/yfinance_stocks.py news SPY BTC-USD --limit 10
python scripts/yfinance_stocks.py options TSLA
python scripts/yfinance_stocks.py options TSLA --expiration 2026-01-16 --json
python scripts/yfinance_stocks.py snapshot AAPL MSFT --output tech-snapshot.json
```

## Notes

- Use `quote` for fast multi-symbol checks
- Use `history` for deterministic OHLCV output and CSV export
- Use `info` when you need selected metadata fields instead of the full payload
- Use `financials` for annual or quarterly statements
- Use `news` for live Yahoo Finance headline context
- Use `snapshot` to save a reusable JSON artifact for later comparison or automation
