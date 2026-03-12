#!/usr/bin/env python3
"""Generate a Telegram-formatted morning market update from local skills."""

import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
HYPERLIQUID = ROOT / "hyperliquid" / "scripts" / "hyperliquid.py"
YFINANCE = ROOT / "yfinance-stocks" / "scripts" / "yfinance_stocks.py"
CCXT = ROOT / "ccxt-exchanges" / "scripts" / "ccxt_exchanges.py"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"

DEFAULT_BASKET = {
    "crypto": [
        {"label": "BTC", "source": "crypto", "hl": "BTC", "exchange": "binance", "ccxt_symbol": "BTC/USDT", "digits": 2, "prefix": "$"},
        {"label": "ETH", "source": "crypto", "hl": "ETH", "exchange": "binance", "ccxt_symbol": "ETH/USDT", "digits": 2, "prefix": "$"},
        {"label": "SOL", "source": "crypto", "hl": "SOL", "exchange": "binance", "ccxt_symbol": "SOL/USDT", "digits": 2, "prefix": "$"},
    ],
    "stocks": [
        {"label": "SPX", "source": "yfinance", "symbol": "^GSPC", "digits": 2},
        {"label": "NDX", "source": "yfinance", "symbol": "^NDX", "digits": 2},
        {"label": "DJI", "source": "yfinance", "symbol": "^DJI", "digits": 2},
        {"label": "RUT", "source": "yfinance", "symbol": "^RUT", "digits": 2},
        {"label": "VIX", "source": "yfinance", "symbol": "^VIX", "digits": 2},
    ],
    "forex": [
        {"label": "DXY", "source": "yfinance", "symbol": "DX-Y.NYB", "digits": 2},
        {"label": "EUR/USD", "source": "yfinance", "symbol": "EURUSD=X", "digits": 4},
        {"label": "GBP/USD", "source": "yfinance", "symbol": "GBPUSD=X", "digits": 4},
        {"label": "USD/JPY", "source": "yfinance", "symbol": "JPY=X", "digits": 3},
        {"label": "USD/CHF", "source": "yfinance", "symbol": "CHF=X", "digits": 4},
    ],
    "commodities": [
        {"label": "Gold", "source": "yfinance", "symbol": "GC=F", "digits": 2, "prefix": "$"},
        {"label": "Silver", "source": "yfinance", "symbol": "SI=F", "digits": 2, "prefix": "$"},
        {"label": "Oil", "source": "yfinance", "symbol": "CL=F", "digits": 2, "prefix": "$"},
        {"label": "Nat Gas", "source": "yfinance", "symbol": "NG=F", "digits": 2, "prefix": "$"},
        {"label": "Copper", "source": "yfinance", "symbol": "HG=F", "digits": 2, "prefix": "$"},
    ],
}

EXTRA_FIELD_PRESETS = {
    "TOTAL3": {"label": "TOTAL3", "source": "coingecko", "metric": "total3_usd", "digits": 0, "prefix": "$"},
    "BTCDOM": {"label": "BTC Dom", "source": "coingecko", "metric": "btc_dominance", "digits": 1, "suffix": "%"},
    "US10Y": {"label": "US10Y", "source": "yfinance", "symbol": "^TNX", "digits": 2, "suffix": "%"},
    "MOVE": {"label": "MOVE", "source": "yfinance", "symbol": "^MOVE", "digits": 2},
}

SECTION_TITLES = {
    "crypto": "CRYPTO",
    "stocks": "STOCKS",
    "forex": "FOREX",
    "commodities": "COMMODITIES",
    "extras": "EXTRAS",
}


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def run_json(script_path, *args):
    cmd = [sys.executable, str(script_path), *args, "--json"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"Command failed: {' '.join(cmd)}")
    return json.loads(proc.stdout)


def format_change(value):
    if value is None:
        return "[N/A]"
    return f"{value:+.1f}%"


def format_price(value, digits=2, prefix="", suffix=""):
    if value is None:
        return "[N/A]"
    return f"{prefix}{value:,.{digits}f}{suffix}"


def get_session_label(now_utc):
    hour = now_utc.hour
    if 0 <= hour < 8:
        return "Asia Session"
    if 8 <= hour < 13:
        return "Europe Session"
    if 13 <= hour < 21:
        return "US Session"
    return "After Hours"


def _cache_key(basket, change_mode):
    payload = json.dumps({"basket": basket, "change_mode": change_mode}, sort_keys=True).encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:16]


def _load_cache(path, cache_minutes):
    if cache_minutes <= 0 or not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    fetched_at = dt.datetime.fromisoformat(data["fetchedAt"])
    age = dt.datetime.now(dt.timezone.utc) - fetched_at
    if age.total_seconds() <= cache_minutes * 60:
        return data["payload"]
    return None


def _write_cache(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    wrapper = {
        "fetchedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "payload": payload,
    }
    path.write_text(json.dumps(wrapper, indent=2), encoding="utf-8")


def load_symbols_config(path):
    if not path:
        return copy.deepcopy(DEFAULT_BASKET)
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if "sections" in payload:
        payload = payload["sections"]
    if not isinstance(payload, dict):
        fail("symbols file must be a JSON object with section arrays")
    return payload


def with_extra_fields(basket, extra_fields):
    out = copy.deepcopy(basket)
    if extra_fields:
        out.setdefault("extras", [])
        for field in extra_fields:
            out["extras"].append(copy.deepcopy(EXTRA_FIELD_PRESETS[field]))
    return out


def compute_change(item, row, price, mode):
    if row is None:
        return None
    if mode == "24h":
        return row.get("changePct")
    open_price = row.get("open")
    if open_price in (None, 0):
        return None
    return ((price - open_price) / open_price) * 100


def fetch_yfinance_rows(items):
    if not items:
        return {}
    symbols = [item["symbol"] for item in items]
    rows = {}
    try:
        quote_rows = run_json(YFINANCE, "quote", *symbols)
        rows.update({row["symbol"]: row for row in quote_rows})
        return rows
    except Exception:
        pass
    for item in items:
        try:
            quote_rows = run_json(YFINANCE, "quote", item["symbol"])
            if quote_rows:
                rows[quote_rows[0]["symbol"]] = quote_rows[0]
        except Exception:
            rows[item["symbol"].upper()] = {}
    return rows


def fetch_coingecko_global():
    with urllib.request.urlopen("https://api.coingecko.com/api/v3/global", timeout=20) as response:
        return json.load(response).get("data", {})


def fetch_entry(item, change_mode, coingecko_data=None, yfinance_rows=None):
    if item["source"] == "crypto":
        hl = run_json(HYPERLIQUID, "ticker", item["hl"])
        ccxt = run_json(CCXT, "ticker", item["exchange"], item["ccxt_symbol"])
        price = hl.get("mid") or ccxt.get("last")
        if change_mode == "24h":
            change = ccxt.get("percentage")
        else:
            open_price = ccxt.get("open")
            change = None if open_price in (None, 0) else ((price - open_price) / open_price) * 100
        return {"label": item["label"], "price": price, "changePct": change, **item}
    if item["source"] == "yfinance":
        row = (yfinance_rows or {}).get(item["symbol"].upper(), {})
        price = row.get("price")
        change = compute_change(item, row, price, change_mode)
        return {"label": item["label"], "price": price, "changePct": change, **item}
    if item["source"] == "coingecko":
        data = coingecko_data or {}
        if item["metric"] == "btc_dominance":
            price = ((data.get("market_cap_percentage") or {}).get("btc"))
        elif item["metric"] == "total3_usd":
            total = ((data.get("total_market_cap") or {}).get("usd"))
            percentages = data.get("market_cap_percentage") or {}
            btc_pct = percentages.get("btc", 0) / 100
            eth_pct = percentages.get("eth", 0) / 100
            price = total * (1 - btc_pct - eth_pct) if total is not None else None
        else:
            price = None
        return {"label": item["label"], "price": price, "changePct": None, **item}
    return {"label": item["label"], "price": None, "changePct": None, **item}


def build_data(basket, change_mode):
    needs_coingecko = any(item.get("source") == "coingecko" for items in basket.values() for item in items)
    coingecko_data = fetch_coingecko_global() if needs_coingecko else None
    yfinance_items = [item for items in basket.values() for item in items if item.get("source") == "yfinance"]
    yfinance_rows = fetch_yfinance_rows(yfinance_items)
    data = {}
    for section, items in basket.items():
        rows = []
        for item in items:
            rows.append(fetch_entry(item, change_mode, coingecko_data=coingecko_data, yfinance_rows=yfinance_rows))
        data[section] = rows
    return data


def get_data(basket, change_mode, cache_minutes):
    cache_path = CACHE_DIR / f"{_cache_key(basket, change_mode)}.json"
    cached = _load_cache(cache_path, cache_minutes)
    if cached is not None:
        return cached
    payload = build_data(basket, change_mode)
    _write_cache(cache_path, payload)
    return payload


def render_section(section_name, rows):
    label_width = max(len(row["label"]) for row in rows)
    price_strings = [format_price(row["price"], row.get("digits", 2), row.get("prefix", ""), row.get("suffix", "")) for row in rows]
    change_strings = [format_change(row["changePct"]) if row.get("changePct") is not None else "" for row in rows]
    price_width = max(len(value) for value in price_strings)
    change_width = max(len(value) for value in change_strings)
    lines = [f"── {SECTION_TITLES.get(section_name, section_name.upper())} ──"]
    for row, price_str, change_str in zip(rows, price_strings, change_strings):
        if change_str:
            lines.append(f"{row['label']:<{label_width}}  {price_str:>{price_width}}  ({change_str:>{change_width}})")
        else:
            lines.append(f"{row['label']:<{label_width}}  {price_str:>{price_width}}")
    return "\n".join(lines)


def render_update(data, args):
    now = dt.datetime.now()
    header = f"📅 Morning Market Update — {now.strftime('%B %d, %Y')}"
    if args.session_label:
        header += f" [{get_session_label(dt.datetime.now(dt.timezone.utc))}]"
    body_sections = []
    for section in ("crypto", "stocks", "forex", "commodities", "extras"):
        rows = data.get(section) or []
        if rows:
            body_sections.append(render_section(section, rows))
    body = "\n\n".join(body_sections)
    return f"{header}\n```text\n{body}\n```"


def main():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Generate a Telegram-formatted morning market update")
    parser.add_argument("--output", help="Write the rendered update to a file")
    parser.add_argument("--json", action="store_true", help="Print the collected data as JSON instead of the formatted update")
    parser.add_argument("--symbols-file", help="Path to a JSON basket definition")
    parser.add_argument("--cache-minutes", type=int, default=0, help="Reuse cached data for this many minutes")
    parser.add_argument("--change-mode", choices=["24h", "since-open"], default="24h", help="Use 24h change or since-open change")
    parser.add_argument("--session-label", action="store_true", help="Append an Asia/Europe/US session label to the header")
    parser.add_argument("--extra-fields", nargs="*", choices=sorted(EXTRA_FIELD_PRESETS.keys()), default=[], help="Optional extra macro or breadth fields")
    args = parser.parse_args()

    for path in (HYPERLIQUID, YFINANCE, CCXT):
        if not path.exists():
            fail(f"Required script not found: {path}")

    basket = with_extra_fields(load_symbols_config(args.symbols_file), args.extra_fields)
    data = get_data(basket, args.change_mode, args.cache_minutes)
    if args.json:
        print(json.dumps(data, indent=2))
        return

    update = render_update(data, args)
    if args.output:
        Path(args.output).write_text(update, encoding="utf-8")
    print(update)


if __name__ == "__main__":
    main()
