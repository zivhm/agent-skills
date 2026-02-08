#!/usr/bin/env python3
"""Hyperliquid public API helper.

Implements a few high-signal endpoints via POST https://api.hyperliquid.xyz/info

This is intentionally small and dependency-light.
"""

import argparse
import json
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


def cmd_mids(args):
    out = hl_info(args.base_url, {"type": "allMids"}, timeout=args.timeout)
    return out


def cmd_meta(args):
    out = hl_info(args.base_url, {"type": "meta"}, timeout=args.timeout)
    return out


def cmd_book(args):
    # coin: string symbol like BTC, ETH, SOL, etc.
    out = hl_info(args.base_url, {"type": "l2Book", "coin": args.coin.upper()}, timeout=args.timeout)
    return out


def cmd_meta_ctx(args):
    return hl_info(args.base_url, {"type": "metaAndAssetCtxs"}, timeout=args.timeout)


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


def _print(out, as_json: bool):
    if as_json:
        print(json.dumps(out, indent=2, sort_keys=False))
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
    sp_book.set_defaults(fn=cmd_book)

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

    args = p.parse_args()

    try:
        out = args.fn(args)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if out is None:
        return

    _print(out, args.json)


if __name__ == "__main__":
    main()
