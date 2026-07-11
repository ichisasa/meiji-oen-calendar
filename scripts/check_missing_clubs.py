#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
団体マスター(data/clubs.csv)と実際に集まっているイベントデータを突き合わせ、
「この団体、最近イベントが1件も見当たらないのでは？」という抜け漏れ候補を
洗い出すスクリプト。

normalize_team.py（表記ゆれ変換辞書）を使って団体名を正規化してから突き合わせるため、
「水泳（競泳）部」と「水泳部（競泳）」のような表記ゆれによる誤検知を防ぐ。
"""

import csv
import sys
from datetime import date, datetime, timedelta

from normalize_team import TeamNameResolver

# 直近イベントが無いと「要確認」フラグを立てる期間（前後）
LOOKAROUND_DAYS = 90


def load_clubs(path):
    clubs = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            clubs.append(
                {
                    "category": row["category"].strip(),
                    "club_name": row["club_name"].strip(),
                }
            )
    return clubs


def load_events(paths, resolver: TeamNameResolver):
    """
    複数のイベントCSVから (resolved_club, date, raw_team) のリストを読み込む。
    team名は normalize_team.py で正式名称に解決してから使う。
    解決できなかった team はそのまま raw として保持し、後段の「未知の団体名」検出に使う。
    """
    events = []
    for path in paths:
        try:
            with open(path, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    raw_team = row.get("team") or row.get("club") or ""
                    raw_team = raw_team.strip()
                    if not raw_team:
                        continue
                    date_raw = row.get("start_date_raw") or row.get("start_date") or ""
                    d = parse_loose_date(date_raw)
                    resolved = resolver.resolve(raw_team)
                    events.append({"raw_team": raw_team, "resolved_club": resolved, "date": d})
        except FileNotFoundError:
            print(f"[警告] {path} が見つからないためスキップします", file=sys.stderr)
    return events


def parse_loose_date(text: str):
    """'2026/6/1' 'YYYY/MM/DD' '06/30'（年なし）など、揺れのある日付文字列を可能な範囲でdateに変換する。
    パースできない場合は None を返す。"""
    text = text.strip()
    if not text:
        return None
    fmts = ["%Y/%m/%d", "%Y-%m-%d"]
    for fmt in fmts:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def find_missing_clubs(clubs, events, today=None):
    if today is None:
        today = date.today()
    window_start = today - timedelta(days=LOOKAROUND_DAYS)
    window_end = today + timedelta(days=LOOKAROUND_DAYS)

    never_seen = []
    quiet_recently = []

    for club in clubs:
        matched_events = [e for e in events if e["resolved_club"] == club["club_name"]]

        if not matched_events:
            never_seen.append(club)
            continue

        has_recent = any(
            e["date"] and window_start <= e["date"] <= window_end
            for e in matched_events
        )
        if not has_recent:
            quiet_recently.append(club)

    return never_seen, quiet_recently


def find_unknown_teams(events):
    """resolve() できなかった（=未知の）団体名を、出現回数の多い順に返す。"""
    unknown = {}
    for e in events:
        if e["resolved_club"] is None:
            unknown[e["raw_team"]] = unknown.get(e["raw_team"], 0) + 1
    return sorted(unknown.items(), key=lambda x: -x[1])


def render_report(never_seen, quiet_recently, unknown_teams, today=None):
    if today is None:
        today = date.today()
    lines = []
    lines.append(f"# 団体データ抜け漏れチェック（{today.isoformat()} 時点）\n")

    lines.append(f"## データに一度も登場しない団体（{len(never_seen)}件）\n")
    lines.append("収集元のどこにも情報が見つかっていません。連盟サイトや団体アカウントを確認してください。\n")
    for c in never_seen:
        lines.append(f"- [ ] {c['category']} {c['club_name']}")

    lines.append(f"\n## 直近{LOOKAROUND_DAYS}日以内にイベントが見当たらない団体（{len(quiet_recently)}件）\n")
    lines.append("オフシーズンの可能性もありますが、念のため確認をおすすめします。\n")
    for c in quiet_recently:
        lines.append(f"- [ ] {c['category']} {c['club_name']}")

    lines.append(f"\n## 表記ゆれ辞書でも解決できない団体名（{len(unknown_teams)}件）\n")
    lines.append("team_aliases.csv に登録すべき新しい表記ゆれか、団体マスター自体の漏れの可能性があります。\n")
    for team, count in unknown_teams:
        lines.append(f"- [ ] {team}（{count}件）")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    resolver = TeamNameResolver(clubs_path="data/clubs.csv", aliases_path="data/team_aliases.csv")
    clubs = load_clubs("data/clubs.csv")
    events = load_events(
        ["data/events.csv", "data/events_archive.csv", "data/meisupo_events.csv"],
        resolver,
    )
    never_seen, quiet_recently = find_missing_clubs(clubs, events)
    unknown_teams = find_unknown_teams(events)
    report = render_report(never_seen, quiet_recently, unknown_teams)

    out_path = "data/missing_clubs_report.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(report)
    print(f"\n{out_path} に保存しました", file=sys.stderr)
