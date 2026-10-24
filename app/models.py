"""資料模型。

Java 對照：相當於 record / POJO。frozen=True 表示建立後不可修改。
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# 台灣沒有日光節約時間，固定 UTC+8 即可，不需要額外安裝時區資料庫
TZ = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class Member:
    id: int  # 內部編號，給管理員用指令指定人（例如 /設季打 3）
    user_id: str  # LINE 使用者 ID，辨識「是誰」一律用它
    display_name: str
    is_season: bool
    is_admin: bool


@dataclass(frozen=True)
class Week:
    game_date: str  # 比賽日期 YYYY-MM-DD，同時是場次的識別
    deadline: datetime
    capacity: int


@dataclass(frozen=True)
class Entry:
    """一筆有效的報名紀錄，名單計算的輸入。"""

    id: int
    label: str  # 名單上顯示的名稱
    is_season: bool  # 朋友永遠是 False
    registered_at: datetime
    owner_id: int  # 報名者的成員編號；朋友則是帶人者
    is_guest: bool
