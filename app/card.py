"""報名卡（LINE Flex Message）。

Flex Message 就是用 JSON 描述的卡片版面。這裡只負責產生 JSON，
不碰 LINE SDK，所以可以直接測試。注意：卡片送出後無法更新內容。
"""
from dataclasses import dataclass
from datetime import date

from app.models import Week

WEEKDAYS = "一二三四五六日"

# 卡片上可由管理員設定的資訊：指令用的中文名稱 → 資料庫的鍵
INFO_FIELDS = {"地點": "venue", "時間": "time", "費用": "fee", "備註": "note"}


@dataclass(frozen=True)
class Card:
    alt_text: str  # 通知與聊天列表上顯示的文字
    contents: dict  # Flex Message 的 JSON 結構


def _text(text: str, **options) -> dict:
    return {"type": "text", "text": text, "wrap": True, **options}


def _button(label: str, action: str, week: Week, style: str) -> dict:
    # 按鈕按下後，LINE 會把 data 原樣送回 webhook（postback 事件）
    return {
        "type": "button",
        "style": style,
        "height": "sm",
        "flex": 1,
        "action": {
            "type": "postback",
            "label": label,
            "data": f"a={action}&w={week.game_date}",
        },
    }


def _info_lines(info: dict[str, str]) -> list[dict]:
    lines = []
    if info.get("venue"):
        lines.append(_text(f"📍 {info['venue']}", size="sm"))
    if info.get("time"):
        lines.append(_text(f"🕖 {info['time']}", size="sm"))
    if info.get("fee"):
        lines.append(_text(f"💰 零打 NT${info['fee']}／次", size="sm"))
    if info.get("note"):
        lines.append(_text(info["note"], size="sm", color="#888888"))
    return lines


def build_card(week: Week, info: dict[str, str]) -> Card:
    game = date.fromisoformat(week.game_date)
    deadline = week.deadline
    title = f"🏀 {game.month}/{game.day}（{WEEKDAYS[game.weekday()]}）籃球報名"
    rule = (
        f"名額 {week.capacity} 人（分 4 隊）\n"
        f"季打保障名額，零打依報名順序\n"
        f"報名截止 {deadline.month}/{deadline.day}（{WEEKDAYS[deadline.weekday()]}）{deadline:%H:%M}"
    )
    contents = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                _text(title, weight="bold", size="lg"),
                *_info_lines(info),
                {"type": "separator", "margin": "md"},
                _text(rule, size="xs", color="#888888", margin="md"),
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "sm",
                    "contents": [
                        _button("報名", "register", week, "primary"),
                        _button("取消", "cancel", week, "secondary"),
                    ],
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "sm",
                    "contents": [
                        _button("帶朋友 +1", "guest", week, "secondary"),
                        _button("查看名單", "roster", week, "secondary"),
                    ],
                },
            ],
        },
    }
    return Card(alt_text=title, contents=contents)
