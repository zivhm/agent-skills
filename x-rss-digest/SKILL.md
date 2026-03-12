---
name: x-rss-digest
description: Follow selected X or Twitter accounts through Nitter-style RSS feeds, keep only new posts, filter low-signal content, and generate an organized digest. Use when Codex or a human operator needs a deterministic, script-based way to monitor curated accounts without browsing the full X timeline.
---

# X RSS Digest

Use the bundled CLI to fetch configured RSS feeds, filter obvious slop, and emit only unseen posts.

## Commands

```powershell
python scripts/x_rss_digest.py --config references/sample-config.json --dry-run
python scripts/x_rss_digest.py --config references/sample-config.json --json
python scripts/x_rss_digest.py --config my-feeds.json --output digest.txt
python scripts/x_rss_digest.py --config my-feeds.json --state-file my-state.json
```

## Rules

- Keep the fetch layer deterministic: RSS only for now
- Store only feed definitions and filter rules in the config file
- Track seen post ids in a local state file so each run emits only new items
- Filter obvious low-signal content before digest generation
- Prefer short, extractive summaries over freeform rewriting
- Use `--dry-run` when testing so the state file does not advance

## Config

The config file is JSON with:

- `feeds`: array of feed definitions
- `filters`: global filter rules
- `output`: formatting and grouping preferences

See `references/sample-config.json` for the exact shape.
