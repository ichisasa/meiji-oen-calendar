#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
big6.gr.jp（東京六大学野球連盟）から、明治大学が出場する試合の日程を取得するスクリプト。

- robots.txt で自動アクセスが許可されていることを確認済み（2026年7月時点）
- 試合詳細ページへのリンク（game.php）のURLパラメータに日付・対戦カードが
  そのままエンコードされているため、見た目のレイアウトに頼らずそこから抽出する。
  例: system/prog/game.php?m=pc&e=league&s=2026s&gd=2026-04-11&gnd=1&vs=TM1
      → 2026-04-11、東大(T) vs 明大(M) の第1試合
- 開始時刻は表のレイアウトに依存し確実な抽出が難しいため、今回はあえて空欄のまま出力する
  （誤った時刻を載せるより、空欄で「要確認」にする方が安全という判断）。
- 会場は全試合共通で明治神宮野球場（神宮球場）固定。
"""

import csv
import re
import sys
import time
from datetime import date, datetime

import requests

BASE_URL = "https://www.big6.gr.jp"
HEADERS = {
    "User-Agent": "meiji-oen-calendar-bot/1.0 (+https://github.com/ichisasa/meiji-oen-calendar)"
}
REQUEST_INTERVAL_SEC = 1.5

# vs= パラメータの1文字目・2文字目に使われるチーム記号
TEAM_CODE = {
    "W": "早稲田大学",
    "K": "慶應義塾大学",
    "M": "明治大学",
    "H": "法政大学",
    "T": "東京大学",
    "R": "立教大学",
}

GAME_LINK_RE = re.compile(
    r"game\.php\?m=pc&e=league&s=(?P<season>\d{4}[sa])&gd=(?P<date>\d{4}-\d{2}-\d{2})"
    r"&gnd=(?P<gnd>\d)&vs=(?P<vs>[A-Z]{2}\d)"
)


def fetch(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    time.sleep(REQUEST_INTERVAL_SEC)
    return resp.text


def current_season_codes(today: date):
    """本日時点で見るべきシーズンコードの候補を返す（春→秋の順で試す）。"""
    year = today.year
    return [f"{year}s", f"{year}a"]


def parse_meiji_games(html: str, season: str):
    games = []
    seen = set()
    for m in GAME_LINK_RE.finditer(html):
        if m.group("season") != season:
            continue
        vs = m.group("vs")
        team1_code, team2_code = vs[0], vs[1]
        if "M" not in (team1_code, team2_code):
            continue  # 明治大学が絡む試合だけを対象にする

        game_date = datetime.strptime(m.group("date"), "%Y-%m-%d").date()
        opponent_code = team1_code if team2_code == "M" else team2_code
        opponent = TEAM_CODE.get(opponent_code, opponent_code)

        key = (m.group("date"), vs)
        if key in seen:
            continue
        seen.add(key)

        detail_url = (
            f"{BASE_URL}/system/prog/game.php?m=pc&e=league&s={season}"
            f"&gd={m.group('date')}&gnd={m.group('gnd')}&vs={vs}"
        )

        games.append(
            {
                "date": game_date,
                "opponent": opponent,
                "url": detail_url,
            }
        )
    return games


def collect_upcoming_games(today: date = None):
    if today is None:
        today = date.today()

    all_games = []
    for season in current_season_codes(today):
        url = f"{BASE_URL}/game/league/{season}/{season}_schedule.html"
        print(f"[fetch] {url}", file=sys.stderr)
        try:
            html = fetch(url)
        except requests.HTTPError as e:
            print(f"[情報] {url} は取得できませんでした（{e}）。スキップします。", file=sys.stderr)
            continue
        games = parse_meiji_games(html, season)
        all_games.extend(games)

    upcoming = [g for g in all_games if g["date"] >= today]
    upcoming.sort(key=lambda g: g["date"])

    season_label = "春季" if today.month <= 7 else "秋季"
    events = []
    for g in upcoming:
        events.append(
            {
                "start_date_raw": g["date"].strftime("%Y/%m/%d"),
                "start_time": "",  # 確実に取れないため空欄（要確認）
                "end_date_raw": "",
                "team": "硬式野球部",
                "event_name": f"東京六大学野球{season_label}リーグ戦 対{g['opponent']}",
                "venue": "明治神宮野球場",
                "venue_address": "",  # build_public_calendar側でvenues.csv/venue_aliases.csvから補完
                "url": g["url"],
                "source": "big6.gr.jp",
            }
        )
    return events


def save_csv(events, path):
    fieldnames = [
        "start_date_raw", "start_time", "end_date_raw", "team",
        "event_name", "venue", "venue_address", "url", "source",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(events)


if __name__ == "__main__":
    events = collect_upcoming_games()
    out_path = "data/big6_baseball_events.csv"
    save_csv(events, out_path)
    print(f"{len(events)} 件の明治大学の試合を {out_path} に保存しました", file=sys.stderr)
