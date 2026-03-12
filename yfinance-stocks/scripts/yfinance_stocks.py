#!/usr/bin/env python3
"""Deterministic stock market CLI built on yfinance."""

import argparse
import json
import math
from pathlib import Path
import sys

try:
    import yfinance as yf
except ImportError as exc:  # pragma: no cover - depends on local environment
    print("ERROR: yfinance is not installed. Install it with `python -m pip install yfinance`.", file=sys.stderr)
    raise SystemExit(1) from exc


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def _clean(value):
    if hasattr(value, "items") and not isinstance(value, dict):
        try:
            value = dict(value)
        except Exception:
            pass
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


def _frame_records(frame, limit=None):
    if frame is None or frame.empty:
        return []
    if limit:
        frame = frame.tail(limit)
    records = []
    for idx, row in frame.iterrows():
        record = {"Date": idx.isoformat() if hasattr(idx, "isoformat") else str(idx)}
        for column, value in row.items():
            record[str(column)] = _clean(value.item() if hasattr(value, "item") else value)
        records.append(record)
    return records


def _print_table(rows, columns):
    if not rows:
        print("No rows")
        return
    widths = {col: len(col) for col in columns}
    for row in rows:
        for col in columns:
            widths[col] = max(widths[col], len(str(row.get(col, ""))))
    header = "  ".join(f"{col:<{widths[col]}}" for col in columns)
    print(header)
    print("  ".join("-" * widths[col] for col in columns))
    for row in rows:
        print("  ".join(f"{str(row.get(col, '')):<{widths[col]}}" for col in columns))


def _ticker(symbol):
    return yf.Ticker(symbol.upper())


def cmd_quote(args):
    rows = []
    for symbol in args.symbols:
        ticker = _ticker(symbol)
        info = ticker.fast_info or {}
        history = ticker.history(period="5d", interval="1d", auto_adjust=False)
        last_close = None
        prev_close = None
        if history is not None and not history.empty:
            closes = history["Close"].dropna().tolist()
            if closes:
                last_close = closes[-1]
                prev_close = closes[-2] if len(closes) > 1 else None
        change = None
        change_pct = None
        if last_close is not None and prev_close not in (None, 0):
            change = last_close - prev_close
            change_pct = (change / prev_close) * 100
        rows.append(
            {
                "symbol": symbol.upper(),
                "price": _clean(info.get("lastPrice", last_close)),
                "previousClose": _clean(info.get("previousClose", prev_close)),
                "change": _clean(change),
                "changePct": _clean(change_pct),
                "open": _clean(info.get("open")),
                "dayHigh": _clean(info.get("dayHigh")),
                "dayLow": _clean(info.get("dayLow")),
                "volume": _clean(info.get("lastVolume")),
                "marketCap": _clean(info.get("marketCap")),
                "currency": _clean(info.get("currency")),
                "exchange": _clean(info.get("exchange")),
            }
        )
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    _print_table(
        rows,
        ["symbol", "price", "change", "changePct", "open", "dayHigh", "dayLow", "volume", "marketCap"],
    )


def cmd_history(args):
    ticker = _ticker(args.symbol)
    frame = ticker.history(
        period=args.period,
        interval=args.interval,
        start=args.start,
        end=args.end,
        auto_adjust=args.auto_adjust,
    )
    records = _frame_records(frame, limit=args.limit)
    if args.csv:
        frame.tail(args.limit if args.limit else len(frame)).to_csv(args.csv)
    if args.json:
        print(json.dumps(records, indent=2))
        return
    _print_table(records, ["Date", "Open", "High", "Low", "Close", "Volume"])


def cmd_info(args):
    ticker = _ticker(args.symbol)
    info = _clean(ticker.info or {})
    if args.keys:
        info = {key: info.get(key) for key in args.keys}
    if args.json:
        print(json.dumps(info, indent=2))
        return
    rows = [{"key": key, "value": value} for key, value in sorted(info.items())]
    _print_table(rows, ["key", "value"])


def cmd_financials(args):
    ticker = _ticker(args.symbol)
    statement_map = {
        ("income", "annual"): ticker.financials,
        ("income", "quarterly"): ticker.quarterly_financials,
        ("balance", "annual"): ticker.balance_sheet,
        ("balance", "quarterly"): ticker.quarterly_balance_sheet,
        ("cashflow", "annual"): ticker.cashflow,
        ("cashflow", "quarterly"): ticker.quarterly_cashflow,
    }
    frame = statement_map[(args.statement, args.frequency)]
    if frame is None or frame.empty:
        fail("No financial statement data returned")
    records = []
    for metric, row in frame.iterrows():
        item = {"metric": str(metric)}
        for column, value in row.items():
            col_name = column.date().isoformat() if hasattr(column, "date") else str(column)
            item[col_name] = _clean(value.item() if hasattr(value, "item") else value)
        records.append(item)
    if args.limit:
        records = records[: args.limit]
    if args.json:
        print(json.dumps(records, indent=2))
        return
    columns = ["metric"] + [col for col in records[0].keys() if col != "metric"]
    _print_table(records, columns)


def cmd_options(args):
    ticker = _ticker(args.symbol)
    expirations = list(ticker.options or [])
    if not expirations:
        fail("No option expirations returned")
    if args.expiration:
        if args.expiration not in expirations:
            fail(f"Expiration {args.expiration} not found")
        chain = ticker.option_chain(args.expiration)
        payload = {
            "symbol": args.symbol.upper(),
            "expiration": args.expiration,
            "calls": _frame_records(chain.calls, limit=args.limit),
            "puts": _frame_records(chain.puts, limit=args.limit),
        }
    else:
        payload = {"symbol": args.symbol.upper(), "expirations": expirations}
    if args.json:
        print(json.dumps(_clean(payload), indent=2))
        return
    if "expirations" in payload:
        for expiration in payload["expirations"]:
            print(expiration)
        return
    print("Calls")
    _print_table(payload["calls"], ["Date", "strike", "lastPrice", "bid", "ask", "volume", "openInterest"])
    print("\nPuts")
    _print_table(payload["puts"], ["Date", "strike", "lastPrice", "bid", "ask", "volume", "openInterest"])


def cmd_snapshot(args):
    payload = {"symbols": {}, "period": args.period, "interval": args.interval}
    for symbol in args.symbols:
        ticker = _ticker(symbol)
        payload["symbols"][symbol.upper()] = {
            "quote": _clean(dict(ticker.fast_info or {})),
            "info": _clean(ticker.info or {}),
            "history": _frame_records(ticker.history(period=args.period, interval=args.interval, auto_adjust=False), limit=args.limit),
            "options": list(ticker.options or []),
        }
    if args.output:
        _write_json(args.output, payload)
    if args.json or not args.output:
        print(json.dumps(payload, indent=2))


def cmd_news(args):
    rows = []
    seen = set()
    for symbol in args.symbols:
        ticker = _ticker(symbol)
        try:
            items = ticker.news or []
        except Exception as exc:
            rows.append({"symbol": symbol.upper(), "error": str(exc)})
            continue
        for item in items[: args.limit]:
            content = item.get("content") or {}
            title = content.get("title")
            url = ((content.get("canonicalUrl") or {}).get("url") or (content.get("clickThroughUrl") or {}).get("url"))
            key = (title, url)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "symbol": symbol.upper(),
                    "title": title,
                    "summary": content.get("summary"),
                    "provider": (content.get("provider") or {}).get("displayName"),
                    "publishedAt": content.get("pubDate") or content.get("displayTime"),
                    "url": url,
                    "contentType": content.get("contentType"),
                }
            )
    rows = sorted(rows, key=lambda row: row.get("publishedAt") or "", reverse=True)
    if args.json:
        print(json.dumps(rows[: args.limit], indent=2))
        return
    _print_table(rows[: args.limit], ["publishedAt", "symbol", "provider", "title"])


def main():
    parser = argparse.ArgumentParser(description="Deterministic stock CLI via yfinance")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("quote", help="Get compact quote data for one or more symbols")
    p.add_argument("symbols", nargs="+")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_quote)

    p = subparsers.add_parser("history", help="Get OHLCV history for one symbol")
    p.add_argument("symbol")
    p.add_argument("--period", default="1mo")
    p.add_argument("--interval", default="1d")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--auto-adjust", action="store_true")
    p.add_argument("--csv")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_history)

    p = subparsers.add_parser("info", help="Get company metadata fields")
    p.add_argument("symbol")
    p.add_argument("--keys", nargs="*")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_info)

    p = subparsers.add_parser("financials", help="Get financial statement rows")
    p.add_argument("symbol")
    p.add_argument("--statement", choices=["income", "balance", "cashflow"], default="income")
    p.add_argument("--frequency", choices=["annual", "quarterly"], default="annual")
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_financials)

    p = subparsers.add_parser("options", help="List expirations or inspect an option chain")
    p.add_argument("symbol")
    p.add_argument("--expiration", help="YYYY-MM-DD expiration to inspect")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_options)

    p = subparsers.add_parser("snapshot", help="Capture a JSON snapshot for one or more symbols")
    p.add_argument("symbols", nargs="+")
    p.add_argument("--period", default="1mo")
    p.add_argument("--interval", default="1d")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--output")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_snapshot)

    p = subparsers.add_parser("news", help="Fetch recent Yahoo Finance news items")
    p.add_argument("symbols", nargs="+")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_news)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
