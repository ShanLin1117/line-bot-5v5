"""每週自動開場次。

Java 對照：相當於 @Scheduled。這裡只有一個固定排程，所以用 asyncio 的背景迴圈就夠了，
不額外引入排程套件。每分鐘檢查一次；場次已經存在就什麼都不做，所以重複檢查、
伺服器重啟或晚一點才開機（會補開）都不會出問題。

排程「只開場次，不發訊息」：群組有 160 人，主動推播會按人數計入每月額度，
免費額度撐不住，所以報名卡改由管理員傳 /報名卡（回覆，免費）發出。
"""
import asyncio
import logging
from datetime import date, datetime, time, timedelta

from app.db import BOUND_GROUP_KEY, Database
from app.models import TZ

logger = logging.getLogger("line-bot-5v5")


def default_deadline(game_date: date) -> datetime:
    """報名截止：比賽日往前 2 天的 12:30（週日場次 → 週五中午）。"""
    return datetime.combine(game_date - timedelta(days=2), time(12, 30), tzinfo=TZ)


def open_time(game_date: date) -> datetime:
    """開放報名：比賽日往前 7 天的 20:00（前一個週日晚上）。"""
    return datetime.combine(game_date - timedelta(days=7), time(20, 0), tzinfo=TZ)


def target_game_date(now: datetime) -> date | None:
    """現在處於哪一場的報名期間（開放 ≤ 現在 ≤ 截止）；不在任何報名期間則回傳 None。"""
    # weekday()：週一 = 0 … 週日 = 6，算出「今天或之後最近的週日」
    first_sunday = now.date() + timedelta(days=(6 - now.weekday()) % 7)
    for game_date in (first_sunday, first_sunday + timedelta(days=7)):
        if open_time(game_date) <= now <= default_deadline(game_date):
            return game_date
    return None


def next_open(now: datetime) -> tuple[date, datetime]:
    """下一次自動開放的（場次日期, 開放時間），開放時間一定晚於現在。"""
    first_sunday = now.date() + timedelta(days=(6 - now.weekday()) % 7)
    for weeks in range(3):
        game_date = first_sunday + timedelta(days=7 * weeks)
        if open_time(game_date) > now:
            return game_date, open_time(game_date)
    raise AssertionError("unreachable: 3 weeks always contain a future opening")


def open_due_week(db: Database, now: datetime) -> bool:
    """該開場次就開（建立例行場）；這次有新建立場次回傳 True。"""
    if db.get_setting(BOUND_GROUP_KEY) is None:
        return False  # 還沒有綁定群組，開了也沒人用
    game_date = target_game_date(now)
    if game_date is None or db.get_week(game_date.isoformat()) is not None:
        return False  # 不在報名期間，或場次已經存在（排程開過，或管理員手動 /開週 過）

    created = db.create_week(game_date.isoformat(), default_deadline(game_date))
    if created:
        logger.info("opened week %s", game_date)
    return created


async def run_forever(db: Database, interval_seconds: int = 60) -> None:
    while True:
        try:
            open_due_week(db, datetime.now(TZ))
        except Exception:
            # 單次失敗不能讓排程停掉，留下完整錯誤，下一輪會重試
            logger.exception("scheduler tick failed")
        await asyncio.sleep(interval_seconds)
