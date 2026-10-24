import asyncio
from datetime import date, datetime

import pytest

from app.db import BOUND_GROUP_KEY, Database
from app.models import TZ
from app.scheduler import next_open, run_once, target_game_date


def dt(month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=TZ)


# 2026-10-25、2026-11-01、2026-11-08 都是週日
@pytest.mark.parametrize(
    "now, expected",
    [
        (dt(10, 25, 19, 59), None),  # 開放前一分鐘
        (dt(10, 25, 20, 0), date(2026, 11, 1)),  # 週日 20:00 開放
        (dt(10, 28, 9, 0), date(2026, 11, 1)),  # 報名期間
        (dt(10, 30, 12, 30), date(2026, 11, 1)),  # 截止當下仍算在內
        (dt(10, 30, 12, 31), None),  # 截止後
        (dt(10, 31, 10, 0), None),  # 週六
        (dt(11, 1, 20, 0), date(2026, 11, 8)),  # 下一週開放
    ],
)
def test_target_game_date(now, expected):
    assert target_game_date(now) == expected


@pytest.mark.parametrize(
    "now, expected_game, expected_open",
    [
        (dt(10, 24, 18, 0), date(2026, 11, 1), dt(10, 25, 20, 0)),  # 週六 → 明天晚上
        (dt(10, 25, 19, 59), date(2026, 11, 1), dt(10, 25, 20, 0)),  # 開放前一分鐘
        (dt(10, 25, 20, 0), date(2026, 11, 8), dt(11, 1, 20, 0)),  # 剛好開放，下一次是下週
        (dt(10, 28, 9, 0), date(2026, 11, 8), dt(11, 1, 20, 0)),
    ],
)
def test_next_open(now, expected_game, expected_open):
    assert next_open(now) == (expected_game, expected_open)


@pytest.fixture
def db():
    database = Database(":memory:")
    database.set_setting(BOUND_GROUP_KEY, "G1")
    return database


class FakePush:
    def __init__(self):
        self.calls = []

    async def __call__(self, group_id, card):
        self.calls.append((group_id, card))


def tick(db, now, push) -> bool:
    return asyncio.run(run_once(db, now, push))


def test_pushes_card_and_opens_week_on_sunday_evening(db):
    push = FakePush()

    assert tick(db, dt(10, 25, 20, 0), push) is True

    assert len(push.calls) == 1
    group_id, card = push.calls[0]
    assert group_id == "G1"
    assert "11/1（日）籃球報名" in card.alt_text
    week = db.get_week("2026-11-01")
    assert week.deadline == dt(10, 30, 12, 30)


def test_pushes_only_once_per_week(db):
    push = FakePush()

    assert tick(db, dt(10, 25, 20, 0), push) is True
    assert tick(db, dt(10, 25, 20, 1), push) is False
    assert tick(db, dt(10, 27, 9, 0), push) is False

    assert len(push.calls) == 1


def test_catches_up_if_server_was_down_at_20_00(db):
    push = FakePush()

    assert tick(db, dt(10, 26, 8, 0), push) is True  # 週一早上才開機


def test_does_nothing_outside_registration_window(db):
    push = FakePush()

    assert tick(db, dt(10, 31, 10, 0), push) is False
    assert push.calls == []


def test_does_nothing_when_group_not_bound():
    push = FakePush()

    assert tick(Database(":memory:"), dt(10, 25, 20, 0), push) is False
    assert push.calls == []


def test_reuses_week_opened_manually(db):
    from app.scheduler import default_deadline

    db.create_week("2026-11-01", default_deadline(date(2026, 11, 1)))
    push = FakePush()

    assert tick(db, dt(10, 25, 20, 0), push) is True
    assert len(push.calls) == 1


def test_failed_push_is_retried_next_tick(db):
    class Failing:
        async def __call__(self, group_id, card):
            raise RuntimeError("LINE API down")

    with pytest.raises(RuntimeError):
        tick(db, dt(10, 25, 20, 0), Failing())

    push = FakePush()
    assert tick(db, dt(10, 25, 20, 1), push) is True  # 沒推成功就不會被標記為已推播
