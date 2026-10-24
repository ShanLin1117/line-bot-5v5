"""名單計算（本專案最核心的商業規則，規則說明見 docs/rules.md）。

刻意寫成純函式：輸入報名紀錄，輸出正取與候補，不碰資料庫與 LINE，
所以可以用單元測試把每條規則驗證清楚。
"""
from dataclasses import dataclass, replace
from datetime import datetime

from app.models import TZ, Entry, Week


@dataclass(frozen=True)
class Roster:
    confirmed: list[Entry]  # 正取
    waitlist: list[Entry]  # 候補，依遞補順序排列


def compute_roster(entries: list[Entry], deadline: datetime, capacity: int) -> Roster:
    # 先依報名時間排序；時間相同則依編號，確保結果穩定
    ordered = sorted(entries, key=lambda e: (e.registered_at, e.id))
    in_window = [e for e in ordered if e.registered_at <= deadline]
    late = [e for e in ordered if e.registered_at > deadline]

    seasons = [e for e in in_window if e.is_season]
    casuals = [e for e in in_window if not e.is_season]

    # 季打保障名額（正常不會超過 capacity，超過的部分排到候補最前面）
    confirmed = seasons[:capacity]

    # 其餘依序排隊：季打超額者 → 截止前零打 → 截止後報名者
    queue = seasons[capacity:] + casuals + late
    open_slots = capacity - len(confirmed)
    confirmed = confirmed + queue[:open_slots]
    waitlist = queue[open_slots:]
    return Roster(confirmed=confirmed, waitlist=waitlist)


def roster_for(entries: list[Entry], week: Week) -> Roster:
    if week.is_extra:
        # 加開場：不分季打零打、也沒有截止的概念，一律依報名時間先搶先贏。
        # 做法是把所有人都當成零打，且截止時間設在遙遠的未來
        everyone = [replace(e, is_season=False) for e in entries]
        return compute_roster(everyone, datetime(9999, 1, 1, tzinfo=TZ), week.capacity)
    return compute_roster(entries, week.deadline, week.capacity)


def _fmt_time(dt: datetime) -> str:
    return f"{dt.month}/{dt.day} {dt:%H:%M}"


def format_roster(week: Week, roster: Roster, now: datetime) -> str:
    """輸出成群組裡慣用的名單格式。"""
    game = datetime.fromisoformat(week.game_date)
    title = "加開場" if week.is_extra else ""
    lines = [f"{game.month}/{game.day} 🏀{title}正取名單{len(roster.confirmed)}位"]
    if week.note:
        lines.append(week.note)

    if not roster.confirmed:
        lines += ["", "（目前還沒有人報名）"]

    # 加開場不分季打零打，所有正取放在同一區；例行場依身分分兩區，編號連續
    if week.is_extra:
        sections = [("正取", roster.confirmed)]
    else:
        sections = [
            ("季打", [e for e in roster.confirmed if e.is_season]),
            ("零打", [e for e in roster.confirmed if not e.is_season]),
        ]
    number = 0
    for name, members in sections:
        if not members:
            continue
        lines += ["", f"📍{name}{len(members)}位"]
        for e in members:
            number += 1
            lines.append(f"{number}.{e.label}")

    if roster.waitlist:
        lines += ["", f"📍候補{len(roster.waitlist)}位"]
        lines += [e.label for e in roster.waitlist]

    if week.is_extra:
        footer = f"名額 {len(roster.confirmed)}/{week.capacity}｜加開場，依報名順序（先搶先贏）"
    else:
        state = "已截止" if now > week.deadline else "未截止"
        footer = (
            f"名額 {len(roster.confirmed)}/{week.capacity}"
            f"｜報名截止 {_fmt_time(week.deadline)}（{state}）"
        )
    lines += ["", footer]
    return "\n".join(lines)
