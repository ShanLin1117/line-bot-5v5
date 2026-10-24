import random
from datetime import datetime

import pytest

from app.db import Database
from app.models import TZ, Week
from app.teams import format_teams, split_into_teams

WEEK = Week(game_date="2026-10-25", deadline=datetime(2026, 10, 23, 12, 30, tzinfo=TZ), capacity=20)


def names(n: int) -> list[str]:
    return [f"P{i:02d}" for i in range(n)]


@pytest.mark.parametrize(
    "players, sizes",
    [
        (20, [5, 5, 5, 5]),
        (19, [5, 5, 5, 4]),
        (18, [5, 5, 5, 3]),  # 前面先補滿 5 人，剩下的放最後一隊
        (16, [5, 5, 5, 1]),
        (15, [5, 5, 5]),  # 人數少時隊數跟著減少
        (7, [5, 2]),
        (2, [2]),
    ],
)
def test_split_fills_teams_in_order(players, sizes):
    teams = split_into_teams(names(players), random.Random(0))

    assert [len(t) for t in teams] == sizes


def test_split_keeps_everyone_exactly_once():
    teams = split_into_teams(names(19), random.Random(0))

    assert sorted(n for team in teams for n in team) == names(19)


def test_split_is_random_but_reproducible_with_a_seed():
    first = split_into_teams(names(20), random.Random(1))
    again = split_into_teams(names(20), random.Random(1))
    other = split_into_teams(names(20), random.Random(2))

    assert first == again
    assert first != other
    assert first != [names(20)[i : i + 5] for i in range(0, 20, 5)]  # 不是照名單順序切


def test_split_does_not_modify_the_input():
    original = names(10)
    split_into_teams(original, random.Random(0))

    assert original == names(10)


def test_format_teams():
    text = format_teams(WEEK, [["a", "b", "c"], ["d", "e", "f"]])

    assert text.split("\n") == [
        "🏀 10/25 分組結果（共 6 人）",
        "",
        "【A 隊】3 人",
        "",
        "1. a",
        "2. b",
        "3. c",
        "",
        "【B 隊】3 人",
        "",
        "1. d",
        "2. e",
        "3. f",
    ]


def test_format_teams_warns_when_a_team_is_too_small():
    text = format_teams(WEEK, [["a", "b", "c", "d", "e"], ["f"]])

    assert "⚠️ B 隊只有 1 人" in text


def test_format_teams_for_extra_session():
    extra = Week("2026-11-06", datetime(2026, 11, 6, 23, 59, tzinfo=TZ), 15, kind="extra")

    assert format_teams(extra, [["a"]]).startswith("🏀 11/6 加開場分組結果")


def test_database_round_trips_teams_and_replaces_them():
    db = Database(":memory:")
    assert db.get_teams("2026-10-25") is None

    db.save_teams("2026-10-25", [["a", "b"], ["c"]])
    assert db.get_teams("2026-10-25") == [["a", "b"], ["c"]]

    db.save_teams("2026-10-25", [["x"]])
    assert db.get_teams("2026-10-25") == [["x"]]
    assert db.get_teams("2026-11-01") is None
