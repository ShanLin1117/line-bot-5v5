"""每週自動開場次並推播報名卡。

Java 對照：相當於 @Scheduled。這裡只有一個固定排程，所以用 asyncio 的背景迴圈就夠了，
不額外引入排程套件。每分鐘檢查一次，並以資料庫記錄「這場次推播過沒有」，
所以伺服器重啟或晚一點才開機，也不會漏發或重發。
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta

from app.card import Card, build_card
from app.db import BOUND_GROUP_KEY, Database
from app.models import TZ

logger = logging.getLogger("line-bot-5v5")

PushFn = Callable[[str, Card], Awaitable[None]]


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


async def run_once(db: Database, now: datetime, push: PushFn) -> bool:
    """檢查是否該開場次並推播報名卡；有推播回傳 True。"""
    group_id = db.get_setting(BOUND_GROUP_KEY)
    if group_id is None:
        return False
    game_date = target_game_date(now)
    if game_date is None:
        return False
    pushed_key = f"card_pushed_{game_date.isoformat()}"
    if db.get_setting(pushed_key) is not None:
        return False

    # 已經手動 /開週 過就沿用，不會重複建立
    db.create_week(game_date.isoformat(), default_deadline(game_date))
    week = db.get_week(game_date.isoformat())
    await push(group_id, build_card(week, db.get_card_info()))
    db.set_setting(pushed_key, now.isoformat())
    logger.info("pushed sign-up card for %s", game_date)
    return True


async def run_forever(db: Database, push: PushFn, interval_seconds: int = 60) -> None:
    while True:
        try:
            await run_once(db, datetime.now(TZ), push)
        except Exception:
            # 單次失敗不能讓排程停掉，留下完整錯誤，下一輪會重試
            logger.exception("scheduler tick failed")
        await asyncio.sleep(interval_seconds)
