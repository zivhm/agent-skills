#!/usr/bin/env python3
"""Hyperliquid public API helper.

Implements a few high-signal endpoints via POST https://api.hyperliquid.xyz/info

This is intentionally small and dependency-light.
"""

import argparse
import datetime as dt
import json
from pathlib import Path
import sys
import urllib.request

DEFAULT_BASE_URL = "https://api.hyperliquid.xyz"


def _post_json(url: str, payload: dict, timeout: int = 20):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        # Include response body to make debugging API shape changes easy.
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        raise RuntimeError(f"HTTP {e.code}: {body.strip()}")


def hl_info(base_url: str, payload: dict, timeout: int = 20):
    return _post_json(base_url.rstrip("/") + "/info", payload, timeout=timeout)


def _normalize_coin(coin: str):
    return coin if ":" in coin else coin.upper()


def _write_json(path: str, payload):
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _load_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _iso_now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _safe_float(value, default=None):
    try:
        return float(value)
    except Exception:
        return default


def _summarize_diff(before, after):
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        keys = sorted(set(before) | set(after))
        out = []
        for key in keys:
            out.extend(_summarize_diff(before.get(key), after.get(key)))
        return out
    return [{"before": before, "after": after}]


def _json_diff(before, after, path="root"):
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in sorted(set(before) | set(after)):
            next_path = f"{path}.{key}"
            if key not in before:
                changes.append({"path": next_path, "before": None, "after": after[key]})
            elif key not in after:
                changes.append({"path": next_path, "before": before[key], "after": None})
            else:
                changes.extend(_json_diff(before[key], after[key], next_path))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        if before == after:
            return []
        return [{"path": path, "before_len": len(before), "after_len": len(after), "changes": _summarize_diff(before, after)[:5]}]
    return [{"path": path, "before": before, "after": after}]


def _meta_ctx_map(base_url: str, timeout: int):
    out = hl_info(base_url, {"type": "metaAndAssetCtxs"}, timeout=timeout)
    if not isinstance(out, list) or len(out) < 2:
        return {}
    meta, ctxs = out[0], out[1]
    universe = (meta or {}).get("universe", [])
    mapping = {}
    for asset, ctx in zip(universe, ctxs):
        name = asset.get("name")
        if name:
            mapping[name] = ctx or {}
    return mapping


def cmd_mids(args):
    out = hl_info(args.base_url, {"type": "allMids"}, timeout=args.timeout)
    return out


def cmd_meta(args):
    out = hl_info(args.base_url, {"type": "meta"}, timeout=args.timeout)
    return out


def cmd_book(args):
    # coin: string symbol like BTC, ETH, SOL, or xyz:PLATINUM for HIP-3 dex markets
    # Preserve case for HIP-3 dex markets (xyz:COIN), uppercase for regular coins
    coin = _normalize_coin(args.coin)
    out = hl_info(args.base_url, {"type": "l2Book", "coin": coin}, timeout=args.timeout)
    return out


def cmd_meta_ctx(args):
    return hl_info(args.base_url, {"type": "metaAndAssetCtxs"}, timeout=args.timeout)


def cmd_markets(args):
    """List all available markets including main perps and HIP-3 dex markets."""
    # Get main perps universe
    meta = hl_info(args.base_url, {"type": "meta"}, timeout=args.timeout) or {}
    universe = meta.get("universe", [])
    main_coins = [a.get("name") for a in universe if a.get("name")]

    # Get HIP-3 perp dexs
    dexs = hl_info(args.base_url, {"type": "perpDexs"}, timeout=args.timeout) or []

    # Get mid prices for context
    mids = hl_info(args.base_url, {"type": "allMids"}, timeout=args.timeout) or {}

    result = {
        "main": sorted(main_coins),
        "dexs": {},
        "mids": mids,
    }

    # Get markets for each HIP-3 dex
    if isinstance(dexs, list) and len(dexs) > 1:
        for d in dexs[1:]:
            if not isinstance(d, dict):
                continue
            dex_name = d.get("name")
            if not dex_name:
                continue
            # Try to get dex metadata
            try:
                dex_meta = hl_info(args.base_url, {"type": "meta", "dex": dex_name}, timeout=args.timeout) or {}
                dex_universe = dex_meta.get("universe", [])
                dex_coins = [a.get("name") for a in dex_universe if a.get("name")]
                if dex_coins:
                    result["dexs"][dex_name] = sorted(dex_coins)
            except Exception:
                # Some dexs might not support meta endpoint
                result["dexs"][dex_name] = []

    return result


def cmd_predicted_funding(args):
    return hl_info(args.base_url, {"type": "predictedFundings"}, timeout=args.timeout)


def cmd_open_orders(args):
    user = args.address.lower()
    return _open_orders(args.base_url, user, args.timeout)


def cmd_candles(args):
    # interval examples: 1m, 5m, 15m, 1h, 4h, 1d
    payload = {
        "type": "candleSnapshot",
        "req": {
            "coin": args.coin.upper(),
            "interval": args.interval,
            "startTime": args.start,
            "endTime": args.end,
        },
    }
    out = hl_info(args.base_url, payload, timeout=args.timeout)
    if args.limit and isinstance(out, list):
        out = out[-args.limit :]
    return out


def cmd_ticker(args):
    coin = _normalize_coin(args.coin)
    book = hl_info(args.base_url, {"type": "l2Book", "coin": coin}, timeout=args.timeout) or {}
    mids = hl_info(args.base_url, {"type": "allMids"}, timeout=args.timeout) or {}
    ctx_map = _meta_ctx_map(args.base_url, args.timeout)
    base_coin = coin.split(":", 1)[-1]
    ctx = ctx_map.get(base_coin, {})
    bids = (book.get("levels") or [[], []])[0]
    asks = (book.get("levels") or [[], []])[1]
    best_bid = _safe_float((bids[0] if bids else {}).get("px"))
    best_ask = _safe_float((asks[0] if asks else {}).get("px"))
    mid = _safe_float(mids.get(base_coin))
    spread = None
    spread_bps = None
    if best_bid is not None and best_ask is not None:
        spread = best_ask - best_bid
        center = ((best_ask + best_bid) / 2) or None
        if center:
            spread_bps = (spread / center) * 10_000
    return {
        "coin": coin,
        "mid": mid,
        "bestBid": best_bid,
        "bestAsk": best_ask,
        "spread": spread,
        "spreadBps": spread_bps,
        "markPx": _safe_float(ctx.get("markPx")),
        "oraclePx": _safe_float(ctx.get("oraclePx")),
        "funding": _safe_float(ctx.get("funding")),
        "openInterest": _safe_float(ctx.get("openInterest")),
        "dayNtlVlm": _safe_float(ctx.get("dayNtlVlm")),
        "premium": _safe_float(ctx.get("premium")),
        "timestamp": _iso_now(),
    }


def cmd_scan_funding(args):
    ctx_map = _meta_ctx_map(args.base_url, args.timeout)
    rows = []
    for coin, ctx in ctx_map.items():
        funding = _safe_float(ctx.get("funding"))
        if funding is None:
            continue
        rows.append(
            {
                "coin": coin,
                "funding": funding,
                "markPx": _safe_float(ctx.get("markPx")),
                "openInterest": _safe_float(ctx.get("openInterest")),
                "dayNtlVlm": _safe_float(ctx.get("dayNtlVlm")),
            }
        )
    rows.sort(key=lambda item: item["funding"], reverse=not args.lowest)
    return {"generatedAt": _iso_now(), "rows": rows[: args.limit]}


def cmd_snapshot(args):
    payload = {
        "generatedAt": _iso_now(),
        "baseUrl": args.base_url,
        "mids": hl_info(args.base_url, {"type": "allMids"}, timeout=args.timeout) or {},
        "metaCtx": hl_info(args.base_url, {"type": "metaAndAssetCtxs"}, timeout=args.timeout) or {},
    }
    if args.include_funding:
        payload["predictedFunding"] = hl_info(args.base_url, {"type": "predictedFundings"}, timeout=args.timeout) or {}
    if args.addresses:
        payload["users"] = {}
        for address in args.addresses:
            user = address.lower()
            payload["users"][user] = {
                "perps": hl_info(args.base_url, {"type": "clearinghouseState", "user": user}, timeout=args.timeout) or {},
                "spot": hl_info(args.base_url, {"type": "spotClearinghouseState", "user": user}, timeout=args.timeout) or {},
                "openOrders": _open_orders(args.base_url, user, args.timeout),
            }
    if args.output:
        _write_json(args.output, payload)
    if args.json or not args.output:
        return payload
    return None


def cmd_diff(args):
    before = _load_json(args.before)
    after = _load_json(args.after)
    return {"before": args.before, "after": args.after, "changes": _json_diff(before, after)}


def _nonzero_positions(ch_state: dict):
    aps = (ch_state or {}).get("assetPositions") or []
    out = []
    for ap in aps:
        try:
            if abs(float(ap["position"]["szi"])) > 1e-12:
                out.append(ap)
        except Exception:
            continue
    return out


def _fmt_usd(x):
    try:
        v = float(x)
    except Exception:
        return str(x)
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if abs(v) >= 1_000:
        return f"${v/1_000:.2f}K"
    return f"${v:.2f}"


def _fmt_num(x, dp=4):
    try:
        v = float(x)
    except Exception:
        return str(x)
    return f"{v:.{dp}f}"


def _open_orders(base_url: str, user: str, timeout: int, dex: str | None = None):
    payload = {"type": "openOrders", "user": user}
    if dex:
        payload["dex"] = dex
    return hl_info(base_url, payload, timeout=timeout) or []


def cmd_user(args):
    # Hyperliquid expects lowercase for some address-sensitive endpoints.
    user = args.address.lower()

    # Perps account state (main dex)
    perps_main = hl_info(args.base_url, {"type": "clearinghouseState", "user": user}, timeout=args.timeout)

    # HIP-3 perp dexs may hold positions under a separate "dex" namespace.
    perps_dexs = []
    if args.all_dexs:
        dexs = hl_info(args.base_url, {"type": "perpDexs"}, timeout=args.timeout) or []
        for d in dexs[1:]:
            if not d or not isinstance(d, dict) or "name" not in d:
                continue
            name = d["name"]
            try:
                st = hl_info(
                    args.base_url,
                    {"type": "clearinghouseState", "user": user, "dex": name},
                    timeout=args.timeout,
                )
            except Exception:
                continue
            if _nonzero_positions(st):
                perps_dexs.append({"dex": name, "state": st})

    # Spot balances (if any)
    spot = hl_info(args.base_url, {"type": "spotClearinghouseState", "user": user}, timeout=args.timeout)

    return {"user": user, "perps": {"main": perps_main, "dexs": perps_dexs}, "spot": spot}


def cmd_dash(args):
    # Hyperdash-style scannable summary. Default behavior: include HIP-3 dexs.
    mids = hl_info(args.base_url, {"type": "allMids"}, timeout=args.timeout) or {}
    dexs = None
    if not args.main_only:
        dexs = hl_info(args.base_url, {"type": "perpDexs"}, timeout=args.timeout) or []

    for addr in args.addresses:
        user = addr.lower()
        perps_main = hl_info(args.base_url, {"type": "clearinghouseState", "user": user}, timeout=args.timeout)
        spot = hl_info(args.base_url, {"type": "spotClearinghouseState", "user": user}, timeout=args.timeout) or {}
        oo_main = _open_orders(args.base_url, user, args.timeout)

        print(f"👤 {user}")

        ms = (perps_main or {}).get("marginSummary") or {}
        cms = (perps_main or {}).get("crossMarginSummary") or {}
        print(
            "📌 Perps (main)",
            f"• AV {_fmt_usd(cms.get('accountValue', ms.get('accountValue', '?')))}",
            f"• Notional {_fmt_usd(cms.get('totalNtlPos', ms.get('totalNtlPos', '?')))}",
            f"• Used {_fmt_usd(cms.get('totalMarginUsed', ms.get('totalMarginUsed', '?')))}",
            f"• W/d {_fmt_usd((perps_main or {}).get('withdrawable', '?'))}",
            sep="\n",
        )

        aps = _nonzero_positions(perps_main)
        if aps:
            print("📍 Positions (main)")
            for ap in aps[: args.limit_positions]:
                p = ap.get("position", {})
                coin = p.get("coin")
                szi = float(p.get("szi", 0))
                side = "Long" if szi > 0 else "Short"
                entry = p.get("entryPx")
                upnl = p.get("unrealizedPnl")
                liq = p.get("liquidationPx")
                base_coin = coin.split(":", 1)[-1] if isinstance(coin, str) else None
                mark = mids.get(base_coin) if base_coin else None
                print(
                    "  •",
                    f"{coin}",
                    f"({side} {_fmt_num(abs(szi), 4)})",
                    f"entry {_fmt_num(entry, 2)}",
                    f"mark {_fmt_num(mark, 2) if mark else '~'}",
                    f"uPnL {_fmt_usd(upnl)}",
                    f"liq {_fmt_num(liq, 2) if liq else '-'}",
                )
        else:
            print("📍 Positions (main): none")

        # HIP-3 scan
        if dexs and isinstance(dexs, list):
            for d in dexs[1:]:
                if not isinstance(d, dict) or "name" not in d:
                    continue
                name = d["name"]
                try:
                    st = hl_info(
                        args.base_url,
                        {"type": "clearinghouseState", "user": user, "dex": name},
                        timeout=args.timeout,
                    )
                except Exception:
                    continue

                pos = _nonzero_positions(st)
                oo = []
                if args.include_orders:
                    try:
                        oo = _open_orders(args.base_url, user, args.timeout, dex=name)
                    except Exception:
                        oo = []

                if not pos and not oo:
                    continue

                ms = (st or {}).get("marginSummary") or {}
                print(
                    f"🧬 Perps (dex: {name})",
                    f"• AV {_fmt_usd(ms.get('accountValue','?'))}",
                    f"• Notional {_fmt_usd(ms.get('totalNtlPos','?'))}",
                    sep="\n",
                )
                if pos:
                    for ap in pos[: args.limit_positions]:
                        p = ap.get("position", {})
                        coin = p.get("coin")
                        szi = float(p.get("szi", 0))
                        side = "Long" if szi > 0 else "Short"
                        entry = p.get("entryPx")
                        upnl = p.get("unrealizedPnl")
                        liq = p.get("liquidationPx")
                        base_coin = coin.split(":", 1)[-1] if isinstance(coin, str) else None
                        mark = mids.get(base_coin) if base_coin else None
                        print(
                            "  •",
                            f"{coin}",
                            f"({side} {_fmt_num(abs(szi), 4)})",
                            f"entry {_fmt_num(entry, 2)}",
                            f"mark {_fmt_num(mark, 2) if mark else '~'}",
                            f"uPnL {_fmt_usd(upnl)}",
                            f"liq {_fmt_num(liq, 2) if liq else '-'}",
                        )
                if args.include_orders:
                    print(f"  • Open orders: {len(oo)}")

        # Spot
        bals = (spot or {}).get("balances") or []
        nz = []
        for b in bals:
            try:
                if float(b.get("total", 0)) != 0:
                    nz.append(b)
            except Exception:
                continue
        if nz:
            top = nz[: args.limit_spot]
            s = ", ".join([f"{b.get('coin')} {_fmt_num(b.get('total'), 6)}" for b in top])
            print(f"💰 Spot: {s}")
        else:
            print("💰 Spot: none")

        # Orders (main)
        if args.include_orders:
            print(f"🧾 Open orders (main): {len(oo_main)}")

        if not args.compact:
            print("")


def _print_book(out: dict, depth: int = 5):
    """Pretty-print order book with spread, mid, and depth."""
    coin = out.get("coin", "Unknown")
    levels = out.get("levels", [[], []])
    bids = levels[0] if len(levels) > 0 else []
    asks = levels[1] if len(levels) > 1 else []

    if not bids or not asks:
        print(f"No order book data for {coin}")
        return

    best_bid_px = float(bids[0].get("px", 0))
    best_ask_px = float(asks[0].get("px", 0))
    mid = (best_bid_px + best_ask_px) / 2
    spread = best_ask_px - best_bid_px
    spread_pct = (spread / mid) * 100 if mid else 0

    print(f"📖 Order Book: {coin}")
    print(f"   Mid: {_fmt_num(mid, 2)} | Spread: {_fmt_num(spread, 2)} ({spread_pct:.3f}%)")
    print()

    # Calculate depth
    bid_depth = sum(float(b.get("sz", 0)) for b in bids[:depth])
    ask_depth = sum(float(a.get("sz", 0)) for a in asks[:depth])

    # Print header
    print(f"{'BIDS':>20} | {'ASKS':<20}")
    print(f"{'Price':>10} {'Size':>9} | {'Size':<9} {'Price':<10}")
    print("-" * 44)

    # Print rows
    for i in range(depth):
        bid = bids[i] if i < len(bids) else {}
        ask = asks[i] if i < len(asks) else {}

        bid_px = bid.get("px", "")
        bid_sz = bid.get("sz", "")
        ask_sz = ask.get("sz", "")
        ask_px = ask.get("px", "")

        bid_str = f"{bid_px:>10} {bid_sz:>9}" if bid_px else " " * 20
        ask_str = f"{ask_sz:<9} {ask_px:<10}" if ask_px else ""

        print(f"{bid_str} | {ask_str}")

    print(f"\n   Top {depth} bid depth: {_fmt_num(bid_depth, 4)}")
    print(f"   Top {depth} ask depth: {_fmt_num(ask_depth, 4)}")


def _print_markets(out: dict):
    """Pretty-print markets listing with main and HIP-3 dex markets."""
    main = out.get("main", [])
    dexs = out.get("dexs", {})
    mids = out.get("mids", {})

    # Main perps
    print(f"📊 Main Perps ({len(main)} markets)")
    print("-" * 60)

    # Print in columns
    cols = 4
    for i in range(0, len(main), cols):
        row = main[i:i+cols]
        row_str = []
        for coin in row:
            price = mids.get(coin, "")
            price_str = f"${_fmt_num(price, 2)}" if price else ""
            row_str.append(f"{coin:12} {price_str:>12}")
        print("  ".join(row_str))

    # HIP-3 dex markets
    if dexs:
        print(f"\n🧬 HIP-3 Perp Dex Markets")
        print("-" * 60)
        for dex_name, coins in dexs.items():
            if coins:
                print(f"\n  {dex_name} ({len(coins)} markets):")
                # Print in columns
                for i in range(0, len(coins), cols):
                    row = coins[i:i+cols]
                    row_str = []
                    for coin in row:
                        base = coin.split(":")[-1] if ":" in coin else coin
                        price = mids.get(base, "")
                        price_str = f"${_fmt_num(price, 2)}" if price else ""
                        row_str.append(f"    {coin:16} {price_str:>12}")
                    print("  ".join(row_str))
            else:
                print(f"\n  {dex_name}: (no markets found)")


def _print_ticker(out: dict):
    print(f"Ticker: {out.get('coin')}")
    print(f"  Mid: {_fmt_num(out.get('mid'), 4)}")
    print(f"  Best Bid/Ask: {_fmt_num(out.get('bestBid'), 4)} / {_fmt_num(out.get('bestAsk'), 4)}")
    print(f"  Spread: {_fmt_num(out.get('spread'), 4)} ({_fmt_num(out.get('spreadBps'), 2)} bps)")
    print(f"  Mark/Oracle: {_fmt_num(out.get('markPx'), 4)} / {_fmt_num(out.get('oraclePx'), 4)}")
    print(f"  Funding: {_fmt_num(out.get('funding'), 6)}")
    print(f"  Open Interest: {_fmt_num(out.get('openInterest'), 2)}")
    print(f"  24h Notional Volume: {_fmt_usd(out.get('dayNtlVlm'))}")


def _print_scan_funding(out: dict):
    print(f"Funding Scan ({len(out.get('rows', []))} markets)")
    print("-" * 72)
    print(f"{'Coin':12} {'Funding':>12} {'Mark':>12} {'OI':>14} {'24h Vol':>14}")
    for row in out.get("rows", []):
        print(
            f"{row.get('coin','?'):12} "
            f"{_fmt_num(row.get('funding'), 6):>12} "
            f"{_fmt_num(row.get('markPx'), 4):>12} "
            f"{_fmt_num(row.get('openInterest'), 2):>14} "
            f"{_fmt_usd(row.get('dayNtlVlm')):>14}"
        )


def _print_diff(out: dict):
    changes = out.get("changes", [])
    if not changes:
        print("No changes")
        return
    print(f"Diff: {out.get('before')} -> {out.get('after')}")
    print(f"Changes: {len(changes)}")
    for change in changes[:50]:
        print(json.dumps(change, ensure_ascii=True))


def _print(out, as_json: bool, book_depth: int = 5):
    if as_json:
        print(json.dumps(out, indent=2, sort_keys=False))
        return

    # Order book formatting
    if isinstance(out, dict) and "levels" in out:
        _print_book(out, depth=book_depth)
        return

    # Markets formatting
    if isinstance(out, dict) and "main" in out and "dexs" in out:
        _print_markets(out)
        return

    if isinstance(out, dict) and {"coin", "spreadBps", "markPx"} <= set(out.keys()):
        _print_ticker(out)
        return

    if isinstance(out, dict) and "rows" in out and isinstance(out.get("rows"), list):
        _print_scan_funding(out)
        return

    if isinstance(out, dict) and "changes" in out and "before" in out and "after" in out:
        _print_diff(out)
        return

    # Minimal human-friendly formatting for common outputs
    if isinstance(out, dict) and "mids" in out and isinstance(out["mids"], dict):
        mids = out["mids"]
        for k in sorted(mids.keys()):
            print(f"{k}: {mids[k]}")
        return

    print(json.dumps(out, indent=2, sort_keys=False))


def main():
    # Make global flags available both before and after the subcommand by
    # attaching them to each subparser as well.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL (default mainnet)")
    common.add_argument("--timeout", type=int, default=20, help="HTTP timeout seconds")
    common.add_argument("--json", action="store_true", help="Output raw JSON")

    p = argparse.ArgumentParser(description="Hyperliquid public API helper", parents=[common])

    sp = p.add_subparsers(dest="cmd", required=True)

    sp_mids = sp.add_parser("mids", help="Get all mid prices", parents=[common])
    sp_mids.set_defaults(fn=cmd_mids)

    sp_meta = sp.add_parser("meta", help="Get exchange metadata", parents=[common])
    sp_meta.set_defaults(fn=cmd_meta)

    sp_book = sp.add_parser("book", help="Get L2 order book for a coin", parents=[common])
    sp_book.add_argument("coin")
    sp_book.add_argument("--depth", type=int, default=5, help="Number of book levels to display")
    sp_book.set_defaults(fn=cmd_book)

    sp_markets = sp.add_parser("markets", help="List all available markets including HIP-3 dex markets", parents=[common])
    sp_markets.set_defaults(fn=cmd_markets)

    sp_t = sp.add_parser("ticker", help="Compact market summary for one coin", parents=[common])
    sp_t.add_argument("coin")
    sp_t.set_defaults(fn=cmd_ticker)

    sp_sf = sp.add_parser("scan-funding", help="Rank markets by funding", parents=[common])
    sp_sf.add_argument("--limit", type=int, default=20, help="Maximum markets to print")
    sp_sf.add_argument("--lowest", action="store_true", help="Show lowest funding rates instead of highest")
    sp_sf.set_defaults(fn=cmd_scan_funding)

    sp_c = sp.add_parser("candles", help="Get candle snapshot", parents=[common])
    sp_c.add_argument("coin")
    sp_c.add_argument("--interval", default="15m")
    sp_c.add_argument("--start", type=int, default=0, help="ms since epoch (0 = API default)")
    sp_c.add_argument("--end", type=int, default=0, help="ms since epoch (0 = API default)")
    sp_c.add_argument("--limit", type=int, default=200, help="Limit number of candles (from the end)")
    sp_c.set_defaults(fn=cmd_candles)

    sp_u = sp.add_parser("user", help="Get user state (perps+spot) for an address", parents=[common])
    sp_u.add_argument("address")
    sp_u.add_argument("--all-dexs", action="store_true", help="Also scan HIP-3 perp dexs for positions")
    sp_u.set_defaults(fn=cmd_user)

    sp_d = sp.add_parser("dash", help="Hyperdash-style scannable dashboard for 1+ addresses", parents=[common])
    sp_d.add_argument("addresses", nargs="+")
    sp_d.add_argument("--main-only", action="store_true", help="Do NOT scan HIP-3 perp dexs (faster; main dex only)")
    sp_d.add_argument("--compact", action="store_true", help="No blank line between addresses")
    sp_d.add_argument("--limit-positions", type=int, default=12)
    sp_d.add_argument("--limit-spot", type=int, default=12)
    sp_d.add_argument("--include-orders", action="store_true", help="Include open orders counts (main + dexs)")
    sp_d.set_defaults(fn=cmd_dash)

    sp_oo = sp.add_parser("open-orders", help="Get open orders for an address", parents=[common])
    sp_oo.add_argument("address")
    sp_oo.set_defaults(fn=cmd_open_orders)

    sp_pf = sp.add_parser("predicted-funding", help="Get predicted funding rates across venues", parents=[common])
    sp_pf.set_defaults(fn=cmd_predicted_funding)

    sp_ma = sp.add_parser("meta-ctx", help="Get perps meta and asset contexts (funding/OI/mark/mid)", parents=[common])
    sp_ma.set_defaults(fn=cmd_meta_ctx)

    sp_ss = sp.add_parser("snapshot", help="Capture market and optional account data to JSON", parents=[common])
    sp_ss.add_argument("addresses", nargs="*", help="Optional addresses to include in the snapshot")
    sp_ss.add_argument("--include-funding", action="store_true", help="Include predicted funding payload")
    sp_ss.add_argument("--output", help="Write JSON snapshot to a file")
    sp_ss.set_defaults(fn=cmd_snapshot)

    sp_df = sp.add_parser("diff", help="Compare two saved JSON snapshots", parents=[common])
    sp_df.add_argument("before")
    sp_df.add_argument("after")
    sp_df.set_defaults(fn=cmd_diff)

    args = p.parse_args()

    try:
        out = args.fn(args)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if out is None:
        return

    # Pass depth for book command
    book_depth = getattr(args, 'depth', 5)
    _print(out, args.json, book_depth)


if __name__ == "__main__":
    main()
