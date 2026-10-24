from datetime import datetime

from app import line_client
from app.card import build_card
from app.models import TZ, Week

WEEK = Week(game_date="2026-11-01", deadline=datetime(2026, 10, 30, 12, 30, tzinfo=TZ), capacity=20)
INFO = {"venue": "威湧運動中心", "time": "07:00-09:00", "fee": "200", "note": "第15季 4/13次"}


def collect(node, key: str, found: list) -> list:
    """遞迴走訪 JSON，收集所有名為 key 的值。"""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                found.append(v)
            collect(v, key, found)
    elif isinstance(node, list):
        for item in node:
            collect(item, key, found)
    return found


def all_text(card) -> str:
    return "\n".join(collect(card.contents, "text", []))


def test_card_has_four_postback_buttons_bound_to_the_week():
    card = build_card(WEEK, INFO)

    actions = collect(card.contents, "action", [])
    assert [(a["label"], a["data"]) for a in actions] == [
        ("報名", "a=register&w=2026-11-01"),
        ("取消", "a=cancel&w=2026-11-01"),
        ("帶朋友 +1", "a=guest&w=2026-11-01"),
        ("查看名單", "a=roster&w=2026-11-01"),
    ]
    assert all(a["type"] == "postback" for a in actions)


def test_card_shows_title_info_and_rules():
    text = all_text(build_card(WEEK, INFO))

    assert "11/1（日）籃球報名" in text
    assert "威湧運動中心" in text and "07:00-09:00" in text
    assert "NT$200" in text and "第15季 4/13次" in text
    assert "報名截止 10/30（五）12:30" in text


def test_card_omits_unset_info():
    text = all_text(build_card(WEEK, {}))

    assert "📍" not in text and "NT$" not in text
    assert "籃球報名" in text


def test_card_is_accepted_by_line_sdk():
    # 使用真正的 SDK 解析一次，能提早發現 JSON 結構不合法（不會連線）
    message = line_client.build_flex_message(build_card(WEEK, INFO))

    assert message.alt_text == "🏀 11/1（日）籃球報名"


EXTRA_1 = Week("2026-11-06", datetime(2026, 11, 6, 23, 59, tzinfo=TZ), 15, kind="extra", note="晚上7點")
EXTRA_2 = Week("2026-11-13", datetime(2026, 11, 13, 23, 59, tzinfo=TZ), 20, kind="extra")


def test_combined_card_stacks_extras_below_the_regular_week():
    card = build_card(WEEK, INFO, [EXTRA_1, EXTRA_2])

    actions = collect(card.contents, "action", [])
    assert [a["data"] for a in actions] == [
        f"a={name}&w={game_date}"
        for game_date in ("2026-11-01", "2026-11-06", "2026-11-13")
        for name in ("register", "cancel", "guest", "roster")
    ]
    text = all_text(card)
    assert text.index("籃球報名") < text.index("11/6（五）加開場報名") < text.index("11/13（五）加開場報名")
    assert "晚上7點" in text and "名額 15 人" in text and "先搶先贏" in text
    assert card.alt_text == "🏀 11/1（日）籃球報名（另有 2 個場次）"


def test_extra_section_does_not_show_regular_info_or_deadline():
    text = all_text(build_card(None, INFO, [EXTRA_1]))

    assert "威湧運動中心" not in text and "NT$" not in text and "報名截止" not in text


def test_card_with_only_extras_uses_the_first_extra_as_title():
    card = build_card(None, INFO, [EXTRA_1, EXTRA_2])

    assert card.alt_text == "⚡ 11/6（五）加開場報名（另有 1 個場次）"
    assert line_client.build_flex_message(card).alt_text == card.alt_text
