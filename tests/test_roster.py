"""名單計算規則測試，每個測試對應 docs/rules.md 的一條規則。"""
from datetime import datetime, timedelta

from app.models import TZ, Entry, Week
from app.roster import compute_roster, format_roster, roster_for

T0 = datetime(2026, 10, 18, 20, 0, tzinfo=TZ)  # 週日 20:00 開放報名
DEADLINE = datetime(2026, 10, 23, 12, 30, tzinfo=TZ)  # 週五 12:30 截止
LATE = DEADLINE + timedelta(hours=1)


def entry(i: int, season: bool, at: datetime, label: str | None = None) -> Entry:
    return Entry(
        id=i,
        label=label or f"p{i}",
        is_season=season,
        registered_at=at,
        owner_id=i,
        is_guest=False,
    )


def ids(entries: list[Entry]) -> list[int]:
    return [e.id for e in entries]


def minutes(n: int) -> datetime:
    return T0 + timedelta(minutes=n)


def test_season_is_guaranteed_even_if_registered_after_casuals():
    # 2 位零打先報，19 位季打後報：季打全部正取，只剩 1 個名額給第一位零打
    entries = [entry(1, False, minutes(1)), entry(2, False, minutes(2))]
    entries += [entry(10 + i, True, minutes(10 + i)) for i in range(19)]

    roster = compute_roster(entries, DEADLINE, 20)

    assert len(roster.confirmed) == 20
    assert all(i in ids(roster.confirmed) for i in range(10, 29))
    assert 1 in ids(roster.confirmed)
    assert ids(roster.waitlist) == [2]


def test_casuals_fill_remaining_slots_in_order_like_real_case():
    # 實際案例：18 位季打、7 位零打 → 正取 18 季打 + 2 零打，候補 5 位
    entries = [entry(i, True, minutes(i)) for i in range(1, 19)]
    entries += [entry(100 + i, False, minutes(100 + i)) for i in range(7)]

    roster = compute_roster(entries, DEADLINE, 20)

    assert len(roster.confirmed) == 20
    assert ids(roster.confirmed)[-2:] == [100, 101]
    assert ids(roster.waitlist) == [102, 103, 104, 105, 106]


def test_late_registrations_go_to_waitlist_when_full():
    entries = [entry(i, True, minutes(i)) for i in range(1, 21)]
    entries.append(entry(99, True, LATE))  # 截止後才報名的季打

    roster = compute_roster(entries, DEADLINE, 20)

    assert 99 not in ids(roster.confirmed)
    assert ids(roster.waitlist) == [99]


def test_late_registration_takes_open_slot_when_not_full():
    entries = [entry(i, True, minutes(i)) for i in range(1, 11)]
    entries.append(entry(99, False, LATE))

    roster = compute_roster(entries, DEADLINE, 20)

    assert 99 in ids(roster.confirmed)
    assert roster.waitlist == []


def test_cancellation_promotes_first_waitlisted_in_order():
    entries = [entry(i, True, minutes(i)) for i in range(1, 19)]
    entries += [entry(100 + i, False, minutes(100 + i)) for i in range(4)]  # 2 正取、2 候補
    before = compute_roster(entries, DEADLINE, 20)
    assert ids(before.waitlist) == [102, 103]

    after = compute_roster([e for e in entries if e.id != 5], DEADLINE, 20)  # 一位季打取消

    assert 102 in ids(after.confirmed)
    assert ids(after.waitlist) == [103]


def test_promotion_prefers_window_waitlist_over_late_registrations():
    entries = [entry(i, True, minutes(i)) for i in range(1, 19)]
    entries += [entry(100, False, minutes(100)), entry(101, False, minutes(101))]
    entries.append(entry(102, False, minutes(102)))  # 截止前的候補
    entries.append(entry(200, True, LATE))  # 截止後的季打，排更後面

    after = compute_roster([e for e in entries if e.id != 1], DEADLINE, 20)

    assert 102 in ids(after.confirmed)
    assert ids(after.waitlist) == [200]


def test_re_registration_after_cancel_goes_to_the_back():
    # 取消後重報是新的一筆紀錄，時間較晚
    entries = [entry(i, False, minutes(i)) for i in range(1, 22)]  # 21 位零打
    assert ids(compute_roster(entries, DEADLINE, 20).waitlist) == [21]

    entries = [e for e in entries if e.id != 3] + [entry(30, False, minutes(60), "p3-again")]
    roster = compute_roster(entries, DEADLINE, 20)

    assert 21 in ids(roster.confirmed)
    assert ids(roster.waitlist) == [30]


def test_season_over_capacity_overflow_goes_first_in_waitlist():
    entries = [entry(i, True, minutes(i)) for i in range(1, 22)]

    roster = compute_roster(entries, DEADLINE, 20)

    assert len(roster.confirmed) == 20
    assert ids(roster.waitlist) == [21]


def test_format_roster_matches_group_style():
    week = Week(game_date="2026-10-25", deadline=DEADLINE, capacity=20)
    entries = [
        entry(1, True, minutes(1), "Gary"),
        entry(2, True, minutes(2), "Shan"),
        entry(3, False, minutes(3), "Brant"),
    ]
    entries += [entry(10 + i, False, minutes(10 + i), f"w{i}") for i in range(19)]
    roster = compute_roster(entries, DEADLINE, 20)

    text = format_roster(week, roster, now=minutes(500))

    lines = text.split("\n")
    assert lines[0] == "10/25 🏀正取名單20位"
    assert "📍季打2位" in lines
    assert "1.Gary" in lines and "2.Shan" in lines
    assert "📍零打18位" in lines
    assert "3.Brant" in lines
    assert "📍候補2位" in lines
    assert lines[-1].startswith("名額 20/20｜報名截止 10/23 12:30（未截止）")


def test_extra_week_ignores_season_and_deadline():
    extra = Week(game_date="2026-11-06", deadline=DEADLINE, capacity=2, kind="extra")
    entries = [
        entry(1, False, LATE + timedelta(days=1)),  # 全部都晚於「截止時間」
        entry(2, True, LATE + timedelta(days=2)),  # 季打也沒有保障
        entry(3, True, LATE + timedelta(days=3)),
    ]

    roster = roster_for(entries, extra)

    assert ids(roster.confirmed) == [1, 2]
    assert ids(roster.waitlist) == [3]


def test_regular_week_still_gives_season_priority():
    regular = Week(game_date="2026-11-01", deadline=DEADLINE, capacity=2)
    entries = [entry(1, False, minutes(1)), entry(2, True, minutes(2)), entry(3, True, minutes(3))]

    assert ids(roster_for(entries, regular).confirmed) == [2, 3]


def test_format_roster_empty():
    week = Week(game_date="2026-10-25", deadline=DEADLINE, capacity=20)
    text = format_roster(week, compute_roster([], DEADLINE, 20), now=LATE)
    assert "目前還沒有人報名" in text
    assert "已截止" in text
