#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
meisupo.net (明大スポーツ新聞部) から体育会全46部の「試合予定・結果」を取得するスクリプト。

- robots.txt で自動アクセスが許可されていることを確認済み（2026年7月時点）
- サーバー負荷を配慮し、リクエスト間に必ず待機時間を入れる
- 一覧ページ(/result/, /result/page/N/)から日付・大会名・競技名・詳細URLを取得
- 各詳細ページ(/result/{id}/)から会場・試合結果を取得
- 明治大学元父母の会「meiji-oen-calendar」プロジェクトの一部として作成
"""

import csv
import re
import sys
import time
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

from normalize_team import TeamNameResolver, normalize as normalize_text

BASE_URL = "https://meisupo.net"
LIST_URL = f"{BASE_URL}/result/"
LIST_PAGE_URL = f"{BASE_URL}/result/page/{{page}}/"

# サイトへの配慮: 誰からのアクセスか分かるUser-Agentにし、リクエスト間隔を空ける
HEADERS = {
    "User-Agent": "meiji-oen-calendar-bot/1.0 (+https://github.com/ichisasa/meiji-oen-calendar)"
}
REQUEST_INTERVAL_SEC = 1.5  # 1リクエストごとの待機時間（サーバーへの配慮）

# 今回の巡回で読みにいく一覧ページの最大数。
# 直近に更新された順に並んでいるため、大きくしすぎるとサーバー負荷になる。
# 元父母の会の用途は「これから開催されるイベント」なので、ひとまず15ページ分（約220件）で十分。
MAX_LIST_PAGES = 15


def fetch(url: str) -> str:
    """URLを取得してHTML文字列を返す。取得のたびに一定時間待機する。"""
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    time.sleep(REQUEST_INTERVAL_SEC)
    return resp.text


def parse_date(text: str):
    """'2026.12.06 (  日 )' のような文字列から date オブジェクトを取り出す。"""
    m = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", text)
    if not m:
        return None
    y, mo, d = map(int, m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def split_title_and_club(raw_title: str):
    """
    'ジャパンオープン2026（３日目） （水泳（競泳） ）' のような文字列を
    大会名と競技名（部活名）に分割する。
    競技名側にも括弧が含まれる場合があるため、末尾から対応する開き括弧を
    深さカウントで探す（正規表現だと入れ子に弱いため）。
    """
    s = raw_title.strip()
    if not s.endswith("）") and not s.endswith(")"):
        return s, ""

    close_chars = {"）", ")"}
    open_chars = {"（", "("}
    depth = 0
    for i in range(len(s) - 1, -1, -1):
        c = s[i]
        if c in close_chars:
            depth += 1
        elif c in open_chars:
            depth -= 1
            if depth == 0:
                club = s[i + 1 : -1].strip()
                title = s[:i].strip()
                return title, club
    return s, ""


def parse_list_page(html: str):
    """一覧ページから (date, title, club, detail_url) のリストを返す。"""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for row in soup.select("table tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        date_cell, link_cell = cells[0], cells[1]
        a_tag = link_cell.find("a")
        if not a_tag or not a_tag.get("href"):
            continue

        event_date = parse_date(date_cell.get_text())
        raw_title = a_tag.get_text(strip=True)
        title, club = split_title_and_club(raw_title)
        detail_url = a_tag["href"]
        if not detail_url.startswith("http"):
            detail_url = BASE_URL + detail_url

        if event_date is None:
            continue

        results.append(
            {
                "date": event_date,
                "title": title,
                "club": club,
                "detail_url": detail_url,
            }
        )
    return results


def parse_detail_page(html: str):
    """詳細ページから 会場・試合結果 等を辞書で返す。"""
    soup = BeautifulSoup(html, "html.parser")
    info = {}
    for row in soup.select("table tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True)
        value = cells[1].get_text(strip=True)
        if label:
            info[label] = value
    return info


def load_venue_aliases(path="data/venue_aliases.csv"):
    """会場名の表記ゆれ辞書（alias -> canonical）を読み込む。"""
    alias_map = {}
    try:
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                alias = (row.get("alias") or "").strip()
                canonical = (row.get("canonical") or "").strip()
                if alias:
                    alias_map[normalize_text(alias)] = canonical
    except FileNotFoundError:
        print(f"[警告] {path} が見つからないため会場名の表記ゆれ吸収はスキップします", file=sys.stderr)
    return alias_map


def load_venue_addresses(path="data/venues.csv"):
    """会場名 -> 住所 の対応表を読み込む。見つからなければ空の辞書を返す。"""
    addresses = {}
    try:
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("venue_name") or "").strip()
                addr = (row.get("venue_address") or "").strip()
                if name:
                    addresses[normalize_text(name)] = addr
    except FileNotFoundError:
        print(f"[警告] {path} が見つからないため会場住所の補完はスキップします", file=sys.stderr)
    return addresses


def resolve_venue_address(venue: str, venue_addresses: dict, venue_aliases: dict) -> str:
    """会場名から住所を引く。表記ゆれ辞書で正式名称に変換してから探す。"""
    if not venue:
        return ""
    norm = normalize_text(venue)
    # 1. 会場マスターと直接一致
    if norm in venue_addresses:
        return venue_addresses[norm]
    # 2. 表記ゆれ辞書で正式名称に変換してから再度探す
    canonical = venue_aliases.get(norm)
    if canonical:
        return venue_addresses.get(normalize_text(canonical), "")
    return ""


def collect_upcoming_events(today: date = None):
    """一覧ページを巡回し、本日以降の日付のイベントについて詳細情報を集める。"""
    if today is None:
        today = date.today()

    resolver = TeamNameResolver(clubs_path="data/clubs.csv", aliases_path="data/team_aliases.csv")
    venue_addresses = load_venue_addresses("data/venues.csv")
    venue_aliases = load_venue_aliases("data/venue_aliases.csv")

    all_items = []
    for page in range(1, MAX_LIST_PAGES + 1):
        url = LIST_URL if page == 1 else LIST_PAGE_URL.format(page=page)
        print(f"[list] page {page}: {url}", file=sys.stderr)
        html = fetch(url)
        items = parse_list_page(html)
        if not items:
            break
        all_items.extend(items)

    # 今日以降のイベントだけに絞る（過去の結果は events_archive.csv 側の役割）
    upcoming = [item for item in all_items if item["date"] >= today]

    events = []
    for item in upcoming:
        print(f"[detail] {item['detail_url']}", file=sys.stderr)
        detail_html = fetch(item["detail_url"])
        info = parse_detail_page(detail_html)

        # 明スポの表記（例:「水泳（競泳）」）を団体マスターの正式名称に変換する。
        # 解決できなければ「体育会 ○○」の形のまま残し、後段のチェックで拾えるようにする。
        guess = f"体育会 {item['club']}部" if item["club"] else ""
        team = resolver.resolve(guess) or resolver.resolve(item["club"]) or guess

        venue = info.get("会場", "")
        venue_address = resolve_venue_address(venue, venue_addresses, venue_aliases)

        events.append(
            {
                "start_date_raw": item["date"].strftime("%Y/%m/%d"),
                "start_time": "",
                "end_date_raw": "",
                "team": team,
                "event_name": item["title"],
                "venue": venue,
                "venue_address": venue_address,
                "url": item["detail_url"],
                "source": "meisupo.net",
            }
        )
    return events


def save_csv(events, path):
    fieldnames = [
        "start_date_raw",
        "start_time",
        "end_date_raw",
        "team",
        "event_name",
        "venue",
        "venue_address",
        "url",
        "source",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(events)


if __name__ == "__main__":
    events = collect_upcoming_events()
    out_path = "data/meisupo_events.csv"
    save_csv(events, out_path)
    print(f"{len(events)} 件のイベントを {out_path} に保存しました", file=sys.stderr)
