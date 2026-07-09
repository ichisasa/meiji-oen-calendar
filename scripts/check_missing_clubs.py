#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
団体マスター(data/clubs.csv)と実際に集まっているイベントデータを突き合わせ、
「この団体、最近イベントが1件も見当たらないのでは？」という抜け漏れ候補を
洗い出すスクリプト。

自動収集(明スポ等)ではカバーしきれない団体・時期を、担当者が手動で
連盟サイトや団体アカウントを確認しに行くための「チェックリスト」を作ることが目的。
完璧な判定ではなく、あくまで「見落とし防止のヒント」として使う。
"""

import csv
import sys
from datetime import date, datetime, timedelta

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


def normalize(s: str) -> str:
    return s.replace(" ", "").replace("　", "")


def load_events(paths):
    """複数のイベントCSVから (team, start_date) のリストを読み込む。日付が読めない行はスキップ。"""
    events = []
    for path in paths:
        try:
            with open(path, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    team = row.get("team") or row.get("club") or ""
                    date_raw = row.get("start_date_raw") or row.get("start_date") or ""
                    d = parse_loose_date(date_raw)
                    if team.strip():
                        events.append({"team": team.strip(), "date": d})
        except FileNotFoundError:
            print(f"[警告] {path} が見つからないためスキップします", file=sys.stderr)
    return events


def parse_loose_date(text: str):
    """'2026/6/1' 'YYYY/MM/DD' '06/30'（年なし）など、揺れのある日付文字列を可能な範囲でdateに変換する。
    パースできない場合は None を返す（=期間判定には使わないが、団体の存在チェックには使う）。"""
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
        key = normalize(club["club_name"])
        matched_events = [e for e in events if key in normalize(e["team"])]

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


def find_unknown_teams(clubs, events):
    """
    イベントデータには出てくるのに、団体マスター(clubs.csv)に無い団体名を探す。
    団体マスター自体の漏れ（カバー率の問題）に気づくための逆方向チェック。
    """
    known_keys = [normalize(c["club_name"]) for c in clubs]

    unknown = {}  # team_name -> 出現回数
    for e in events:
        team = e["team"].strip()
        if not team:
            continue
        norm_team = normalize(team)
        # マスターのどの団体名も、このteam文字列に含まれていなければ「未知」とみなす
        if not any(key in norm_team for key in known_keys):
            unknown[team] = unknown.get(team, 0) + 1

    # 出現回数が多い順に並べる（誤記・表記ゆれより「本当に抜けている団体」を優先して見せるため）
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

    lines.append(f"\n## 団体マスターに無いのにデータに登場する団体名（{len(unknown_teams)}件）\n")
    lines.append("表記ゆれの可能性もありますが、団体マスター自体の抜けかもしれません。多く出現するものから優先確認してください。\n")
    for team, count in unknown_teams:
        lines.append(f"- [ ] {team}（{count}件）")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    clubs = load_clubs("data/clubs.csv")
    events = load_events(
        ["data/events.csv", "data/events_archive.csv", "data/meisupo_events.csv"]
    )
    never_seen, quiet_recently = find_missing_clubs(clubs, events)
    unknown_teams = find_unknown_teams(clubs, events)
    report = render_report(never_seen, quiet_recently, unknown_teams)

    out_path = "data/missing_clubs_report.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(report)
    print(f"\n{out_path} に保存しました", file=sys.stderr)
