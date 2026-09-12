#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data/events.csv（手動収集）、data/meisupo_events.csv（明スポ自動収集）、
data/big6_baseball_events.csv、data/ai_scraped_events.csv（AI抽出）を統合し、
本日以降のイベントだけを抽出して、GitHub Pages公開用の docs/events.json を作る。

【優先順位】同じ試合が複数ソースにまたがって存在する場合、以下の優先順で
「主役カード」を選ぶ（プロジェクトの核心的価値である「主催者への確認URL」を
できるだけ前面に出すため）:
  1. 自動収集（AI抽出・big6等の公式サイト由来）
  2. 明大スポーツ新聞部（meisupo.net）
  3. 元父母の会 手動収集

団体名は normalize_team.py で正式名称に統一してから出力する。
日付が読み取れない行（「8月下旬」等）は、公開カレンダーには含めず件数だけ表示する。
"""

import csv
import json
import sys
from collections import defaultdict
from datetime import date, datetime

from normalize_team import TeamNameResolver
from scrape_meisupo import load_venue_addresses, load_venue_aliases, resolve_venue_address


def parse_loose_date(text: str):
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def source_priority(source: str) -> int:
    """数字が小さいほど優先度が高い（主役カードとして採用される）。"""
    if isinstance(source, str) and source.startswith("AI抽出"):
        return 0
    if source == "big6.gr.jp":
        return 0
    if source == "meisupo.net":
        return 1
    return 2  # 元父母の会 手動収集 など


def load_events_csv(path, resolver, venue_addresses, venue_aliases):
    items = []
    try:
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                team_raw = (row.get("team") or "").strip()
                if not team_raw:
                    continue
                d = parse_loose_date(row.get("start_date_raw"))
                venue = (row.get("venue") or "").strip()
                venue_address = (row.get("venue_address") or "").strip()
                if not venue_address and venue:
                    venue_address = resolve_venue_address(venue, venue_addresses, venue_aliases)
                items.append(
                    {
                        "date": d,
                        "date_raw": (row.get("start_date_raw") or "").strip(),
                        "time": (row.get("start_time") or "").strip(),
                        "team": resolver.resolve(team_raw) or team_raw,
                        "event_name": (row.get("event_name") or "").strip(),
                        "venue": venue,
                        "venue_address": venue_address,
                        "url": (row.get("url") or "").strip(),
                        "source": row.get("source") or "元父母の会 手動収集",
                    }
                )
    except FileNotFoundError:
        print(f"[警告] {path} が見つかりません", file=sys.stderr)
    return items


def merge_duplicate_events(items):
    """
    団体名+日付が一致するイベントを1件に統合する。
    イベント名はキーに含めない（明スポとAI抽出で表現が違うことが多いため）。
    優先順位が最も高いソースの内容を「主役」として採用し、
    明スポのURLは meisupo_url として、公式サイト系のURLは official_url として保持する。
    """
    groups = defaultdict(list)
    for i in items:
        key = (i["team"], i["date"])
        groups[key].append(i)

    merged = []
    for key, group in groups.items():
        group.sort(key=lambda e: source_priority(e["source"]))
        primary = group[0]

        official_url = ""
        meisupo_url = ""
        for e in group:
            if e["source"] == "meisupo.net" and not meisupo_url:
                meisupo_url = e["url"]
            elif e["source"] != "meisupo.net" and not official_url:
                official_url = e["url"]

        merged_event = dict(primary)
        merged_event["official_url"] = official_url
        merged_event["meisupo_url"] = meisupo_url
        merged.append(merged_event)

    return merged


def build_calendar(sources, resolver, today=None):
    if today is None:
        today = date.today()

    venue_addresses = load_venue_addresses("data/venues.csv")
    venue_aliases = load_venue_aliases("data/venue_aliases.csv")

    all_items = []
    for path in sources:
        all_items.extend(load_events_csv(path, resolver, venue_addresses, venue_aliases))

    with_date = [i for i in all_items if i["date"] is not None]
    without_date = len(all_items) - len(with_date)

    merged = merge_duplicate_events(with_date)

    upcoming = [i for i in merged if i["date"] >= today]
    upcoming.sort(key=lambda i: (i["date"], i["time"]))

    print(
        f"統合前: {len(all_items)}件 / 日付不明でスキップ: {without_date}件 / "
        f"重複統合後: {len(merged)}件 / 本日以降で公開対象: {len(upcoming)}件",
        file=sys.stderr,
    )
    return upcoming


def to_json_ready(items):
    out = []
    for i in items:
        out.append(
            {
                "date": i["date"].isoformat(),
                "time": i["time"],
                "team": i["team"],
                "event_name": i["event_name"],
                "venue": i["venue"],
                "venue_address": i["venue_address"],
                "url": i["url"],
                "official_url": i.get("official_url", ""),
                "meisupo_url": i.get("meisupo_url", ""),
                "source": i["source"],
            }
        )
    return out


if __name__ == "__main__":
    resolver = TeamNameResolver(clubs_path="data/clubs.csv", aliases_path="data/team_aliases.csv")
    upcoming = build_calendar(
        [
            "data/events.csv",
            "data/meisupo_events.csv",
            "data/big6_baseball_events.csv",
            "data/ai_scraped_events.csv",
        ],
        resolver,
    )

    with open("docs/events.json", "w", encoding="utf-8") as f:
        json.dump(to_json_ready(upcoming), f, ensure_ascii=False, indent=2)

    print("docs/events.json に保存しました", file=sys.stderr)
