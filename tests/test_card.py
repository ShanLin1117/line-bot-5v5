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
