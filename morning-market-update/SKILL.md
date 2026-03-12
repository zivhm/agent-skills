---
name: morning-market-update
description: Generates a clean, minimal Telegram-formatted morning market update by calling local script-based skills for market data. Use when Codex or a human operator needs a daily market summary, a morning market update message, or a filled-in Telegram market template covering crypto, stocks, forex, and commodities.
---

# Morning Market Update

Generate a clean, minimal Telegram-formatted morning market update.

## Output

Use the bundled CLI:

```powershell
python scripts/morning_market_update.py
python scripts/morning_market_update.py --output market-update.txt
python scripts/morning_market_update.py --session-label --change-mode since-open
python scripts/morning_market_update.py --extra-fields TOTAL3 BTCDOM US10Y MOVE
python scripts/morning_market_update.py --cache-minutes 5
python scripts/morning_market_update.py --symbols-file .\my-basket.json
```

## Rules

- Use the generated template exactly as printed by the script
- The script gathers crypto data from `hyperliquid` and `ccxt-exchanges`
- The script gathers stocks, forex, and commodities data from `yfinance-stocks`
- The output uses a Telegram-friendly fixed-width code block for cleaner alignment
- Prices use consistent decimals by asset class
- `--change-mode 24h` uses daily change; `--change-mode since-open` uses the move from the session open when that data exists
- `--session-label` appends an Asia, Europe, or US session label to the header
- `--cache-minutes` reuses recent data to avoid repeated slow fetches
- `--extra-fields` adds optional macro or breadth rows such as `TOTAL3`, `BTCDOM`, `US10Y`, or `MOVE`
- Use `--json` when another tool needs the raw collected data instead of the Telegram message

## Symbols File

Use `--symbols-file` with a JSON object whose keys are section names and whose values are arrays of rows.

```json
{
  "crypto": [
    {"label": "BTC", "source": "crypto", "hl": "BTC", "exchange": "binance", "ccxt_symbol": "BTC/USDT", "digits": 2, "prefix": "$"},
    {"label": "ETH", "source": "crypto", "hl": "ETH", "exchange": "binance", "ccxt_symbol": "ETH/USDT", "digits": 2, "prefix": "$"}
  ],
  "stocks": [
    {"label": "SPX", "source": "yfinance", "symbol": "^GSPC", "digits": 2},
    {"label": "QQQ", "source": "yfinance", "symbol": "QQQ", "digits": 2}
  ],
  "extras": [
    {"label": "US10Y", "source": "yfinance", "symbol": "^TNX", "digits": 2, "suffix": "%"}
  ]
}
```
