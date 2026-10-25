"""指令處理測試。用記憶體內的 SQLite，不需要任何外部服務。"""
import random
from datetime import datetime

import pytest

from app.card import Card
from app.db import Database
from app.handlers import (
    Context,
    check_group,
    check_group_postback,
    handle_command,
    handle_postback,
)
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
    assert "📍零打2位" in text and "3.阿豪" in text and "帶" not in text


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


# --- 報名卡按鈕 ---


def press(db, user: str, action: str, week: str = "2026-10-25", now: datetime = NOW):
    """模擬某位使用者按下報名卡上的按鈕。"""
    return handle_postback(Context(db, GROUP, f"U-{user}", user, now), f"a={action}&w={week}")


def test_check_group_postback():
    assert check_group_postback(None, "G1") == "ignore"
    assert check_group_postback("G1", "G1") == "allow"
    assert check_group_postback("G1", "G2") == "leave"


def test_buttons_register_cancel_and_roster(ready):
    assert "Bob 報名成功（零打）" in press(ready, "Bob", "register", now=at(1))
    assert "已經報名過了" in press(ready, "Bob", "register", now=at(2))
    assert "1.Bob" in press(ready, "Bob", "roster", now=at(3))

    assert "Bob 已取消" in press(ready, "Bob", "cancel", now=at(4))
    assert "目前沒有報名" in press(ready, "Bob", "cancel", now=at(5))


def test_guest_button_names_friends_automatically(ready):
    first = press(ready, "Bob", "guest", now=at(1))
    second = press(ready, "Bob", "guest", now=at(2))

    assert "Bob友1 報名成功（零打）" in first
    assert "Bob友2 報名成功（零打）" in second
    assert "3.Bob友2" not in second  # 回覆只有一行狀態，不是整份名單

    say(ready, "Bob", "/取消帶人 Bob友1", at(3))
    assert "Bob友1 報名成功" in press(ready, "Bob", "guest", now=at(4))  # 空出的編號會被重用


def test_old_card_cannot_register_for_a_new_week(ready):
    say(ready, "Admin", "/開週 11/01")

    reply = press(ready, "Bob", "register", week="2026-10-25", now=at(1))

    assert "已經過期" in reply
    assert "沒有報名" in say(ready, "Bob", "/取消", at(2))


def test_unknown_button_is_ignored(ready):
    assert press(ready, "Bob", "hack") is None


def test_card_command_returns_card_for_admin_only(ready):
    assert "只有管理員" in say(ready, "Bob", "/報名卡")

    card = say(ready, "Admin", "/報名卡")

    assert isinstance(card, Card)
    assert "10/25" in card.alt_text


def test_card_command_without_week(db):
    say(db, "Admin", "/初始化")
    assert "沒有開放報名" in say(db, "Admin", "/報名卡")


def test_schedule_status_requires_admin(ready):
    assert "只有管理員" in say(ready, "Bob", "/排程狀態")


def test_schedule_status_before_push(ready):
    text = say(ready, "Admin", "/排程狀態")  # NOW = 10/18（日）20:00，剛進入 10/25 場次的報名期間

    assert "現在時間：10/18（日）20:00" in text
    assert "10/25，報名卡尚未推播" in text
    assert "下次自動推播：10/25（日）20:00（場次 11/1）" in text


def test_schedule_status_after_push(ready):
    ready.set_setting("card_pushed_2026-10-25", at(5).isoformat())

    text = say(ready, "Admin", "/排程狀態")

    assert "報名卡已於 10/18（日）20:05 推播" in text


# --- 加開場 ---


def open_extra(db, text: str = "/加開場 11/06 15 晚上7點 中正運動中心"):
    return say(db, "Admin", text)


def test_open_extra_requires_admin(ready):
    assert "只有管理員" in say(ready, "Bob", "/加開場 11/06")


def test_open_extra_replies_with_combined_card(ready):
    card = open_extra(ready)

    assert isinstance(card, Card)
    text = str(card.contents)
    assert "11/6（五）加開場報名" in text and "晚上7點 中正運動中心" in text
    assert "名額 15 人" in text
    assert "10/25（日）籃球報名" in text  # 例行場仍在卡片上方
    assert card.alt_text == "🏀 10/25（日）籃球報名（另有 1 個場次）"


def test_open_extra_defaults_to_20_without_note(ready):
    text = str(open_extra(ready, "/加開場 11/06").contents)

    assert "名額 20 人" in text


def test_open_extra_validation(ready):
    assert "用法" in say(ready, "Admin", "/加開場")
    assert "日期格式不正確" in say(ready, "Admin", "/加開場 abc")
    assert "已經過了" in say(ready, "Admin", "/加開場 2026/10/01")
    assert "人數請輸入" in say(ready, "Admin", "/加開場 11/06 0")
    assert "人數請輸入" in say(ready, "Admin", "/加開場 11/06 99")
    assert "已經有場次" in say(ready, "Admin", "/加開場 10/25")  # 與例行場同一天

    open_extra(ready)
    assert "已經有場次" in open_extra(ready)


def test_extra_does_not_replace_the_current_regular_week(ready):
    open_extra(ready)  # 11/06 比例行場 10/25 晚，但它不是例行場

    assert ready.current_week().game_date == "2026-10-25"
    assert "報名成功（零打）" in say(ready, "Bob", "/報名", at(1))
    assert say(ready, "Bob", "/名單", at(2)).startswith("10/25 🏀正取名單")


def test_extra_is_first_come_regardless_of_season(ready):
    open_extra(ready, "/加開場 11/06 1")
    say(ready, "Bob", "/報名", at(1))  # 先讓 Bob 成為成員，編號 2
    say(ready, "Admin", "/設季打 2")

    first = press(ready, "Cat", "register", week="2026-11-06", now=at(2))
    second = press(ready, "Bob", "register", week="2026-11-06", now=at(3))

    assert first == "✅ Cat 報名成功｜正取 1/1"  # 加開場不標示季打、零打
    assert "排候補第 1 位" in second  # Bob 是季打，但加開場不給保障名額


def test_extra_cancel_promotes_in_order(ready):
    open_extra(ready, "/加開場 11/06 1")
    press(ready, "Cat", "register", week="2026-11-06", now=at(1))
    press(ready, "Dan", "register", week="2026-11-06", now=at(2))

    reply = press(ready, "Cat", "cancel", week="2026-11-06", now=at(3))

    assert "候補遞補：Dan" in reply


def test_commands_accept_a_date_to_target_the_extra(ready):
    open_extra(ready)

    assert "Bob 報名成功｜正取 1/15" in say(ready, "Bob", "/報名 11/06", at(1))
    assert "加開場正取名單1位" in say(ready, "Bob", "/名單 11/06", at(2))
    assert "阿豪 報名成功" in say(ready, "Bob", "/帶人 阿豪 11/06", at(3))
    assert "阿豪 已取消" in say(ready, "Bob", "/取消帶人 阿豪 11/06", at(4))
    assert "Bob 已取消" in say(ready, "Bob", "/取消 11/06", at(5))
    # 沒帶日期的指令仍然是例行場，這時例行場沒有人報名
    assert "（目前還沒有人報名）" in say(ready, "Bob", "/名單", at(6))


def test_unknown_date_is_reported(ready):
    assert "找不到 12/25 的場次" in say(ready, "Bob", "/名單 12/25")
    assert "找不到 12/25 的場次" in say(ready, "Bob", "/報名 12/25")


def test_extra_roster_format(ready):
    open_extra(ready)
    say(ready, "Bob", "/報名 11/06", at(1))

    text = say(ready, "Bob", "/名單 11/06", at(2))

    assert text.split("\n")[0] == "11/6 🏀加開場正取名單1位"
    assert "晚上7點 中正運動中心" in text
    assert "📍正取1位" in text and "1.Bob" in text
    assert "季打" not in text and "零打" not in text
    assert text.endswith("名額 1/15｜加開場，依報名順序（先搶先贏）")


def test_extra_guest_button_hint_includes_date(ready):
    open_extra(ready)

    reply = press(ready, "Bob", "guest", week="2026-11-06", now=at(1))

    assert "Bob友1 報名成功｜正取 1/15" in reply
    assert "/取消帶人 Bob友1 11/6" in reply


def test_card_command_lists_regular_and_all_open_extras(ready):
    open_extra(ready)
    open_extra(ready, "/加開場 11/13")

    card = say(ready, "Admin", "/報名卡")

    text = str(card.contents)
    assert text.index("10/25（日）籃球報名") < text.index("11/6（五）加開場報名")
    assert text.index("11/6（五）加開場報名") < text.index("11/13（五）加開場報名")
    assert card.alt_text.endswith("（另有 2 個場次）")


def test_card_command_drops_expired_sessions(ready):
    open_extra(ready)
    open_extra(ready, "/加開場 11/13")
    after_first_extra = datetime(2026, 11, 7, 10, 0, tzinfo=TZ)  # 例行場與 11/6 都過了

    card = say(ready, "Admin", "/報名卡", now=after_first_extra)

    text = str(card.contents)
    assert "11/13（五）加開場報名" in text
    assert "11/6" not in text and "10/25" not in text


def test_old_regular_card_is_expired_but_extra_card_still_works(ready):
    open_extra(ready)
    say(ready, "Admin", "/開週 11/01")  # 例行場換成 11/01

    assert "已經過期" in press(ready, "Bob", "register", week="2026-10-25", now=at(1))
    assert "報名成功" in press(ready, "Bob", "register", week="2026-11-06", now=at(2))


def test_extra_card_expires_after_the_game_day(ready):
    open_extra(ready)
    later = datetime(2026, 11, 7, 9, 0, tzinfo=TZ)

    assert "已經過期" in press(ready, "Bob", "register", week="2026-11-06", now=later)


def test_cancel_extra_requires_admin(ready):
    open_extra(ready)
    assert "只有管理員" in say(ready, "Bob", "/取消加開場 11/06")


def test_cancel_extra_removes_session_and_registrations(ready):
    open_extra(ready)
    say(ready, "Bob", "/報名 11/06", at(1))
    say(ready, "Cat", "/報名 11/06", at(2))

    reply = say(ready, "Admin", "/取消加開場 11/06")

    assert reply == "✅ 已取消 11/6 加開場（已清除 2 筆報名）"
    assert "找不到 11/06 的場次" in say(ready, "Bob", "/名單 11/06", at(3))
    assert "11/6" not in str(say(ready, "Admin", "/報名卡").contents)
    assert isinstance(say(ready, "Admin", "/加開場 11/06"), Card)  # 日期可以重新使用


def test_cancel_extra_without_registrations_and_validation(ready):
    open_extra(ready)

    assert say(ready, "Admin", "/取消加開場 11/06") == "✅ 已取消 11/6 加開場"
    assert "用法" in say(ready, "Admin", "/取消加開場")
    assert "找不到 11/20 的加開場" in say(ready, "Admin", "/取消加開場 11/20")


def test_cancel_extra_refuses_the_regular_week(ready):
    assert "找不到 10/25 的加開場" in say(ready, "Admin", "/取消加開場 10/25")
    assert ready.current_week().game_date == "2026-10-25"


# --- 分組 ---


def fill(db, n: int, suffix: str = ""):
    """讓 P00 ~ P(n-1) 依序報名；suffix 可以帶日期來報加開場。"""
    for i in range(n):
        say(db, f"P{i:02d}", f"/報名{suffix}", at(i))


def say_seeded(db, user: str, text: str, seed: int):
    ctx = Context(db, GROUP, f"U-{user}", user, NOW, rng=random.Random(seed))
    return handle_command(ctx, text)


def team_lines(text: str) -> list[str]:
    return [line for line in text.split("\n") if line.startswith("【")]


def test_teams_require_admin_but_result_is_open_to_everyone(ready):
    fill(ready, 4)

    assert "只有管理員" in say(ready, "Bob", "/分組")
    assert "只有管理員" in say(ready, "Bob", "/重新分組")
    assert "還沒有分組" in say(ready, "Bob", "/分組結果")


def test_teams_split_19_players_into_5_5_5_4(ready):
    fill(ready, 19)

    text = say(ready, "Admin", "/分組")

    assert team_lines(text) == ["【A 隊】5 人", "【B 隊】5 人", "【C 隊】5 人", "【D 隊】4 人"]
    assert text.startswith("🏀 10/25 分組結果（共 19 人）")
    for i in range(19):
        assert text.count(f"P{i:02d}") == 1  # 每個人只出現一次


def test_teams_use_only_confirmed_players_not_the_waitlist(ready):
    fill(ready, 22)  # 20 位正取、2 位候補

    text = say(ready, "Admin", "/分組")

    assert "共 20 人" in text
    assert "P20" not in text and "P21" not in text


def test_teams_cannot_be_redrawn_by_pressing_again(ready):
    fill(ready, 20)
    first = say(ready, "Admin", "/分組")

    again = say(ready, "Admin", "/分組")

    assert "已經分組過了" in again and "/重新分組" in again
    assert again.endswith(first)  # 結果完全相同
    assert say(ready, "Bob", "/分組結果") == first


def test_reteam_replaces_the_previous_result(ready):
    fill(ready, 20)
    first = say_seeded(ready, "Admin", "/分組", seed=1)

    redo = say_seeded(ready, "Admin", "/重新分組", seed=2)

    assert redo.startswith("🔁 已重新分組，原本的結果已作廢")
    assert redo.endswith(say(ready, "Bob", "/分組結果"))  # 之後查到的是新結果
    assert say(ready, "Bob", "/分組結果") != first


def test_reteam_without_previous_result_just_makes_teams(ready):
    fill(ready, 10)

    text = say(ready, "Admin", "/重新分組")

    assert not text.startswith("🔁") and "共 10 人" in text


def test_teams_need_at_least_two_players(ready):
    assert "正取人數不足" in say(ready, "Admin", "/分組")
    fill(ready, 1)
    assert "正取人數不足" in say(ready, "Admin", "/分組")


def test_teams_are_a_snapshot_and_ignore_later_cancellations(ready):
    fill(ready, 8)
    say(ready, "Admin", "/分組")

    say(ready, "P00", "/取消", at(30))

    assert "P00" in say(ready, "Bob", "/分組結果")


def test_teams_for_an_extra_session_use_the_date(ready):
    open_extra(ready, "/加開場 11/06 15")
    fill(ready, 15, suffix=" 11/06")

    text = say(ready, "Admin", "/分組 11/06")

    assert text.startswith("🏀 11/6 加開場分組結果（共 15 人）")
    assert team_lines(text) == ["【A 隊】5 人", "【B 隊】5 人", "【C 隊】5 人"]
    assert "還沒有分組" in say(ready, "Bob", "/分組結果")  # 例行場沒有被影響
    assert "加開場分組結果" in say(ready, "Bob", "/分組結果 11/06")


def test_teams_unknown_date(ready):
    assert "找不到 12/25 的場次" in say(ready, "Admin", "/分組 12/25")


def test_cancel_extra_also_removes_its_teams(ready):
    open_extra(ready, "/加開場 11/06 15")
    fill(ready, 6, suffix=" 11/06")
    say(ready, "Admin", "/分組 11/06")

    say(ready, "Admin", "/取消加開場 11/06")

    assert ready.get_teams("2026-11-06") is None


# --- 卡片資訊設定 ---


def test_info_settings_flow_into_card(ready):
    assert "只有管理員" in say(ready, "Bob", "/設定 地點 某球場")
    assert "已設定地點：威湧運動中心" in say(ready, "Admin", "/設定 地點 威湧運動中心")
    say(ready, "Admin", "/設定 時間 07:00-09:00")
    say(ready, "Admin", "/設定 費用 200")

    overview = say(ready, "Admin", "/設定")
    assert "地點：威湧運動中心" in overview and "備註：（未設定）" in overview

    card = say(ready, "Admin", "/報名卡")
    texts = str(card.contents)
    assert "威湧運動中心" in texts and "07:00-09:00" in texts and "NT$200" in texts


def test_info_settings_validation_and_clear(ready):
    assert "可設定的項目" in say(ready, "Admin", "/設定 不存在 xx")

    say(ready, "Admin", "/設定 備註 第15季 4/13次")
    assert ready.get_card_info()["note"] == "第15季 4/13次"

    assert "已清除備註" in say(ready, "Admin", "/設定 備註")
    assert "note" not in ready.get_card_info()
