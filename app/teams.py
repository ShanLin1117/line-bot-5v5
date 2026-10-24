"""分組（規則見 docs/rules.md）。

純函式：輸入名字清單與亂數產生器，輸出分好的隊伍，不碰資料庫與 LINE。
亂數產生器由外部傳入，測試時可以用固定種子得到可重現的結果。
"""
import random
import string
from datetime import date

from app.models import Week

TEAM_SIZE = 5
MIN_RECOMMENDED = 3  # 最後一隊少於這個人數時提醒管理員


def split_into_teams(names: list[str], rng: random.Random, team_size: int = TEAM_SIZE) -> list[list[str]]:
    """隨機打亂後，依序把每隊補滿 team_size 人，剩下的人放在最後一隊。

    例：19 人 → 5、5、5、4；18 人 → 5、5、5、3。
    隊數 = 人數 ÷ team_size 無條件進位，所以 20 人正好 4 隊。
    """
    shuffled = list(names)  # 複製一份，不改動傳進來的清單
    rng.shuffle(shuffled)
    return [shuffled[i : i + team_size] for i in range(0, len(shuffled), team_size)]


def team_name(index: int) -> str:
    return string.ascii_uppercase[index]


def format_teams(week: Week, teams: list[list[str]]) -> str:
    game = date.fromisoformat(week.game_date)
    total = sum(len(team) for team in teams)
    title = "加開場" if week.is_extra else ""
    lines = [f"🏀 {game.month}/{game.day} {title}分組結果（共 {total} 人）"]

    for index, team in enumerate(teams):
        lines += ["", f"【{team_name(index)} 隊】{len(team)} 人", ""]
        lines += [f"{number}. {name}" for number, name in enumerate(team, start=1)]

    smallest = min(range(len(teams)), key=lambda i: len(teams[i]))
    if len(teams[smallest]) < MIN_RECOMMENDED:
        lines += ["", f"⚠️ {team_name(smallest)} 隊只有 {len(teams[smallest])} 人，可視情況現場調整"]
    return "\n".join(lines)
