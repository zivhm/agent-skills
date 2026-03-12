#!/usr/bin/env python3
"""
Zapper CLI
Query DeFi portfolios, NFTs, and transactions via Zapper's GraphQL API
"""

import argparse
import csv
import datetime as dt
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

DEFAULT_CONFIG_FILE = os.path.expanduser("~/.config/zapper/addresses.json")
LOCAL_CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "addresses.json")
GRAPHQL_URL = "https://public.zapper.xyz/graphql"
NETWORK_CHAIN_MAP = {
    "ethereum": "ETHEREUM", "eth": "ETHEREUM", "mainnet": "ETHEREUM",
    "base": "BASE",
    "arbitrum": "ARBITRUM", "arb": "ARBITRUM",
    "optimism": "OPTIMISM", "op": "OPTIMISM",
    "polygon": "POLYGON", "matic": "POLYGON",
    "avalanche": "AVALANCHE", "avax": "AVALANCHE",
    "solana": "SOLANA", "sol": "SOLANA",
    "bnb": "BNB", "bsc": "BNB",
}
CHAIN_ID_MAP = {
    "ethereum": 1, "eth": 1, "mainnet": 1,
    "base": 8453, "bsc": 56, "bnb": 56,
    "arbitrum": 42161, "arb": 42161,
    "optimism": 10, "op": 10,
    "polygon": 137, "matic": 137,
    "avalanche": 43114, "avax": 43114,
    "solana": 1399811149, "sol": 1399811149,
}


# =============================================================================
# Config & API
# =============================================================================

def fail(message, exit_code=1):
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def _iso_now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


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
        return [{"path": path, "before_len": len(before), "after_len": len(after)}]
    return [{"path": path, "before": before, "after": after}]


def _wallet_name(wallet, fallback):
    return wallet.get("label") or fallback


def resolve_config_path(config_path=None):
    if config_path:
        return config_path
    env_path = os.environ.get("ZAPPER_CONFIG_FILE")
    if env_path:
        return env_path
    if os.path.exists(LOCAL_CONFIG_FILE):
        return LOCAL_CONFIG_FILE
    return DEFAULT_CONFIG_FILE


def get_config(config_path=None):
    path = resolve_config_path(config_path)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"wallets": [], "apiKey": None}
    except json.JSONDecodeError as exc:
        return {"wallets": [], "apiKey": None, "error": f"Invalid config JSON in {path}: {exc}"}


def get_api_key(config_path=None, explicit_api_key=None):
    return explicit_api_key or os.environ.get("ZAPPER_API_KEY") or get_config(config_path).get("apiKey")


def get_wallets(config_path=None):
    return get_config(config_path).get("wallets", [])


def _configured_wallets_or_single(address, config_path=None):
    if address:
        return [{"label": address, "address": resolve_address(address, config_path)[0]}]
    wallets = get_wallets(config_path)
    if wallets:
        return wallets
    fail("Provide an address or configure at least one wallet")


def graphql_request(query, variables, api_key=None, config_path=None):
    api_key = get_api_key(config_path, explicit_api_key=api_key)
    if not api_key:
        return {"error": "No API key. Set ZAPPER_API_KEY or add apiKey to config."}

    payload = json.dumps({"query": query, "variables": variables}).encode()
    headers = {
        "Content-Type": "application/json",
        "x-zapper-api-key": api_key,
        "User-Agent": "ZapperSkill/1.0"
    }

    try:
        req = urllib.request.Request(GRAPHQL_URL, data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())
            if data.get("errors"):
                return {"error": data["errors"][0].get("message", "GraphQL error")}
            return data
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return {"error": "Access denied - this endpoint may require a paid API tier"}
        return {"error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"error": str(e)}


def resolve_address(address_or_label, config_path=None):
    """Resolve address from argument or wallet label."""
    if address_or_label and address_or_label.startswith("0x"):
        return [address_or_label]

    wallets = get_wallets(config_path)
    if address_or_label:
        # Try to find by label
        for w in wallets:
            if w.get("label", "").lower() == address_or_label.lower():
                return [w["address"]]
        fail(f"Wallet '{address_or_label}' not found in config")

    if wallets:
        return [w["address"] for w in wallets]

    fail(
        f"No address provided and no wallets configured. Add wallets to {resolve_config_path(config_path)} or pass an address."
    )


def resolve_chain(chain_name):
    """Resolve chain name to network enum."""
    if not chain_name:
        return None
    chain_key = chain_name.lower()
    return NETWORK_CHAIN_MAP.get(chain_key)


def resolve_chain_id(chain_name):
    if chain_name is None:
        return None
    if isinstance(chain_name, int):
        return chain_name
    if isinstance(chain_name, str) and chain_name.isdigit():
        return int(chain_name)
    return CHAIN_ID_MAP.get(str(chain_name).lower())


# =============================================================================
# Fetch Functions
# =============================================================================

def fetch_portfolio(addresses, limit=10, chain_filter=None, api_key=None, config_path=None):
    query = """
    query Portfolio($addresses: [Address!]!, $first: Int, $chains: [Network!]) {
      portfolioV2(addresses: $addresses) {
        tokenBalances {
          totalBalanceUSD
          byToken(first: $first, filters: {networks: $chains}) {
            totalCount
            edges {
              node {
                name
                symbol
                price
                balance
                balanceUSD
                network { name }
                onchainMarketData {
                  priceChange24h
                  marketCap
                }
              }
            }
          }
        }
        appBalances {
          totalBalanceUSD
          byApp(first: 10) {
            edges {
              node {
                app { displayName }
                balanceUSD
                network { name }
              }
            }
          }
        }
      }
    }
    """
    variables = {"addresses": addresses, "first": limit}
    if chain_filter:
        variables["chains"] = [chain_filter]
    result = graphql_request(query, variables, api_key=api_key, config_path=config_path)
    if "error" in result:
        return result
    return result.get("data", {}).get("portfolioV2", {})


def fetch_tokens(addresses, limit=20, chain_filter=None, api_key=None, config_path=None):
    query = """
    query Tokens($addresses: [Address!]!, $first: Int, $chains: [Network!]) {
      portfolioV2(addresses: $addresses) {
        tokenBalances {
          totalBalanceUSD
          byToken(first: $first, filters: {networks: $chains}) {
            totalCount
            edges {
              node {
                name
                symbol
                price
                balance
                balanceUSD
                network { name }
                onchainMarketData {
                  priceChange24h
                  marketCap
                }
              }
            }
          }
        }
      }
    }
    """
    variables = {"addresses": addresses, "first": limit}
    if chain_filter:
        variables["chains"] = [chain_filter]
    result = graphql_request(query, variables, api_key=api_key, config_path=config_path)
    if "error" in result:
        return result
    return result.get("data", {}).get("portfolioV2", {}).get("tokenBalances", {})


def fetch_apps(addresses, limit=20, chain_filter=None, api_key=None, config_path=None):
    query = """
    query Apps($addresses: [Address!]!, $first: Int, $chains: [Network!]) {
      portfolioV2(addresses: $addresses) {
        appBalances {
          totalBalanceUSD
          byApp(first: $first, filters: {networks: $chains}) {
            edges {
              node {
                app { displayName }
                balanceUSD
                network { name }
              }
            }
          }
        }
      }
    }
    """
    variables = {"addresses": addresses, "first": limit}
    if chain_filter:
        variables["chains"] = [chain_filter]
    result = graphql_request(query, variables, api_key=api_key, config_path=config_path)
    if "error" in result:
        return result
    return result.get("data", {}).get("portfolioV2", {}).get("appBalances", {})


def fetch_nfts(addresses, limit=10, api_key=None, config_path=None):
    query = """
    query NFTs($addresses: [Address!]!, $first: Int) {
      portfolioV2(addresses: $addresses) {
        nftBalances {
          totalBalanceUSD
          totalTokensOwned
          byToken(first: $first, order: {by: USD_WORTH}) {
            edges {
              node {
                token {
                  tokenId
                  name
                  estimatedValue { valueUsd }
                  collection { name address network }
                }
              }
            }
          }
        }
      }
    }
    """
    result = graphql_request(query, {"addresses": addresses, "first": limit}, api_key=api_key, config_path=config_path)
    if "error" in result:
        return result
    return result.get("data", {}).get("portfolioV2", {}).get("nftBalances", {})


def fetch_transactions(addresses, limit=20, api_key=None, config_path=None):
    end_date = int(time.time() * 1000)
    start_date = end_date - (30 * 24 * 60 * 60 * 1000)  # 30 days

    query = """
    query Transactions($addresses: [Address!]!, $first: Int, $startDate: Timestamp!, $endDate: Timestamp!) {
      transactionHistoryV2(
        subjects: $addresses
        first: $first
        filters: {
          orderByDirection: DESC
          startDate: $startDate
          endDate: $endDate
        }
      ) {
        edges {
          node {
            ... on TimelineEventV2 {
              transaction { hash timestamp network }
              interpretation { processedDescription }
            }
          }
        }
      }
    }
    """
    result = graphql_request(query, {
        "addresses": addresses,
        "first": limit,
        "startDate": start_date,
        "endDate": end_date
    }, api_key=api_key, config_path=config_path)
    if not result or "error" in result:
        return result or {"error": "No response from API"}
    return result.get("data", {}).get("transactionHistoryV2", {})


def fetch_price(symbol_or_address, chain_id=None, api_key=None, config_path=None):
    # Common token addresses (Ethereum mainnet)
    TOKEN_ADDRESSES = {
        "ETH": ("0x0000000000000000000000000000000000000000", 1),
        "WETH": ("0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", 1),
        "USDC": ("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", 1),
        "USDT": ("0xdac17f958d2ee523a2206206994597c13d831ec7", 1),
        "DAI": ("0x6b175474e89094c44da98b954eedeac495271d0f", 1),
        "WBTC": ("0x2260fac5e5542a773aa44fbcfedf7c193bc2c599", 1),
        "LINK": ("0x514910771af9ca656af840dff83e8264ecf986ca", 1),
        "UNI": ("0x1f9840a85d5af5bf1d1762f925bdaddc4201f984", 1),
        "AAVE": ("0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9", 1),
        "MKR": ("0x9f8f72aa9304c8b593d555f12ef6589cc3a579a2", 1),
        "CRV": ("0xd533a949740bb3306d119cc777fa900ba034cd52", 1),
        "SNX": ("0xc011a73ee8576fb46f5e1c5751ca3b9fe0af2a6f", 1),
        "COMP": ("0xc00e94cb662c3520282e6f5717214004a7f26888", 1),
        "YFI": ("0x0bc529c00c6401aef6d220be8c6ea1667f6ad93e", 1),
        "LDO": ("0x5a98fcbea516cf06857215779fd812ca3bef1b32", 1),
        "FXS": ("0x3432b6a60d23ca0df16f4b0ddc2b0e0000", 1),
    }

    # Check if input is an address (starts with 0x and is 42 chars)
    input_str = symbol_or_address.strip()
    if input_str.startswith("0x") and len(input_str) == 42:
        address = input_str
        # Use provided chain_id or default to Ethereum
        if chain_id is None:
            chain_id = 1
    else:
        # Treat as symbol
        symbol_upper = input_str.upper()
        if symbol_upper not in TOKEN_ADDRESSES:
            return {"error": f"Unknown token symbol: {input_str}. Use contract address for other tokens."}
        address, chain_id = TOKEN_ADDRESSES[symbol_upper]

    query = """
    query Price($address: Address!, $chainId: Int!) {
      fungibleTokenV2(address: $address, chainId: $chainId) {
        symbol
        name
        priceData {
          price
          priceChange24h
          marketCap
          volume24h
        }
      }
    }
    """
    result = graphql_request(query, {"address": address, "chainId": chain_id}, api_key=api_key, config_path=config_path)
    if "error" in result:
        return result
    token = result.get("data", {}).get("fungibleTokenV2", {})
    if not token:
        return {"error": "Token not found"}
    price_data = token.get("priceData", {})
    return {
        "symbol": token.get("symbol"),
        "name": token.get("name"),
        "price": price_data.get("price"),
        "priceChange24h": price_data.get("priceChange24h"),
        "marketCap": price_data.get("marketCap"),
        "volume24h": price_data.get("volume24h"),
    }


def fetch_token_search(query_str, limit=10, api_key=None, config_path=None):
    """Search for tokens by name or symbol across chains."""
    query = """
    query TokenSearch($query: String!, $first: Int) {
      tokenSearchV2(query: $query, first: $first) {
        edges {
          node {
            address
            symbol
            name
            network
            decimals
            price
            onchainMarketData {
              priceChange24h
              marketCap
              volume24h
            }
          }
        }
      }
    }
    """
    result = graphql_request(query, {"query": query_str, "first": limit}, api_key=api_key, config_path=config_path)
    if "error" in result:
        return result
    return result.get("data", {}).get("tokenSearchV2", {}).get("edges", [])


def fetch_claimables(addresses, api_key=None, config_path=None):
    # Claimables are in positionBalances - look for type containing "claimable"
    query = """
    query Claimables($addresses: [Address!]!) {
      portfolioV2(addresses: $addresses) {
        appBalances {
          byApp(first: 50) {
            edges {
              node {
                app { displayName }
                network { name }
                positionBalances(first: 100) {
                  edges {
                    node {
                      ... on AppTokenPositionBalance {
                        balanceUSD
                        tokens {
                          type
                          symbol
                          balance
                          balanceUSD
                        }
                      }
                      ... on ContractPositionBalance {
                        balanceUSD
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    result = graphql_request(query, {"addresses": addresses}, api_key=api_key, config_path=config_path)
    if "error" in result:
        return result

    # Extract claimable tokens (type contains "claimable")
    claimables = []
    total_usd = 0

    apps = result.get("data", {}).get("portfolioV2", {}).get("appBalances", {}).get("byApp", {}).get("edges", [])
    for app_edge in apps:
        app_node = app_edge.get("node", {})
        app_name = app_node.get("app", {}).get("displayName", "Unknown")
        network = app_node.get("network", {}).get("name", "")

        positions = app_node.get("positionBalances", {}).get("edges", [])
        for pos_edge in positions:
            pos_node = pos_edge.get("node", {})
            tokens = pos_node.get("tokens", [])

            for t in tokens:
                token_type = t.get("type", "").lower()
                if "claimable" in token_type or "reward" in token_type:
                    value = t.get("balanceUSD", 0)
                    if value > 0.01:  # Skip dust
                        total_usd += value
                        claimables.append({
                            "symbol": t.get("symbol", "?"),
                            "balance": t.get("balance", 0),
                            "balanceUSD": value,
                            "app": app_name,
                            "network": network,
                        })

    return {"totalBalanceUSD": total_usd, "claimables": claimables}


# =============================================================================
# Format Functions
# =============================================================================

def format_portfolio(data, short=False, onchain=False):
    if "error" in data:
        return f"Error: {data['error']}"

    total_tokens = data.get("tokenBalances", {}).get("totalBalanceUSD", 0)
    total_apps = data.get("appBalances", {}).get("totalBalanceUSD", 0)
    total = total_tokens + total_apps

    if short:
        return f"${total:,.2f}"

    lines = [f"Total: ${total:,.2f}"]
    lines.append(f"  Tokens: ${total_tokens:,.2f} | DeFi: ${total_apps:,.2f}")

    tokens = data.get("tokenBalances", {}).get("byToken", {}).get("edges", [])
    if tokens:
        lines.append("\nTokens:")
        for edge in tokens[:10]:
            node = edge.get("node", {})
            symbol = node.get("symbol", "?")
            value = node.get("balanceUSD", 0)
            network = node.get("network", {}).get("name", "")
            if onchain:
                change = (node.get("onchainMarketData") or {}).get("priceChange24h", 0)
                sign = "+" if change > 0 else ""
                lines.append(f"  {symbol}: ${value:,.2f} ({sign}{change:.1f}%) [{network}]")
            else:
                lines.append(f"  {symbol}: ${value:,.2f} [{network}]")

    apps = data.get("appBalances", {}).get("byApp", {}).get("edges", [])
    if apps:
        lines.append("\nDeFi:")
        for edge in apps[:5]:
            node = edge.get("node", {})
            name = node.get("app", {}).get("displayName", "?")
            value = node.get("balanceUSD", 0)
            network = node.get("network", {}).get("name", "")
            lines.append(f"  {name}: ${value:,.2f} [{network}]")

    return "\n".join(lines)


def format_tokens(data, onchain=False):
    if "error" in data:
        return f"Error: {data['error']}"

    total = data.get("totalBalanceUSD", 0)
    count = data.get("byToken", {}).get("totalCount", 0)
    lines = [f"Token Value: ${total:,.2f} ({count} tokens)"]

    tokens = data.get("byToken", {}).get("edges", [])
    if tokens:
        lines.append("")
        for edge in tokens:
            node = edge.get("node", {})
            symbol = node.get("symbol", "?")
            name = node.get("name", "")
            balance = node.get("balance", 0)
            value = node.get("balanceUSD", 0)
            price = node.get("price", 0)
            network = node.get("network", {}).get("name", "")

            if onchain:
                change = (node.get("onchainMarketData") or {}).get("priceChange24h", 0)
                sign = "+" if change > 0 else ""
                lines.append(f"  {symbol}: {balance:,.4f} (${value:,.2f}) @ ${price:.4f} ({sign}{change:.1f}%) [{network}]")
            else:
                lines.append(f"  {symbol}: {balance:,.4f} (${value:,.2f}) @ ${price:.4f} [{network}]")

    return "\n".join(lines)


def format_apps(data):
    if "error" in data:
        return f"Error: {data['error']}"

    total = data.get("totalBalanceUSD", 0)
    lines = [f"DeFi Value: ${total:,.2f}"]

    apps = data.get("byApp", {}).get("edges", [])
    if apps:
        lines.append("")
        for edge in apps:
            node = edge.get("node", {})
            name = node.get("app", {}).get("displayName", "?")
            value = node.get("balanceUSD", 0)
            network = node.get("network", {}).get("name", "")
            lines.append(f"  {name}: ${value:,.2f} [{network}]")
    else:
        lines.append("  No DeFi positions found")

    return "\n".join(lines)


def format_nfts(data):
    if "error" in data:
        return f"Error: {data['error']}"

    total = data.get("totalBalanceUSD", 0)
    count = data.get("totalTokensOwned", "0")
    lines = [f"NFT Value: ${total:,.2f} ({count} tokens)"]

    tokens = data.get("byToken", {}).get("edges", [])
    if tokens:
        lines.append("")
        for edge in tokens:
            token = edge.get("node", {}).get("token", {})
            name = token.get("name", "Unknown")
            token_id = token.get("tokenId", "?")
            value = token.get("estimatedValue", {}).get("valueUsd", 0)
            coll = token.get("collection", {})
            coll_name = coll.get("name", "")
            network = coll.get("network", "")
            lines.append(f"  {coll_name} #{token_id}: ${value:,.2f} [{network}]")
    else:
        lines.append("  No NFTs found")

    return "\n".join(lines)


def format_transactions(data):
    if "error" in data:
        return f"Error: {data['error']}"

    edges = data.get("edges", [])
    if not edges:
        return "No recent transactions"

    lines = ["Recent Transactions (30 days):"]
    for edge in edges:
        node = edge.get("node", {})
        tx = node.get("transaction", {})
        ts_ms = tx.get("timestamp")
        ts = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M") if ts_ms else ""
        network = tx.get("network", "")
        tx_hash = tx.get("hash", "")[:10] if tx.get("hash") else ""
        desc = node.get("interpretation", {}).get("processedDescription", "")

        if desc:
            lines.append(f"  [{ts}] {desc} [{network}] {tx_hash}...")

    return "\n".join(lines)


def format_price(data):
    if not data or "error" in data:
        return f"Error: {data.get('error', 'Token not found')}"

    symbol = data.get("symbol", "?")
    name = data.get("name", "")
    price = data.get("price", 0)
    change = data.get("priceChange24h", 0)
    mcap = data.get("marketCap", 0)
    volume = data.get("volume24h", 0)

    sign = "+" if change > 0 else ""
    lines = [
        f"{symbol} ({name})",
        f"  Price: ${price:,.6f}" if price < 1 else f"  Price: ${price:,.2f}",
        f"  24h Change: {sign}{change:.2f}%",
    ]
    if mcap:
        lines.append(f"  Market Cap: ${mcap/1e9:.2f}B" if mcap > 1e9 else f"  Market Cap: ${mcap/1e6:.2f}M")
    if volume:
        lines.append(f"  24h Volume: ${volume/1e6:.2f}M")

    return "\n".join(lines)


def format_search(edges):
    """Format token search results."""
    if not edges:
        return "No tokens found"

    lines = [f"Found {len(edges)} token(s):\n"]
    for edge in edges:
        node = edge.get("node", {})
        symbol = node.get("symbol", "?")
        name = node.get("name", "Unknown")
        address = node.get("address", "")
        network = node.get("network", "Unknown")
        price = node.get("price", 0)
        market_data = node.get("onchainMarketData", {}) or {}
        change = market_data.get("priceChange24h", 0)
        mcap = market_data.get("marketCap", 0)

        sign = "+" if change > 0 else ""
        price_str = f"${price:.6f}" if price and price < 1 else f"${price:.2f}" if price else "N/A"
        mcap_str = f" | MC: ${mcap/1e6:.1f}M" if mcap else ""

        lines.append(f"  {symbol} - {name}")
        lines.append(f"    Price: {price_str} ({sign}{change:.2f}%){mcap_str}")
        lines.append(f"    Chain: {network} | Address: {address[:20]}...")
        lines.append("")

    return "\n".join(lines)


def format_claimables(data):
    if "error" in data:
        return f"Error: {data['error']}"

    total = data.get("totalBalanceUSD", 0)
    lines = [f"Claimable Rewards: ${total:,.2f}"]

    claimables = data.get("claimables", [])
    if claimables:
        lines.append("")
        for c in claimables:
            symbol = c.get("symbol", "?")
            balance = c.get("balance", 0)
            value = c.get("balanceUSD", 0)
            app = c.get("app", "")
            network = c.get("network", "")
            if isinstance(balance, (int, float)):
                lines.append(f"  {symbol}: {balance:,.4f} (${value:,.2f}) from {app} [{network}]")
            else:
                lines.append(f"  {symbol}: {balance} (${value:,.2f}) from {app} [{network}]")
    else:
        lines.append("  No claimable rewards found")

    return "\n".join(lines)


def export_csv(filename, data, data_type):
    """Export data to CSV file."""
    try:
        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)
            if data_type == "tokens":
                writer.writerow(["Symbol", "Name", "Balance", "Price", "Value USD", "24h Change %", "Network"])
                for edge in data.get("byToken", {}).get("edges", []):
                    node = edge.get("node", {})
                    change = (node.get("onchainMarketData") or {}).get("priceChange24h", 0)
                    writer.writerow([
                        node.get("symbol", ""),
                        node.get("name", ""),
                        node.get("balance", 0),
                        node.get("price", 0),
                        node.get("balanceUSD", 0),
                        change,
                        node.get("network", {}).get("name", "")
                    ])
            elif data_type == "apps":
                writer.writerow(["App", "Value USD", "Network"])
                for edge in data.get("byApp", {}).get("edges", []):
                    node = edge.get("node", {})
                    writer.writerow([
                        node.get("app", {}).get("displayName", ""),
                        node.get("balanceUSD", 0),
                        node.get("network", {}).get("name", "")
                    ])
            elif data_type == "tx":
                writer.writerow(["Date", "Description", "Network", "Transaction Hash"])
                for edge in data.get("edges", []):
                    node = edge.get("node", {})
                    tx = node.get("transaction", {})
                    ts_ms = tx.get("timestamp")
                    ts = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M") if ts_ms else ""
                    writer.writerow([
                        ts,
                        node.get("interpretation", {}).get("processedDescription", ""),
                        tx.get("network", ""),
                        tx.get("hash", "")
                    ])
        return f"Exported to {filename}"
    except Exception as e:
        return f"Error exporting CSV: {e}"


def format_top_movers(tokens_data, limit=10):
    """Show biggest 24h gainers and losers."""
    edges = tokens_data.get("byToken", {}).get("edges", [])
    
    # Filter tokens with price change data
    tokens_with_change = []
    for edge in edges:
        node = edge.get("node", {})
        change = (node.get("onchainMarketData") or {}).get("priceChange24h")
        if change is not None:
            tokens_with_change.append({
                "symbol": node.get("symbol", "?"),
                "name": node.get("name", ""),
                "change": change,
                "value": node.get("balanceUSD", 0),
                "price": node.get("price", 0),
                "network": node.get("network", {}).get("name", "")
            })
    
    if not tokens_with_change:
        return "No 24h price change data available"
    
    # Sort by change
    sorted_tokens = sorted(tokens_with_change, key=lambda x: x["change"], reverse=True)
    
    lines = ["📈 Top Movers (24h)\n"]
    
    # Top gainers
    gainers = [t for t in sorted_tokens if t["change"] > 0][:limit]
    if gainers:
        lines.append("🟢 Gainers:")
        for t in gainers:
            lines.append(f"  {t['symbol']}: +{t['change']:.2f}% @ ${t['price']:.4f} [{t['network']}]")
        lines.append("")
    
    # Top losers
    losers = [t for t in sorted_tokens if t["change"] < 0][-limit:]
    if losers:
        lines.append("🔴 Losers:")
        for t in reversed(losers):
            lines.append(f"  {t['symbol']}: {t['change']:.2f}% @ ${t['price']:.4f} [{t['network']}]")
    
    return "\n".join(lines)


def format_wallet_summary(rows):
    if not rows:
        return "No wallets found"
    lines = ["Wallet Summary:"]
    for row in rows:
        if row.get("error"):
            lines.append(f"  {row['label']}: Error: {row['error']}")
            continue
        lines.append(
            f"  {row['label']}: total ${row['totalUSD']:,.2f} | tokens ${row['tokenUSD']:,.2f} | "
            f"DeFi ${row['appUSD']:,.2f} | {row['tokenCount']} tokens | {row['appCount']} apps"
        )
    return "\n".join(lines)


def format_allocations(result):
    if "error" in result:
        return f"Error: {result['error']}"
    lines = [f"Allocations by {result['groupBy']}:"]
    for row in result.get("rows", []):
        lines.append(f"  {row['name']}: ${row['usd']:,.2f} ({row['pct']:.2f}%)")
    return "\n".join(lines)


def format_diff(result):
    changes = result.get("changes", [])
    if not changes:
        return "No changes"
    lines = [f"Diff: {result['before']} -> {result['after']}", f"Changes: {len(changes)}"]
    for change in changes[:50]:
        lines.append(json.dumps(change, ensure_ascii=True))
    return "\n".join(lines)


# =============================================================================
# Command Handlers
# =============================================================================

def cmd_portfolio(args):
    chain_filter = resolve_chain(args.chain) if args.chain else None
    if args.chain and not chain_filter:
        fail(f"Unsupported chain '{args.chain}'")
    if args.per_wallet:
        wallets = get_wallets(args.config)
        if not wallets:
            fail("No wallets configured for --per-wallet")
        total_all = 0
        all_data = []
        for w in wallets:
            data = fetch_portfolio([w["address"]], args.limit, chain_filter, api_key=args.api_key, config_path=args.config)
            all_data.append({"wallet": w, "data": data})
            if "error" not in data:
                total_all += data.get("tokenBalances", {}).get("totalBalanceUSD", 0)
                total_all += data.get("appBalances", {}).get("totalBalanceUSD", 0)

        if args.json:
            print(json.dumps(all_data, indent=2))
        else:
            for item in all_data:
                w = item["wallet"]
                addr = w['address']
                print(f"\n{w['label']} ({addr[:8]}...{addr[-6:]})")
                print(format_portfolio(item["data"], onchain=args.show_24h))
            print(f"\nGrand Total: ${total_all:,.2f}")
    else:
        addresses = resolve_address(args.address, args.config)
        data = fetch_portfolio(addresses, args.limit, chain_filter, api_key=args.api_key, config_path=args.config)
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(format_portfolio(data, short=args.short, onchain=args.show_24h))


def cmd_tokens(args):
    chain_filter = resolve_chain(args.chain) if args.chain else None
    if args.chain and not chain_filter:
        fail(f"Unsupported chain '{args.chain}'")
    addresses = resolve_address(args.address, args.config)
    data = fetch_tokens(addresses, args.limit, chain_filter, api_key=args.api_key, config_path=args.config)
    if args.csv:
        print(export_csv(args.csv, data, "tokens"))
    elif args.json:
        print(json.dumps(data, indent=2))
    else:
        print(format_tokens(data, onchain=args.show_24h))


def cmd_top_movers(args):
    chain_filter = resolve_chain(args.chain) if args.chain else None
    if args.chain and not chain_filter:
        fail(f"Unsupported chain '{args.chain}'")
    addresses = resolve_address(args.address, args.config)
    data = fetch_tokens(addresses, 100, chain_filter, api_key=args.api_key, config_path=args.config)  # Fetch more to analyze
    if "error" in data:
        print(f"Error: {data['error']}")
        return
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(format_top_movers(data, args.limit))


def cmd_apps(args):
    chain_filter = resolve_chain(args.chain) if args.chain else None
    if args.chain and not chain_filter:
        fail(f"Unsupported chain '{args.chain}'")
    addresses = resolve_address(args.address, args.config)
    data = fetch_apps(addresses, args.limit, chain_filter, api_key=args.api_key, config_path=args.config)
    if args.csv:
        print(export_csv(args.csv, data, "apps"))
    elif args.json:
        print(json.dumps(data, indent=2))
    else:
        print(format_apps(data))


def cmd_nfts(args):
    addresses = resolve_address(args.address, args.config)
    data = fetch_nfts(addresses, args.limit, api_key=args.api_key, config_path=args.config)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(format_nfts(data))


def cmd_tx(args):
    addresses = resolve_address(args.address, args.config)
    data = fetch_transactions(addresses, args.limit, api_key=args.api_key, config_path=args.config)
    if args.csv:
        print(export_csv(args.csv, data, "tx"))
    elif args.json:
        print(json.dumps(data, indent=2))
    else:
        print(format_transactions(data))


def cmd_price(args):
    chain_id = resolve_chain_id(args.chain_id)
    if args.chain_id and chain_id is None:
        fail(f"Unsupported chain '{args.chain_id}'")
    data = fetch_price(args.symbol, chain_id, api_key=args.api_key, config_path=args.config)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(format_price(data))


def cmd_search(args):
    data = fetch_token_search(args.query, args.limit, api_key=args.api_key, config_path=args.config)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(format_search(data))


def cmd_claimables(args):
    addresses = resolve_address(args.address, args.config)
    data = fetch_claimables(addresses, api_key=args.api_key, config_path=args.config)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(format_claimables(data))


def cmd_config(args):
    config_path = resolve_config_path(args.config)
    config = get_config(args.config)
    api_key = get_api_key(args.config, explicit_api_key=args.api_key)
    print(f"Config: {config_path}")
    print(f"API Key: {'Set' if api_key else 'Missing'}")
    print(f"Wallets: {len(config.get('wallets', []))}")
    if config.get("error"):
        print(f"Config Error: {config['error']}")
    for w in config.get('wallets', []):
        addr = w.get('address', '')
        print(f"  - {w.get('label', 'Unnamed')}: {addr[:8]}...{addr[-6:]}")


def cmd_wallet_summary(args):
    chain_filter = resolve_chain(args.chain) if args.chain else None
    if args.chain and not chain_filter:
        fail(f"Unsupported chain '{args.chain}'")
    rows = []
    for idx, wallet in enumerate(_configured_wallets_or_single(args.address, args.config), start=1):
        address = wallet["address"]
        data = fetch_portfolio([address], args.limit, chain_filter, api_key=args.api_key, config_path=args.config)
        if "error" in data:
            rows.append({"label": _wallet_name(wallet, f"wallet-{idx}"), "address": address, "error": data["error"]})
            continue
        token_balances = data.get("tokenBalances", {})
        app_balances = data.get("appBalances", {})
        rows.append(
            {
                "label": _wallet_name(wallet, f"wallet-{idx}"),
                "address": address,
                "tokenUSD": _safe_float(token_balances.get("totalBalanceUSD")),
                "appUSD": _safe_float(app_balances.get("totalBalanceUSD")),
                "totalUSD": _safe_float(token_balances.get("totalBalanceUSD")) + _safe_float(app_balances.get("totalBalanceUSD")),
                "tokenCount": len((token_balances.get("byToken") or {}).get("edges", [])),
                "appCount": len((app_balances.get("byApp") or {}).get("edges", [])),
            }
        )
    rows.sort(key=lambda item: item.get("totalUSD", -1), reverse=True)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print(format_wallet_summary(rows))


def cmd_allocations(args):
    chain_filter = resolve_chain(args.chain) if args.chain else None
    if args.chain and not chain_filter:
        fail(f"Unsupported chain '{args.chain}'")
    addresses = resolve_address(args.address, args.config)
    totals = {}
    if args.group_by in {"token", "network"}:
        data = fetch_tokens(addresses, args.limit, chain_filter, api_key=args.api_key, config_path=args.config)
        if "error" in data:
            result = data
        else:
            for edge in data.get("byToken", {}).get("edges", []):
                node = edge.get("node", {})
                if args.group_by == "token":
                    key = node.get("symbol", "?")
                else:
                    key = (node.get("network") or {}).get("name", "Unknown")
                totals[key] = totals.get(key, 0.0) + _safe_float(node.get("balanceUSD"))
            result = {"groupBy": args.group_by, "rows": []}
    else:
        data = fetch_apps(addresses, args.limit, chain_filter, api_key=args.api_key, config_path=args.config)
        if "error" in data:
            result = data
        else:
            for edge in data.get("byApp", {}).get("edges", []):
                node = edge.get("node", {})
                key = (node.get("app") or {}).get("displayName", "?")
                totals[key] = totals.get(key, 0.0) + _safe_float(node.get("balanceUSD"))
            result = {"groupBy": args.group_by, "rows": []}
    if "error" not in result:
        grand_total = sum(totals.values()) or 1.0
        rows = [{"name": name, "usd": usd, "pct": (usd / grand_total) * 100} for name, usd in totals.items()]
        rows.sort(key=lambda item: item["usd"], reverse=True)
        result["rows"] = rows[: args.top]
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_allocations(result))


def cmd_snapshot(args):
    chain_filter = resolve_chain(args.chain) if args.chain else None
    if args.chain and not chain_filter:
        fail(f"Unsupported chain '{args.chain}'")
    wallets = _configured_wallets_or_single(args.address, args.config)
    snapshot = {
        "generatedAt": _iso_now(),
        "chain": args.chain,
        "wallets": {},
    }
    for idx, wallet in enumerate(wallets, start=1):
        label = _wallet_name(wallet, f"wallet-{idx}")
        address = wallet["address"]
        snapshot["wallets"][label] = {
            "address": address,
            "portfolio": fetch_portfolio([address], args.limit, chain_filter, api_key=args.api_key, config_path=args.config),
            "tokens": fetch_tokens([address], args.limit, chain_filter, api_key=args.api_key, config_path=args.config),
            "apps": fetch_apps([address], args.limit, chain_filter, api_key=args.api_key, config_path=args.config),
            "claimables": fetch_claimables([address], api_key=args.api_key, config_path=args.config),
        }
        if args.include_tx:
            snapshot["wallets"][label]["tx"] = fetch_transactions([address], args.tx_limit, api_key=args.api_key, config_path=args.config)
    if args.output:
        _write_json(args.output, snapshot)
    if args.json or not args.output:
        print(json.dumps(snapshot, indent=2))


def cmd_diff(args):
    result = {"before": args.before, "after": args.after, "changes": _json_diff(_load_json(args.before), _load_json(args.after))}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_diff(result))


def cmd_validate_config(args):
    config_path = resolve_config_path(args.config)
    config = get_config(args.config)
    issues = []
    wallets = config.get("wallets", [])
    labels = set()
    for idx, wallet in enumerate(wallets, start=1):
        label = wallet.get("label", "").strip()
        address = wallet.get("address", "")
        if not label:
            issues.append(f"wallet {idx}: missing label")
        elif label.lower() in labels:
            issues.append(f"wallet {idx}: duplicate label '{label}'")
        else:
            labels.add(label.lower())
        if not (isinstance(address, str) and address.startswith("0x") and len(address) == 42):
            issues.append(f"wallet {idx}: invalid address '{address}'")
    if config.get("error"):
        issues.append(config["error"])
    result = {
        "config": config_path,
        "walletCount": len(wallets),
        "apiKeyConfigured": bool(get_api_key(args.config, explicit_api_key=args.api_key)),
        "issues": issues,
        "ok": not issues,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Config: {config_path}")
        print(f"Wallets: {len(wallets)}")
        print(f"API Key: {'Set' if result['apiKeyConfigured'] else 'Missing'}")
        if issues:
            print("Issues:")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("No issues found")
    if issues:
        raise SystemExit(1)


# =============================================================================
# Main
# =============================================================================

def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="Path to wallet config JSON")
    common.add_argument("--api-key", help="Override ZAPPER_API_KEY for this invocation")

    parser = argparse.ArgumentParser(
        description="Zapper CLI - Query DeFi data across 50+ chains",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common],
        epilog="""
Examples:
  zapper.py portfolio 0x123...          Portfolio summary
  zapper.py tokens 0x123... --24h       Token holdings with 24h change
  zapper.py apps 0x123...               DeFi positions
  zapper.py nfts 0x123...               NFT holdings
  zapper.py tx 0x123...                 Recent transactions
  zapper.py price ETH                   Token price lookup
  zapper.py claimables 0x123...         Unclaimed rewards
  zapper.py config                      Show configuration
  zapper.py wallet-summary              Summarize configured wallets
"""
    )
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # portfolio
    p = subparsers.add_parser("portfolio", help="Portfolio summary (tokens + DeFi)")
    p.add_argument("address", nargs="?", help="Address or wallet label")
    p.add_argument("--chain", help="Filter by chain (ethereum, base, arbitrum, polygon, solana, etc.)")
    p.add_argument("--short", action="store_true", help="Show only total value")
    p.add_argument("--per-wallet", action="store_true", help="Show each configured wallet")
    p.add_argument("--24h", dest="show_24h", action="store_true", help="Show 24h price changes")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.add_argument("--limit", type=int, default=10, help="Max tokens to show")
    p.set_defaults(func=cmd_portfolio)

    # tokens
    p = subparsers.add_parser("tokens", help="Token holdings")
    p.add_argument("address", nargs="?", help="Address or wallet label")
    p.add_argument("--chain", help="Filter by chain (ethereum, base, arbitrum, polygon, solana, etc.)")
    p.add_argument("--24h", dest="show_24h", action="store_true", help="Show 24h price changes")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.add_argument("--csv", help="Export to CSV file")
    p.add_argument("--limit", type=int, default=20, help="Max tokens to show")
    p.set_defaults(func=cmd_tokens)

    # top-movers
    p = subparsers.add_parser("top-movers", help="Show biggest 24h gainers and losers")
    p.add_argument("address", nargs="?", help="Address or wallet label")
    p.add_argument("--chain", help="Filter by chain (ethereum, base, arbitrum, polygon, solana, etc.)")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.add_argument("--limit", type=int, default=10, help="Max gainers/losers to show")
    p.set_defaults(func=cmd_top_movers)

    # apps
    p = subparsers.add_parser("apps", help="DeFi positions (LPs, lending, staking)")
    p.add_argument("address", nargs="?", help="Address or wallet label")
    p.add_argument("--chain", help="Filter by chain (ethereum, base, arbitrum, polygon, solana, etc.)")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.add_argument("--csv", help="Export to CSV file")
    p.add_argument("--limit", type=int, default=20, help="Max apps to show")
    p.set_defaults(func=cmd_apps)

    # nfts
    p = subparsers.add_parser("nfts", help="NFT holdings")
    p.add_argument("address", nargs="?", help="Address or wallet label")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.add_argument("--limit", type=int, default=10, help="Max NFTs to show")
    p.set_defaults(func=cmd_nfts)

    # tx
    p = subparsers.add_parser("tx", help="Recent transactions")
    p.add_argument("address", nargs="?", help="Address or wallet label")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.add_argument("--csv", help="Export to CSV file")
    p.add_argument("--limit", type=int, default=20, help="Max transactions to show")
    p.set_defaults(func=cmd_tx)

    # price
    p = subparsers.add_parser("price", help="Token price lookup by symbol or address")
    p.add_argument("symbol", help="Token symbol (e.g., ETH) or contract address (0x...)")
    p.add_argument("--chain", dest="chain_id", help="Chain name (ethereum, base, arbitrum, etc.)")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_price)

    # search
    p = subparsers.add_parser("search", help="Search for tokens by name or symbol")
    p.add_argument("query", help="Search query (e.g., 'bitcoin', 'ETH', 'aave')")
    p.add_argument("--limit", type=int, default=10, help="Max results to show")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_search)

    # claimables
    p = subparsers.add_parser("claimables", help="Unclaimed rewards")
    p.add_argument("address", nargs="?", help="Address or wallet label")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_claimables)

    # config
    p = subparsers.add_parser("config", help="Show configuration")
    p.set_defaults(func=cmd_config)

    p = subparsers.add_parser("wallet-summary", help="Summarize one or more wallets")
    p.add_argument("address", nargs="?", help="Address or wallet label")
    p.add_argument("--chain", help="Filter by chain")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.add_argument("--limit", type=int, default=10, help="Max tokens fetched per wallet")
    p.set_defaults(func=cmd_wallet_summary)

    p = subparsers.add_parser("allocations", help="Show portfolio allocation breakdown")
    p.add_argument("address", nargs="?", help="Address or wallet label")
    p.add_argument("--chain", help="Filter by chain")
    p.add_argument("--group-by", choices=["token", "network", "app"], default="token")
    p.add_argument("--limit", type=int, default=100, help="Max rows fetched from the API")
    p.add_argument("--top", type=int, default=15, help="Max rows to print")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_allocations)

    p = subparsers.add_parser("snapshot", help="Capture wallet state to JSON")
    p.add_argument("address", nargs="?", help="Address or wallet label")
    p.add_argument("--chain", help="Filter by chain")
    p.add_argument("--limit", type=int, default=50, help="Max rows fetched per section")
    p.add_argument("--include-tx", action="store_true", help="Include recent transactions")
    p.add_argument("--tx-limit", type=int, default=20, help="Max transactions per wallet")
    p.add_argument("--output", help="Write JSON snapshot to a file")
    p.add_argument("--json", action="store_true", help="Print JSON to stdout")
    p.set_defaults(func=cmd_snapshot)

    p = subparsers.add_parser("diff", help="Compare two saved JSON snapshots")
    p.add_argument("before")
    p.add_argument("after")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_diff)

    p = subparsers.add_parser("validate-config", help="Validate wallet config structure")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_validate_config)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
