
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data/events.csv（手動収集の現在データ）と data/meisupo_events.csv（自動収集データ）を
統合し、本日以降のイベントだけを抽出して、GitHub Pages公開用の docs/events.json を作る。

団体名は normalize_team.py で正式名称に統一してから出力する。
日付が読み取れない行（「8月下旬」等）は、公開カレンダーには含めず件数だけ表示する。
"""

import csv
import json
import sys
from datetime import date, datetime

from normalize_team import TeamNameResolver


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


def load_events_csv(path, resolver):
    items = []
    try:
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                team_raw = (row.get("team") or "").strip()
                if not team_raw:
                    continue
                d = parse_loose_date(row.get("start_date_raw"))
                items.append(
                    {
                        "date": d,
                        "date_raw": (row.get("start_date_raw") or "").strip(),
                        "time": (row.get("start_time") or "").strip(),
                        "team": resolver.resolve(team_raw) or team_raw,
                        "event_name": (row.get("event_name") or "").strip(),
                        "venue": (row.get("venue") or "").strip(),
                        "venue_address": (row.get("venue_address") or "").strip(),
                        "url": (row.get("url") or "").strip(),
                        "source": row.get("source", "元父母の会 手動収集"),
                    }
                )
    except FileNotFoundError:
        print(f"[警告] {path} が見つかりません", file=sys.stderr)
    return items


def build_calendar(sources, resolver, today=None):
    if today is None:
        today = date.today()

    all_items = []
    for path in sources:
        all_items.extend(load_events_csv(path, resolver))

    # URLが同じものは重複とみなし、1件にまとめる
    seen_urls = set()
    deduped = []
    for item in all_items:
        key = item["url"] or f"{item['team']}|{item['event_name']}|{item['date_raw']}"
        if key in seen_urls:
            continue
        seen_urls.add(key)
        deduped.append(item)

    with_date = [i for i in deduped if i["date"] is not None]
    without_date = len(deduped) - len(with_date)

    upcoming = [i for i in with_date if i["date"] >= today]
    upcoming.sort(key=lambda i: (i["date"], i["time"]))

    print(
        f"統合: {len(deduped)}件（重複除去後）/ 日付不明でスキップ: {without_date}件 / "
        f"本日以降で公開対象: {len(upcoming)}件",
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
                "source": i["source"],
            }
        )
    return out


if __name__ == "__main__":
    resolver = TeamNameResolver(clubs_path="data/clubs.csv", aliases_path="data/team_aliases.csv")
    upcoming = build_calendar(["data/events.csv", "data/meisupo_events.csv", "data/big6_baseball_events.csv","data/ai_scraped_events.csv"], resolver)

    with open("docs/events.json", "w", encoding="utf-8") as f:
        json.dump(to_json_ready(upcoming), f, ensure_ascii=False, indent=2)

    print("docs/events.json に保存しました", file=sys.stderr)
