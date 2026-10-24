"""報名卡（LINE Flex Message）。

Flex Message 就是用 JSON 描述的卡片版面。這裡只負責產生 JSON，
不碰 LINE SDK，所以可以直接測試。注意：卡片送出後無法更新內容。

一張報名卡包含「目前所有開放的場次」：上面是例行場，下面依日期接著每個加開場，
每個區塊都有自己的按鈕，按鈕綁定該區塊的場次。
"""
from collections.abc import Sequence
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


def _buttons(week: Week) -> list[dict]:
    def row(*buttons: dict) -> dict:
        return {"type": "box", "layout": "horizontal", "spacing": "sm", "contents": list(buttons)}

    return [
        row(_button("報名", "register", week, "primary"), _button("取消", "cancel", week, "secondary")),
        row(
            _button("帶朋友 +1", "guest", week, "secondary"),
            _button("查看名單", "roster", week, "secondary"),
        ),
    ]


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


def _title(week: Week) -> str:
    game = date.fromisoformat(week.game_date)
    label = "加開場報名" if week.is_extra else "籃球報名"
    prefix = "⚡" if week.is_extra else "🏀"
    return f"{prefix} {game.month}/{game.day}（{WEEKDAYS[game.weekday()]}）{label}"


def _regular_section(week: Week, info: dict[str, str]) -> list[dict]:
    deadline = week.deadline
    rule = (
        f"名額 {week.capacity} 人（分 4 隊）\n"
        f"季打保障名額，零打依報名順序\n"
        f"報名截止 {deadline.month}/{deadline.day}（{WEEKDAYS[deadline.weekday()]}）{deadline:%H:%M}"
    )
    return [
        _text(_title(week), weight="bold", size="lg"),
        *_info_lines(info),
        _text(rule, size="xs", color="#888888", margin="md"),
        *_buttons(week),
    ]


def _extra_section(week: Week) -> list[dict]:
    rule = f"名額 {week.capacity} 人\n不分季打零打，依報名順序（先搶先贏）"
    note = [_text(week.note, size="sm")] if week.note else []
    return [
        _text(_title(week), weight="bold", size="lg"),
        *note,
        _text(rule, size="xs", color="#888888", margin="md"),
        *_buttons(week),
    ]


def build_card(
    regular: Week | None, info: dict[str, str], extras: Sequence[Week] = ()
) -> Card:
    """合併報名卡：先放例行場，再依日期放加開場。至少要有一個場次。"""
    sections = []
    if regular is not None:
        sections.append(_regular_section(regular, info))
    sections += [_extra_section(week) for week in extras]
    assert sections, "build_card needs at least one week"

    body: list[dict] = []
    for index, section in enumerate(sections):
        if index > 0:
            body.append({"type": "separator", "margin": "lg"})
        body += section

    first = regular if regular is not None else extras[0]
    alt_text = _title(first) + (f"（另有 {len(sections) - 1} 個場次）" if len(sections) > 1 else "")
    contents = {
        "type": "bubble",
        "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": body},
    }
    return Card(alt_text=alt_text, contents=contents)
