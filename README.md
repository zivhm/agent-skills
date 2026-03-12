# Agent Skills

Each skill should stay portable, CLI-testable, and easy to reuse from another machine or repo checkout. Treat `SKILL.md` as the runtime instruction file for agents, and use this README as a quick human-oriented index for the workspace.

## Current Skills

- `ccxt-exchanges`: Query centralized exchange market data through a local Python CLI built on `ccxt`. Good for listings, tickers, order books, candles, funding, and JSON snapshots across supported exchanges.
- `hyperliquid`: Query Hyperliquid market and account data through a local Python CLI. Good for mids, books, candles, funding, user state, open orders, and snapshot/diff monitoring flows.
- `morning-market-update`: Generate a Telegram-formatted market update by combining data from the local market-data skills. Good for repeatable daily summaries across crypto, stocks, forex, and macro extras.
- `x-rss-digest`: Fetch curated X/Twitter RSS feeds, filter low-signal posts, track seen items, and emit a clean incremental digest. Good for deterministic monitoring without browsing a social feed directly.
- `yfinance-stocks`: Query equities and ETFs through a local Python CLI built on `yfinance`. Good for quotes, history, metadata, financials, options, news, and JSON snapshots.
- `zapper-api`: Query DeFi wallet and token data through a local Python CLI for the Zapper GraphQL API. Good for portfolios, token holdings, NFTs, transactions, prices, claimables, and portfolio snapshots.

## Ideal Skill Structure

Required:

- `SKILL.md`
- `scripts/` if the skill performs repeatable work

Optional:

- `references/` for sample configs, schemas, focused docs, or examples
- `assets/` only when the skill truly needs static templates or output resources

Avoid by default:

- `agents/openai.yaml`
- `README.md` inside individual skill folders unless there is a deliberate workspace-level reason
- `CHANGELOG.md`
- duplicated process docs that repeat `SKILL.md`

## Recommended Layout

```text
skill-name/
  SKILL.md
  scripts/
    tool.py
  references/
    sample-config.json
  assets/
```

## Skill Standards

- Keep the smallest useful deterministic workflow.
- Prefer scripts over freeform repeated reasoning.
- Keep file paths and defaults relative to the skill folder when practical.
- Separate config, state, and secrets cleanly.
- Prefer JSON for user-editable config.
- Expose `--help` on scripts and `--json` where structured output is useful.
- Make local state safe to delete and rebuild.
- Keep `SKILL.md` examples aligned with the real CLI.
- Validate and smoke-test before finishing changes.
- Remove `__pycache__`, `.cache`, temp state, and other generated junk before wrapping up.

## Notes For Future Additions

- Start with the script first when the workflow is repeatable.
- Add sample config only if it helps a human run the skill quickly.
- Keep per-skill documentation in `SKILL.md`; use `references/` for details that do not belong in the main instruction file.
- Favor one-line, shell-safe examples with relative paths.
