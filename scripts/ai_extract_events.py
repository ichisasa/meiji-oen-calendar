#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
道①（コードでHTML構造を直接指定する方式）では対応が難しい、
ニュース記事形式のサイトなどから、AI（Gemini API 無料枠）にページ内容を読ませて
明治大学の試合情報を抜き出すスクリプト。

- data/ai_source_urls.csv に読ませたいページのURL一覧を登録しておく
- 各ページのテキストをAIに渡し「明治大学の試合情報だけをJSONで返して」と指示する
- 抜き出した結果を data/ai_scraped_events.csv に保存する

必要な環境変数:
  GEMINI_API_KEY … Google AI Studio (https://aistudio.google.com/) で無料発行できるAPIキー

このスクリプトは実験的な位置づけ。抽出精度はページの作りやAIの出来に左右されるため、
他のスクレイパーと同様、必ずPull Requestでの人的レビューを経てからマージすること。
"""

import csv
import io
import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

HEADERS = {
    "User-Agent": "meiji-oen-calendar-bot/1.0 (+https://github.com/ichisasa/meiji-oen-calendar)"
}
REQUEST_INTERVAL_SEC = 4  # Geminiの無料枠(RPM制限)にも配慮した間隔

MAX_PAGE_CHARS = 12000  # ページ本文をAIに渡す際の上限（トークン節約）

PROMPT_TEMPLATE = """\
あなたは大学スポーツの試合日程を抽出するアシスタントです。
以下は、あるスポーツ連盟・団体の公式サイトのページ本文です。
この中から「明治大学」が関わる試合・大会の情報だけを抜き出してください。

重要な条件:
- 本日（{today}）以降に開催される、またはまだ結果が出ていない試合・大会だけを対象にしてください。
- 既に終了した過去のシーズン（例:2025年度の結果一覧など）は対象外です。ページに「結果」や
  スコアが明記されている、明らかに終わった試合は抜き出さないでください。
- 年の表記が無く判断できない場合のみ、{default_year}年と仮定してください。

出力は必ず次の形式のJSON配列のみとしてください。前置きや説明文、Markdownのコードフェンスは一切不要です。
情報が見つからない場合は空配列 [] だけを返してください。

[
  {{
    "date": "YYYY-MM-DD形式の日付。年が不明な場合は{default_year}年と仮定する",
    "time": "HH:MM形式の開始時刻。分からなければ空文字",
    "event_name": "大会名・試合名",
    "opponent": "対戦相手（分かれば。個人戦や対戦相手なしの大会は空文字）",
    "venue": "会場名（分かれば。不明なら空文字）",
    "confidence": "high または low（情報の確実さ）"
  }}
]

--- ページ本文 ---
{page_text}
--- ここまで ---
"""


def fetch_page_text(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    is_pdf = url.lower().endswith(".pdf") or "application/pdf" in resp.headers.get("Content-Type", "")
    if is_pdf:
        text = extract_pdf_text(resp.content)
    else:
        # 古いサイトはShift-JIS等、UTF-8以外の文字コードのことがある。
        # resp.textはHTTPヘッダのcharsetを鵜呑みにして文字化けすることがあるため、
        # 実際のバイト列から文字コードを推定し直す。
        detected_encoding = resp.apparent_encoding
        if detected_encoding:
            resp.encoding = detected_encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)

    return text[:MAX_PAGE_CHARS]


def extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages_text = []
    for page in reader.pages:
        pages_text.append(page.extract_text() or "")
    return "\n".join(pages_text)


def call_gemini(page_text: str, default_year: int, today: str) -> list:
    if not GEMINI_API_KEY:
        print("[警告] GEMINI_API_KEY が設定されていません。スキップします。", file=sys.stderr)
        return []

    prompt = PROMPT_TEMPLATE.format(page_text=page_text, default_year=default_year, today=today)
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}

    resp = requests.post(GEMINI_URL, headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    try:
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        print(f"[警告] Geminiの応答形式が想定と異なります: {data}", file=sys.stderr)
        return []

    return parse_json_response(raw_text)


def parse_json_response(raw_text: str) -> list:
    """AIの応答からJSON部分だけを取り出してパースする（```json ... ``` で囲まれていても対応）。"""
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError as e:
        print(f"[警告] JSON解析に失敗しました: {e}\n応答内容: {raw_text[:300]}", file=sys.stderr)
    return []


def load_sources(path="data/ai_source_urls.csv"):
    sources = []
    try:
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = (row.get("url") or "").strip()
                team = (row.get("team") or "").strip()
                if url:
                    sources.append({"url": url, "team": team})
    except FileNotFoundError:
        print(f"[警告] {path} が見つかりません", file=sys.stderr)
    return sources


def collect_events(default_year: int, today: str):
    sources = load_sources()
    events = []
    for src in sources:
        print(f"[fetch] {src['url']}", file=sys.stderr)
        try:
            text = fetch_page_text(src["url"])
        except requests.RequestException as e:
            print(f"[警告] 取得失敗: {src['url']} ({e})", file=sys.stderr)
            continue

        items = call_gemini(text, default_year, today)
        time.sleep(REQUEST_INTERVAL_SEC)

        for item in items:
            event_name = item.get("event_name", "")
            opponent = item.get("opponent", "")
            if opponent:
                event_name = f"{event_name} 対{opponent}"

            events.append(
                {
                    "start_date_raw": (item.get("date") or "").replace("-", "/"),
                    "start_time": item.get("time", ""),
                    "end_date_raw": "",
                    "team": src["team"] or "",
                    "event_name": event_name,
                    "venue": item.get("venue", ""),
                    "venue_address": "",
                    "url": src["url"],
                    "source": f"AI抽出:{item.get('confidence', 'low')}信頼度",
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
    import datetime
    today_date = datetime.date.today()
    default_year = today_date.year
    today_str = today_date.isoformat()

    events = collect_events(default_year, today_str)
    out_path = "data/ai_scraped_events.csv"
    save_csv(events, out_path)
    print(f"{len(events)} 件をAIで抽出し {out_path} に保存しました", file=sys.stderr)
