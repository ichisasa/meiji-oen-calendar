
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
団体名の表記ゆれ（「水泳部（競泳）」⇔「水泳（競泳）部」、誤字「バトミントン」等）を
吸収し、団体マスター(clubs.csv)上の正式名称に変換するモジュール。

優先順位:
  1. data/team_aliases.csv に登録された既知の表記ゆれ（完全一致）
  2. clubs.csv の club_name とスペース無視で完全一致
  3. clubs.csv の club_name が team文字列に部分一致（複数候補なら最長一致を採用）
  4. どれにも当てはまらなければ None（＝人の確認が必要、という合図）

check_missing_clubs.py や build_tournament_master.py から import して使うことを想定。
"""

import csv


CATEGORY_PREFIXES = ["体育会", "公認団体", "実行委員会"]


def normalize(s: str) -> str:
    s = s.replace(" ", "").replace("　", "")
    for prefix in CATEGORY_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix):]
    return s


def load_clubs(path="data/clubs.csv"):
    clubs = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            clubs.append(
                {"category": row["category"].strip(), "club_name": row["club_name"].strip()}
            )
    return clubs


def load_aliases(path="data/team_aliases.csv"):
    """alias(正規化済みキー) -> canonical(clubs.csv上の正式名称) の辞書を返す。"""
    alias_map = {}
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            alias = row["alias"].strip()
            canonical = row["canonical"].strip()
            alias_map[normalize(alias)] = canonical
    return alias_map


class TeamNameResolver:
    def __init__(self, clubs_path="data/clubs.csv", aliases_path="data/team_aliases.csv"):
        self.clubs = load_clubs(clubs_path)
        self.club_names = [c["club_name"] for c in self.clubs]
        self.alias_map = load_aliases(aliases_path)

    def resolve(self, raw_team: str):
        """
        raw_team（イベントデータのteam列など）を正式団体名に変換する。
        解決できた場合は正式名称（str）、できなければ None を返す。
        """
        if not raw_team:
            return None
        norm = normalize(raw_team.strip())

        # 1. 既知の表記ゆれ辞書と完全一致
        if norm in self.alias_map:
            return self.alias_map[norm]

        # 2. clubs.csv の名称と完全一致（スペース無視）
        for name in self.club_names:
            if normalize(name) == norm:
                return name

        # 3. clubs.csv の名称が部分一致するもの（最長一致を優先）
        candidates = [name for name in self.club_names if normalize(name) in norm]
        if candidates:
            return max(candidates, key=len)

        # 4. 解決できず
        return None


if __name__ == "__main__":
    # 簡易セルフテスト
    resolver = TeamNameResolver()
    test_cases = [
        "体育会 水泳（競泳）部",
        "体育会 ラクロス（男子）部",
        "体育会 サッカー部",
        "体育会 バトミントン部",
        "体育会 スケート部 フィギュア部門",
        "第140回明大祭実行委員会",
        "存在しない謎の団体",
    ]
    for t in test_cases:
        result = resolver.resolve(t)
        status = "OK" if result else "未解決"
        print(f"[{status}] {t!r} -> {result!r}")
