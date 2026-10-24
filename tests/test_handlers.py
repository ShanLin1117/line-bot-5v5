"""指令處理測試。用記憶體內的 SQLite，不需要任何外部服務。"""
from datetime import datetime

import pytest

from app.db import Database
from app.handlers import Context, check_group, handle_command
from app.models import TZ

GROUP = "G1"
NOW = datetime(2026, 10, 18, 20, 0, tzinfo=TZ)  # 週日 20:00 開放報名


@pytest.fixture
def db():
    return Database(":memory:")


def say(db, user: str, text: str, now: datetime = NOW) -> str | None:
    """模擬某位使用者（user 同時當作 LINE ID 與顯示名稱）在群組說話。"""
    return handle_command(Context(db, GROUP, f"U-{user}", user, now), text)


@pytest.fixture
def ready(db):
    """已初始化、已開場次的資料庫：Admin 是管理員，場次是 10/25。"""
    say(db, "Admin", "/初始化")
    say(db, "Admin", "/開週 10/25")
    return db


def at(minutes: int) -> datetime:
    return datetime(2026, 10, 18, 20, minutes, tzinfo=TZ)


# --- 群組綁定 ---


def test_check_group_before_binding_only_init_is_allowed():
    assert check_group(None, "G1", "/初始化") == "allow"
    assert check_group(None, "G1", "/報名") == "ignore"
    assert check_group(None, "G1", "大家好") == "ignore"


def test_check_group_after_binding():
    assert check_group("G1", "G1", "/報名") == "allow"
    assert check_group("G1", "G1", "大家好") == "ignore"
    assert check_group("G1", "G2", "/報名") == "leave"
    assert check_group("G1", "G2", "大家好") == "leave"


def test_init_binds_group_and_makes_sender_admin(db):
    reply = say(db, "Admin", "/初始化")

    assert "初始化完成" in reply
    assert db.get_setting("bound_group_id") == GROUP
    assert db.get_member_by_user_id("U-Admin").is_admin


def test_init_twice_reports_already_initialized(db):
    say(db, "Admin", "/初始化")
    assert "已經初始化" in say(db, "Other", "/初始化")
    assert not db.get_member_by_user_id("U-Other").is_admin


def test_unbind_requires_admin_and_clears_binding(ready):
    assert "只有管理員" in say(ready, "Bob", "/解除綁定")
    assert ready.get_setting("bound_group_id") == GROUP

    say(ready, "Admin", "/解除綁定")
    assert ready.get_setting("bound_group_id") is None


# --- 場次 ---


def test_open_week_requires_admin(db):
    say(db, "Admin", "/初始化")
    assert "只有管理員" in say(db, "Bob", "/開週 10/25")


def test_open_week_sets_default_deadline(db):
    say(db, "Admin", "/初始化")

    reply = say(db, "Admin", "/開週 10/25")

    assert "10/25" in reply and "10/23 12:30" in reply
    assert db.current_week().deadline == datetime(2026, 10, 23, 12, 30, tzinfo=TZ)


def test_open_week_rejects_bad_input_and_duplicates(ready):
    assert "用法" in say(ready, "Admin", "/開週")
    assert "格式不正確" in say(ready, "Admin", "/開週 abc")
    assert "已經過了" in say(ready, "Admin", "/開週 2026/10/01")
    assert "已經存在" in say(ready, "Admin", "/開週 10/25")


def test_register_without_week(db):
    say(db, "Admin", "/初始化")
    assert "沒有開放報名" in say(db, "Bob", "/報名")


# --- 報名、取消、遞補 ---


def test_register_and_duplicate(ready):
    assert "報名成功（零打）" in say(ready, "Bob", "/報名", at(1))
    assert "已經報名過了" in say(ready, "Bob", "/報名", at(2))


def test_season_member_is_labelled_season(ready):
    say(ready, "Bob", "/報名", at(1))  # 讓 Bob 成為已認識的成員
    say(ready, "Bob", "/取消", at(2))
    say(ready, "Admin", "/設季打 2")  # Admin 是 1 號，Bob 是 2 號

    assert "報名成功（季打）" in say(ready, "Bob", "/報名", at(3))


def test_cancel_promotes_waitlist_and_announces(ready):
    for i in range(22):
        say(ready, f"P{i}", "/報名", at(i))
    reply_full = say(ready, "P22", "/報名", at(30))
    assert "候補第 3 位" in reply_full  # 前 20 位正取，P20、P21 已在候補

    reply = say(ready, "P0", "/取消", at(31))

    assert "P0 已取消" in reply
    assert "候補遞補：P20" in reply
    assert "目前正取 20/20" in reply


def test_cancel_without_registration(ready):
    assert "目前沒有報名" in say(ready, "Bob", "/取消")


def test_guest_registration_and_cancel_are_independent(ready):
    say(ready, "Bob", "/報名", at(1))

    assert "阿豪 報名成功（零打）" in say(ready, "Bob", "/帶人 阿豪", at(2))
    assert "已經報名過了" in say(ready, "Bob", "/帶人 阿豪", at(3))

    assert "阿豪 已取消" in say(ready, "Bob", "/取消帶人 阿豪", at(4))
    assert "Bob 目前沒有" not in say(ready, "Bob", "/名單", at(5))  # Bob 本人還在名單上
    assert "1.Bob" in say(ready, "Bob", "/名單", at(5))


def test_guest_requires_name(ready):
    assert "用法" in say(ready, "Bob", "/帶人")


def test_roster_shows_sections(ready):
    say(ready, "Bob", "/報名", at(1))
    say(ready, "Admin", "/設季打 2")
    say(ready, "Cat", "/報名", at(2))
    say(ready, "Bob", "/帶人 阿豪", at(3))

    text = say(ready, "Cat", "/名單", at(4))

    assert "10/25 🏀正取名單3位" in text
    assert "📍季打1位" in text and "1.Bob" in text
    assert "📍零打2位" in text and "3.阿豪（Bob 帶）" in text


# --- 成員與權限 ---


def test_members_list_and_season_management(ready):
    say(ready, "Bob", "/報名", at(1))
    say(ready, "Cat", "/報名", at(2))

    assert "只有管理員" in say(ready, "Bob", "/設季打 3")
    reply = say(ready, "Admin", "/設季打 2 3 99")
    assert "已設為季打：Bob、Cat" in reply
    assert "找不到編號：99" in reply
    assert "目前季打共 2 人" in reply
    assert "2.Bob［季打］" in say(ready, "Admin", "/成員")

    assert "已取消季打：Cat" in say(ready, "Admin", "/取消季打 3")
    assert "已清除" in say(ready, "Admin", "/重設季打")
    assert "［季打］" not in say(ready, "Admin", "/成員")


def test_set_season_requires_numbers(ready):
    assert "請提供成員編號" in say(ready, "Admin", "/設季打")
    assert "請提供成員編號" in say(ready, "Admin", "/設季打 abc")


def test_add_admin(ready):
    say(ready, "Bob", "/報名", at(1))
    assert "只有管理員" in say(ready, "Bob", "/開週 11/01")

    assert "Bob 已成為管理員" in say(ready, "Admin", "/管理員 加 2")

    assert "已開放 11/1" in say(ready, "Bob", "/開週 11/01")


def test_unknown_text_is_ignored(ready):
    assert say(ready, "Bob", "/不存在的指令") is None
    assert say(ready, "Bob", "大家好") is None
    assert say(ready, "Bob", "") is None


def test_help(ready):
    assert "指令說明" in say(ready, "Bob", "/說明")
