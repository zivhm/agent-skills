#!/usr/bin/env python3
"""Deterministic crypto exchange CLI built on ccxt."""

import argparse
import json
import math
from pathlib import Path
import sys
import warnings

warnings.filterwarnings("ignore")

try:
    import ccxt
except ImportError as exc:  # pragma: no cover
    print("ERROR: ccxt is not installed. Install it with `python -m pip install ccxt`.", file=sys.stderr)
    raise SystemExit(1) from exc


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _write_json(path, payload):
    Path(path).write_text(json.dumps(_clean(payload), indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _print_table(rows, columns):
    if not rows:
        print("No rows")
        return
    widths = {col: len(col) for col in columns}
    for row in rows:
        for col in columns:
            widths[col] = max(widths[col], len(str(row.get(col, ""))))
    print("  ".join(f"{col:<{widths[col]}}" for col in columns))
    print("  ".join("-" * widths[col] for col in columns))
    for row in rows:
        print("  ".join(f"{str(row.get(col, '')):<{widths[col]}}" for col in columns))


def _make_exchange(name):
    if not hasattr(ccxt, name):
        fail(f"Unsupported exchange '{name}'")
    exchange_class = getattr(ccxt, name)
    exchange = exchange_class({"enableRateLimit": True})
    exchange.load_markets()
    return exchange


def cmd_exchanges(args):
    rows = []
    for name in sorted(ccxt.exchanges):
        exchange_class = getattr(ccxt, name)
        rows.append(
            {
                "exchange": name,
                "countries": ",".join(exchange_class.countries or []),
                "certified": getattr(exchange_class, "certified", False),
            }
        )
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    _print_table(rows[: args.limit], ["exchange", "countries", "certified"])


def cmd_markets(args):
    exchange = _make_exchange(args.exchange)
    rows = []
    for symbol, market in exchange.markets.items():
        if args.quote and market.get("quote") != args.quote.upper():
            continue
        rows.append(
            {
                "symbol": symbol,
                "type": market.get("type"),
                "base": market.get("base"),
                "quote": market.get("quote"),
                "active": market.get("active"),
                "spot": market.get("spot"),
                "swap": market.get("swap"),
            }
        )
    rows.sort(key=lambda row: row["symbol"])
    if args.json:
        print(json.dumps(rows[: args.limit], indent=2))
        return
    _print_table(rows[: args.limit], ["symbol", "type", "base", "quote", "active", "spot", "swap"])


def cmd_ticker(args):
    exchange = _make_exchange(args.exchange)
    ticker = exchange.fetch_ticker(args.symbol)
    payload = {
        "exchange": args.exchange,
        "symbol": args.symbol,
        "last": ticker.get("last"),
        "bid": ticker.get("bid"),
        "ask": ticker.get("ask"),
        "high": ticker.get("high"),
        "low": ticker.get("low"),
        "open": ticker.get("open"),
        "close": ticker.get("close"),
        "change": ticker.get("change"),
        "percentage": ticker.get("percentage"),
        "baseVolume": ticker.get("baseVolume"),
        "quoteVolume": ticker.get("quoteVolume"),
        "timestamp": ticker.get("datetime") or ticker.get("timestamp"),
    }
    if args.json:
        print(json.dumps(_clean(payload), indent=2))
        return
    _print_table([payload], ["exchange", "symbol", "last", "bid", "ask", "high", "low", "percentage", "quoteVolume"])


def cmd_book(args):
    exchange = _make_exchange(args.exchange)
    book = exchange.fetch_order_book(args.symbol, limit=args.limit)
    payload = {
        "exchange": args.exchange,
        "symbol": args.symbol,
        "timestamp": book.get("datetime") or book.get("timestamp"),
        "bids": book.get("bids", [])[: args.depth],
        "asks": book.get("asks", [])[: args.depth],
    }
    if args.json:
        print(json.dumps(_clean(payload), indent=2))
        return
    print(f"Order Book: {args.exchange} {args.symbol}")
    print("Bids")
    _print_table([{"price": b[0], "amount": b[1]} for b in payload["bids"]], ["price", "amount"])
    print("\nAsks")
    _print_table([{"price": a[0], "amount": a[1]} for a in payload["asks"]], ["price", "amount"])


def cmd_candles(args):
    exchange = _make_exchange(args.exchange)
    if not exchange.has.get("fetchOHLCV"):
        fail(f"{args.exchange} does not support fetchOHLCV")
    candles = exchange.fetch_ohlcv(args.symbol, timeframe=args.timeframe, limit=args.limit)
    rows = [
        {
            "timestamp": candle[0],
            "open": candle[1],
            "high": candle[2],
            "low": candle[3],
            "close": candle[4],
            "volume": candle[5],
        }
        for candle in candles
    ]
    if args.json:
        print(json.dumps(_clean(rows), indent=2))
        return
    _print_table(rows, ["timestamp", "open", "high", "low", "close", "volume"])


def cmd_funding(args):
    exchange = _make_exchange(args.exchange)
    if args.symbol:
        if not exchange.has.get("fetchFundingRate"):
            fail(f"{args.exchange} does not support fetchFundingRate")
        payload = exchange.fetch_funding_rate(args.symbol)
        if args.json:
            print(json.dumps(_clean(payload), indent=2))
            return
        rows = [
            {
                "symbol": payload.get("symbol"),
                "fundingRate": payload.get("fundingRate"),
                "nextFundingRate": payload.get("nextFundingRate"),
                "markPrice": payload.get("markPrice"),
                "indexPrice": payload.get("indexPrice"),
                "datetime": payload.get("datetime"),
            }
        ]
        _print_table(rows, ["symbol", "fundingRate", "nextFundingRate", "markPrice", "indexPrice", "datetime"])
        return
    if not exchange.has.get("fetchFundingRates"):
        fail(f"{args.exchange} does not support fetchFundingRates")
    rows = list(exchange.fetch_funding_rates().values())
    rows = sorted(rows, key=lambda row: row.get("symbol") or "")[: args.limit]
    if args.json:
        print(json.dumps(_clean(rows), indent=2))
        return
    _print_table(
        [
            {
                "symbol": row.get("symbol"),
                "fundingRate": row.get("fundingRate"),
                "nextFundingRate": row.get("nextFundingRate"),
                "markPrice": row.get("markPrice"),
            }
            for row in rows
        ],
        ["symbol", "fundingRate", "nextFundingRate", "markPrice"],
    )


def cmd_snapshot(args):
    exchange = _make_exchange(args.exchange)
    payload = {"exchange": args.exchange, "symbols": {}}
    for symbol in args.symbols:
        payload["symbols"][symbol] = {
            "ticker": _clean(exchange.fetch_ticker(symbol)),
            "orderBook": _clean(exchange.fetch_order_book(symbol, limit=args.book_limit)),
        }
        if exchange.has.get("fetchOHLCV"):
            payload["symbols"][symbol]["candles"] = _clean(
                exchange.fetch_ohlcv(symbol, timeframe=args.timeframe, limit=args.candle_limit)
            )
    if args.output:
        _write_json(args.output, payload)
    if args.json or not args.output:
        print(json.dumps(_clean(payload), indent=2))


def main():
    parser = argparse.ArgumentParser(description="Deterministic crypto exchange CLI via ccxt")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("exchanges", help="List supported ccxt exchange ids")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_exchanges)

    p = subparsers.add_parser("markets", help="List markets on one exchange")
    p.add_argument("exchange")
    p.add_argument("--quote", help="Filter by quote currency")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_markets)

    p = subparsers.add_parser("ticker", help="Fetch one ticker")
    p.add_argument("exchange")
    p.add_argument("symbol")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_ticker)

    p = subparsers.add_parser("book", help="Fetch an order book")
    p.add_argument("exchange")
    p.add_argument("symbol")
    p.add_argument("--limit", type=int, default=20, help="Exchange fetch limit")
    p.add_argument("--depth", type=int, default=10, help="Levels to print")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_book)

    p = subparsers.add_parser("candles", help="Fetch OHLCV candles")
    p.add_argument("exchange")
    p.add_argument("symbol")
    p.add_argument("--timeframe", default="1h")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_candles)

    p = subparsers.add_parser("funding", help="Fetch one or many funding rates")
    p.add_argument("exchange")
    p.add_argument("symbol", nargs="?")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_funding)

    p = subparsers.add_parser("snapshot", help="Capture ticker/book/candle snapshot for symbols")
    p.add_argument("exchange")
    p.add_argument("symbols", nargs="+")
    p.add_argument("--timeframe", default="1h")
    p.add_argument("--book-limit", type=int, default=10)
    p.add_argument("--candle-limit", type=int, default=10)
    p.add_argument("--output")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_snapshot)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
