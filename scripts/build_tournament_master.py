#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
過去のイベントアーカイブ(data/events_archive.csv)から、
「団体ごとに毎年のように繰り返し登場する大会」を自動抽出し、
大会マスターの叩き台(data/tournament_master_draft.csv)を作るスクリプト。

大会名は年によって回数表記が変わる（第100回→第101回、2023年度→2024年度）ため、
数字を取り除いた「型」でグルーピングし、複数年にわたって出現するものを
「毎年開催されている定例大会」の候補として拾い出す。
"""

import csv
import re
from collections import defaultdict

MIN_OCCURRENCES = 2  # これ以上出現したら「定例大会」候補とみなす


def normalize_name(name: str) -> str:
    """大会名から年・回数などの数字要素を取り除き、比較しやすい『型』にする。"""
    s = name
    # 全角数字を半角に統一
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    # 数字の連続を除去（第100回 → 第回、2023年度 → 年度 など）
    s = re.sub(r"\d+", "", s)
    # 記号や空白のゆれも軽く吸収
    s = re.sub(r"[　\s]+", "", s)
    return s.strip()


def extract_year(date_raw: str):
    m = re.search(r"(20\d{2})", date_raw)
    return int(m.group(1)) if m else None


def load_archive(path):
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def build_tournament_master(rows):
    groups = defaultdict(list)
    for row in rows:
        team = (row.get("team") or "").strip()
        event_name = (row.get("event_name") or "").strip()
        date_raw = (row.get("start_date_raw") or "").strip()
        url = (row.get("url") or "").strip()
        if not team or not event_name:
            continue
        key = (team, normalize_name(event_name))
        groups[key].append(
            {
                "event_name": event_name,
                "year": extract_year(date_raw),
                "url": url,
            }
        )

    master = []
    for (team, norm_name), items in groups.items():
        years = sorted({i["year"] for i in items if i["year"]})
        if len(items) < MIN_OCCURRENCES:
            continue
        # 一番よく登場した表記をサンプル名として採用
        names = [i["event_name"] for i in items]
        sample_name = max(set(names), key=names.count)
        sample_url = next((i["url"] for i in items if i["url"]), "")
        master.append(
            {
                "team": team,
                "tournament_name_sample": sample_name,
                "occurrence_count": len(items),
                "years_seen": ",".join(str(y) for y in years),
                "sample_url": sample_url,
            }
        )

    master.sort(key=lambda r: (r["team"], -r["occurrence_count"]))
    return master


def save_csv(master, path):
    fieldnames = ["team", "tournament_name_sample", "occurrence_count", "years_seen", "sample_url"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(master)


if __name__ == "__main__":
    rows = load_archive("data/events_archive.csv")
    master = build_tournament_master(rows)
    save_csv(master, "data/tournament_master_draft.csv")
    print(f"{len(master)} 件の定例大会候補を抽出しました")
    for m in master[:20]:
        print(f"- {m['team']} / {m['tournament_name_sample']} ({m['occurrence_count']}回, {m['years_seen']})")
