#!/usr/bin/env python3
"""Incremental digest builder for curated X/Nitter RSS feeds."""

import argparse
import datetime as dt
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def get_text(self):
        return " ".join(self.parts)


DEFAULT_STATE_NAME = ".state.json"


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def strip_html(text):
    parser = _HTMLStripper()
    parser.feed(text or "")
    return unescape(parser.get_text())


def normalize_text(text):
    text = strip_html(text or "")
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def resolve_path(base_dir, maybe_path):
    value = Path(maybe_path)
    if value.is_absolute():
        return value
    return (base_dir / value).resolve()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def fetch_feed(feed_path_or_url):
    if "://" in feed_path_or_url:
        with urllib.request.urlopen(feed_path_or_url, timeout=20) as response:
            content = response.read()
    else:
        content = Path(feed_path_or_url).read_bytes()
    root = ET.fromstring(content)
    channel = root.find("channel")
    if channel is None:
        return []
    items = []
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link or title).strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        description = normalize_text(item.findtext("description") or "")
        published = None
        if pub_date:
            try:
                published = parsedate_to_datetime(pub_date).astimezone(dt.timezone.utc).isoformat()
            except Exception:
                published = pub_date
        items.append(
            {
                "guid": guid,
                "link": link,
                "title": normalize_text(title),
                "description": description,
                "publishedAt": published,
            }
        )
    return items


def is_retweet(text):
    lowered = text.lower()
    return lowered.startswith("rt by ") or lowered.startswith("rt @") or lowered.startswith("rt:")


def is_reply(text):
    return text.startswith("@")


def should_keep(item, feed_cfg, filters):
    text = item["description"] or item["title"]
    lowered = text.lower()
    if not text:
        return False
    if not feed_cfg.get("include_replies", False) and is_reply(text):
        return False
    if not feed_cfg.get("include_retweets", False) and is_retweet(text):
        return False
    if len(text) < filters.get("min_chars", 0):
        return False
    for prefix in filters.get("drop_if_startswith", []):
        if lowered.startswith(prefix.lower()):
            return False
    for needle in filters.get("drop_if_contains", []):
        if needle.lower() in lowered:
            return False
    return True


def summarize(item):
    text = item["description"] or item["title"]
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= 220:
        return text
    return text[:217].rstrip() + "..."


def load_state(path):
    if not Path(path).exists():
        return {"seen": {}, "lastRun": None}
    return load_json(path)


def build_digest(config, state, config_dir):
    filters = config.get("filters", {})
    output_cfg = config.get("output", {})
    grouped = {}
    seen = state.setdefault("seen", {})
    max_items = output_cfg.get("max_items", 20)
    max_per_group = output_cfg.get("max_per_group", 8)
    collected = []

    for feed in sorted(config.get("feeds", []), key=lambda row: row.get("priority", 999)):
        handle = feed["handle"]
        rss_source = feed["rss_url"]
        rss_path = rss_source if "://" in rss_source else str(resolve_path(config_dir, rss_source))
        items = fetch_feed(rss_path)
        feed_seen = set(seen.get(handle, []))
        for item in items:
            if item["guid"] in feed_seen:
                continue
            if not should_keep(item, feed, filters):
                continue
            collected.append(
                {
                    "handle": handle,
                    "tags": feed.get("tags", []),
                    "guid": item["guid"],
                    "publishedAt": item["publishedAt"],
                    "summary": summarize(item),
                    "link": item["link"],
                }
            )

    collected.sort(key=lambda row: (row.get("publishedAt") or "", row["handle"]), reverse=True)
    collected = collected[:max_items]

    group_by = config.get("output", {}).get("group_by", "tag")
    for row in collected:
        if group_by == "author":
            keys = [row["handle"]]
        else:
            keys = row["tags"] or [row["handle"]]
        for key in keys:
            grouped.setdefault(key, [])
            if len(grouped[key]) < max_per_group:
                grouped[key].append(row)
    return collected, grouped


def render_digest(grouped, include_links=True):
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"X Digest — {timestamp}"]
    total = sum(len(rows) for rows in grouped.values())
    lines.append(f"New posts: {total}")
    if total == 0:
        lines.append("")
        lines.append("No new posts.")
        return "\n".join(lines)
    for group in sorted(grouped.keys()):
        lines.append("")
        lines.append(group.upper())
        for row in grouped[group]:
            lines.append(f"- @{row['handle']}: {row['summary']}")
            if include_links and row.get("link"):
                lines.append(f"  Link: {row['link']}")
    return "\n".join(lines)


def update_state(state, collected):
    state["lastRun"] = dt.datetime.now(dt.timezone.utc).isoformat()
    for row in collected:
        state.setdefault("seen", {}).setdefault(row["handle"], [])
        if row["guid"] not in state["seen"][row["handle"]]:
            state["seen"][row["handle"]].append(row["guid"])
        state["seen"][row["handle"]] = state["seen"][row["handle"]][-200:]
    return state


def main():
    parser = argparse.ArgumentParser(description="Build an incremental digest from curated X RSS feeds")
    parser.add_argument("--config", required=True, help="Path to the feed config JSON")
    parser.add_argument("--state-file", help="Path to the state file; defaults to config_dir/.state.json")
    parser.add_argument("--output", help="Write the rendered digest to a file")
    parser.add_argument("--json", action="store_true", help="Print the collected posts and grouping as JSON")
    parser.add_argument("--dry-run", action="store_true", help="Do not update the state file")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    config_dir = config_path.parent
    state_path = Path(args.state_file).resolve() if args.state_file else config_dir / DEFAULT_STATE_NAME

    config = load_json(config_path)
    state = load_state(state_path)
    collected, grouped = build_digest(config, state, config_dir)

    if args.json:
        payload = {"collected": collected, "grouped": grouped}
        print(json.dumps(payload, indent=2))
    else:
        text = render_digest(grouped, include_links=config.get("output", {}).get("include_links", True))
        if args.output:
            Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(text)

    if not args.dry_run:
        save_json(state_path, update_state(state, collected))


if __name__ == "__main__":
    main()
