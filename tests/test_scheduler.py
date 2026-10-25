from datetime import date, datetime

import pytest

from app.db import BOUND_GROUP_KEY, Database
from app.models import TZ
from app.scheduler import default_deadline, next_open, open_due_week, target_game_date


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


def test_opens_the_week_on_sunday_evening_with_default_deadline(db):
    assert open_due_week(db, dt(10, 25, 20, 0)) is True

    week = db.get_week("2026-11-01")
    assert week.kind == "regular" and week.capacity == 20
    assert week.deadline == dt(10, 30, 12, 30)


def test_opens_only_once_and_keeps_registrations(db):
    assert open_due_week(db, dt(10, 25, 20, 0)) is True
    member = db.upsert_member("U1", "Bob")
    db.add_registration("2026-11-01", member.id, None, dt(10, 25, 20, 5))

    assert open_due_week(db, dt(10, 25, 20, 1)) is False
    assert open_due_week(db, dt(10, 27, 9, 0)) is False

    assert len(db.entries("2026-11-01")) == 1


def test_catches_up_if_server_was_down_at_20_00(db):
    assert open_due_week(db, dt(10, 26, 8, 0)) is True  # 週一早上才開機


def test_does_nothing_outside_registration_window(db):
    assert open_due_week(db, dt(10, 31, 10, 0)) is False
    assert db.get_week("2026-11-01") is None


def test_does_nothing_when_group_not_bound():
    unbound = Database(":memory:")

    assert open_due_week(unbound, dt(10, 25, 20, 0)) is False
    assert unbound.current_week() is None


def test_keeps_a_week_opened_manually_untouched(db):
    manual_deadline = dt(10, 29, 18, 0)
    db.create_week("2026-11-01", manual_deadline)

    assert open_due_week(db, dt(10, 25, 20, 0)) is False
    assert db.get_week("2026-11-01").deadline == manual_deadline


def test_default_deadline_is_friday_noon_thirty():
    assert default_deadline(date(2026, 11, 1)) == dt(10, 30, 12, 30)
