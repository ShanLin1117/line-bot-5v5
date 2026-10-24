"""Webhook 整合測試。Java 對照：JUnit + MockMvc。

pytest 會自動找 test_*.py 內以 test_ 開頭的函式，不需要註解標記。
"""
import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta

# 必須在 import app 之前設定，因為 app.main 載入時就會讀取設定
os.environ["LINE_CHANNEL_SECRET"] = "test-secret"
os.environ["DB_PATH"] = ":memory:"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import line_client  # noqa: E402
from app.db import Database  # noqa: E402
from app.main import app  # noqa: E402
from app.models import TZ  # noqa: E402

client = TestClient(app)


def sign(body: str) -> str:
    """依 LINE 規則計算簽章：HMAC-SHA256(channel secret, body) 再 Base64。"""
    digest = hmac.new(b"test-secret", body.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def post(events: list[dict]):
    body = json.dumps({"destination": "U0", "events": events}, ensure_ascii=False)
    return client.post(
        "/callback", content=body.encode("utf-8"), headers={"X-Line-Signature": sign(body)}
    )


def message_event(group_id: str, user_id: str, text: str) -> dict:
    return {
        "type": "message",
        "mode": "active",
        "timestamp": 1,
        "webhookEventId": "01",
        "deliveryContext": {"isRedelivery": False},
        "source": {"type": "group", "groupId": group_id, "userId": user_id},
        "replyToken": "token-1",
        "message": {"type": "text", "id": "100", "quoteToken": "q", "text": text},
    }


def join_event(group_id: str) -> dict:
    return {
        "type": "join",
        "mode": "active",
        "timestamp": 1,
        "webhookEventId": "02",
        "deliveryContext": {"isRedelivery": False},
        "source": {"type": "group", "groupId": group_id},
        "replyToken": "token-2",
    }


def postback_event(group_id: str, user_id: str, data: str) -> dict:
    return {
        "type": "postback",
        "mode": "active",
        "timestamp": 1,
        "webhookEventId": "03",
        "deliveryContext": {"isRedelivery": False},
        "source": {"type": "group", "groupId": group_id, "userId": user_id},
        "replyToken": "token-3",
        "postback": {"data": data},
    }


@pytest.fixture
def line(monkeypatch):
    """換成記憶體資料庫，並把對 LINE 的呼叫換成假的，記錄呼叫內容。

    monkeypatch 相當於 Mockito 的 mock/when：測試結束後會自動還原。
    """
    monkeypatch.setattr("app.main.db", Database(":memory:"))
    calls = {"replies": [], "left": [], "cards": [], "pushes": [], "push_fails": False}

    async def fake_push_card(group_id, card):
        if calls["push_fails"]:
            raise RuntimeError("LINE API down")
        calls["pushes"].append((group_id, card))

    async def fake_reply(reply_token, text):
        calls["replies"].append((reply_token, text))

    async def fake_reply_card(reply_token, card):
        calls["cards"].append((reply_token, card))

    async def fake_leave(group_id):
        calls["left"].append(group_id)

    async def fake_name(group_id, user_id):
        return "Shan"

    monkeypatch.setattr(line_client, "reply_text", fake_reply)
    monkeypatch.setattr(line_client, "reply_card", fake_reply_card)
    monkeypatch.setattr(line_client, "push_card", fake_push_card)
    monkeypatch.setattr(line_client, "leave_group", fake_leave)
    monkeypatch.setattr(line_client, "get_display_name", fake_name)
    return calls


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_callback_rejects_invalid_signature():
    response = client.post(
        "/callback", content='{"events": []}', headers={"X-Line-Signature": "bad"}
    )
    assert response.status_code == 400


def test_callback_accepts_valid_signature(line):
    assert post([]).status_code == 200


def test_init_command_binds_group_and_replies(line):
    assert post([message_event("G1", "U1", "/初始化")]).status_code == 200

    assert len(line["replies"]) == 1
    token, text = line["replies"][0]
    assert token == "token-1"
    assert "初始化完成" in text


def test_commands_before_init_are_ignored(line):
    post([message_event("G1", "U1", "/名單")])

    assert line["replies"] == []
    assert line["left"] == []


def test_plain_chat_is_ignored(line):
    post([message_event("G1", "U1", "/初始化")])
    line["replies"].clear()

    post([message_event("G1", "U1", "今天天氣不錯")])

    assert line["replies"] == []


def test_other_group_message_makes_bot_leave(line):
    post([message_event("G1", "U1", "/初始化")])
    line["replies"].clear()

    post([message_event("G2", "U9", "/名單")])

    assert line["left"] == ["G2"]
    assert line["replies"] == []


def test_joining_other_group_makes_bot_leave(line):
    post([message_event("G1", "U1", "/初始化")])

    post([join_event("G2")])

    assert line["left"] == ["G2"]


def test_joining_before_binding_does_not_leave(line):
    post([join_event("G1")])
    assert line["left"] == []


def open_week_in_two_weeks() -> str:
    """開一個兩週後的場次（用實際日期，避免日期過了之後測試失效）。"""
    game_date = (datetime.now(TZ) + timedelta(days=14)).date().isoformat()
    post([message_event("G1", "U1", "/初始化")])
    post([message_event("G1", "U1", f"/開週 {game_date}")])
    return game_date


def test_card_command_replies_with_flex_card(line):
    open_week_in_two_weeks()

    post([message_event("G1", "U1", "/報名卡")])

    assert len(line["cards"]) == 1
    token, card = line["cards"][0]
    assert token == "token-1"
    assert "籃球報名" in card.alt_text


def test_push_card_command_pushes_to_bound_group_and_confirms(line):
    open_week_in_two_weeks()
    line["replies"].clear()

    post([message_event("G1", "U1", "/推播報名卡")])

    assert len(line["pushes"]) == 1
    group_id, card = line["pushes"][0]
    assert group_id == "G1"
    assert "籃球報名" in card.alt_text
    assert "已用推播發出報名卡" in line["replies"][0][1]


def test_push_card_failure_is_reported_to_admin(line):
    open_week_in_two_weeks()
    line["replies"].clear()
    line["push_fails"] = True

    assert post([message_event("G1", "U1", "/推播報名卡")]).status_code == 200

    assert line["pushes"] == []
    assert "推播失敗" in line["replies"][0][1]


def test_button_press_registers_and_replies(line):
    game_date = open_week_in_two_weeks()
    line["replies"].clear()

    post([postback_event("G1", "U2", f"a=register&w={game_date}")])

    assert len(line["replies"]) == 1
    token, text = line["replies"][0]
    assert token == "token-3"
    assert "Shan 報名成功（零打）" in text


def test_button_press_from_other_group_makes_bot_leave(line):
    game_date = open_week_in_two_weeks()
    line["replies"].clear()

    post([postback_event("G2", "U2", f"a=register&w={game_date}")])

    assert line["left"] == ["G2"]
    assert line["replies"] == []


def test_button_press_before_binding_is_ignored(line):
    post([postback_event("G1", "U2", "a=register&w=2026-11-01")])

    assert line["replies"] == [] and line["left"] == []


def test_reply_failure_does_not_break_webhook(line, monkeypatch):
    async def broken_reply(reply_token, text):
        raise RuntimeError("LINE API down")

    monkeypatch.setattr(line_client, "reply_text", broken_reply)

    assert post([message_event("G1", "U1", "/初始化")]).status_code == 200
