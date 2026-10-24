"""指令處理。

Java 對照：相當於 Service 層。所有函式只依賴 Database 與 Context，
不依賴 LINE SDK 與 FastAPI，所以可以直接單元測試。
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.db import Database
from app.models import TZ, Member, Week
from app.roster import format_roster, roster_for

BOUND_GROUP_KEY = "bound_group_id"

HELP_TEXT = """📖 指令說明
/報名　報名本場次
/取消　取消自己的報名
/帶人 阿豪　幫朋友報名
/取消帶人 阿豪　取消朋友的報名
/名單　查看目前名單
/成員　列出成員與編號

🔧 管理員
/開週 10/25　開放場次報名
/設季打 3 7 12　依編號標記季打
/取消季打 5　取消季打標記
/重設季打　新季開始時清除全部季打
/管理員 加 3　依編號新增管理員
/解除綁定　解除群組綁定"""


@dataclass
class Context:
    db: Database
    group_id: str
    user_id: str
    display_name: str
    now: datetime


def check_group(bound_group_id: str | None, group_id: str, text: str) -> str:
    """決定群組事件要如何處理：allow（處理）、ignore（忽略）、leave（退出群組）。"""
    if bound_group_id is not None and group_id != bound_group_id:
        return "leave"
    if not text.strip().startswith("/"):
        return "ignore"
    if bound_group_id is None:
        # 尚未綁定時，只有 /初始化 有效
        return "allow" if text.split()[0] == "/初始化" else "ignore"
    return "allow"


def handle_command(ctx: Context, text: str) -> str | None:
    """依指令回傳要回覆的內容；不是指令則回傳 None（不回覆）。

    `str | None` 是型別提示，相當於 Java 的 Optional<String>，
    Python 不會在執行期強制檢查，主要給 IDE 與讀者看。
    """
    tokens = text.split()  # split() 不帶參數會同時處理半形與全形空白
    if not tokens:
        return None
    command, args = tokens[0], tokens[1:]

    handler = COMMANDS.get(command)
    if handler is None:
        return None

    member = ctx.db.upsert_member(ctx.user_id, ctx.display_name)
    if command in ADMIN_COMMANDS and not member.is_admin:
        return "這個指令只有管理員可以使用"
    return handler(ctx, member, args)


# --- 共用輔助 ---


def _active_week(ctx: Context) -> Week | None:
    week = ctx.db.current_week()
    if week is None or ctx.now.date() > date.fromisoformat(week.game_date):
        return None
    return week


def _parse_game_date(raw: str, today: date) -> date | None:
    """支援 10/25、10-25、2026/10/25；沒寫年份時取今天之後最近的一天。"""
    m = re.fullmatch(r"(?:(\d{4})[-/])?(\d{1,2})[-/](\d{1,2})", raw)
    if not m:
        return None
    year, month, day = m.groups()
    try:
        if year:
            return date(int(year), int(month), int(day))
        parsed = date(today.year, int(month), int(day))
        return parsed if parsed >= today else date(today.year + 1, int(month), int(day))
    except ValueError:
        return None


def _parse_ids(args: list[str]) -> list[int] | None:
    try:
        return [int(a) for a in args]
    except ValueError:
        return None


def _fmt_deadline(dt: datetime) -> str:
    return f"{dt.month}/{dt.day} {dt:%H:%M}"


# --- 群組綁定 ---


def cmd_init(ctx: Context, member: Member, args: list[str]) -> str | None:
    bound = ctx.db.get_setting(BOUND_GROUP_KEY)
    if bound == ctx.group_id:
        return "這個群組已經初始化過了"
    if bound is not None:
        return None
    ctx.db.set_setting(BOUND_GROUP_KEY, ctx.group_id)
    ctx.db.set_admin(member.id, True)
    return f"✅ 初始化完成，{member.display_name} 是管理員\n傳 /說明 查看指令"


def cmd_unbind(ctx: Context, member: Member, args: list[str]) -> str:
    ctx.db.delete_setting(BOUND_GROUP_KEY)
    return "已解除綁定，Bot 不會再處理這個群組的指令。資料仍保留，可在群組重新 /初始化"


# --- 場次 ---


def cmd_open_week(ctx: Context, member: Member, args: list[str]) -> str:
    if len(args) != 1:
        return "用法：/開週 10/25"
    game_date = _parse_game_date(args[0], ctx.now.date())
    if game_date is None:
        return "日期格式不正確，例如：/開週 10/25"
    if game_date < ctx.now.date():
        return "這個日期已經過了"

    # 預設截止時間：比賽日往前 2 天的 12:30（週日場次 → 週五中午）
    deadline = datetime.combine(game_date - timedelta(days=2), time(12, 30), tzinfo=TZ)
    if not ctx.db.create_week(game_date.isoformat(), deadline):
        return f"{game_date.month}/{game_date.day} 的場次已經存在了"
    return (
        f"✅ 已開放 {game_date.month}/{game_date.day} 場次報名\n"
        f"名額 20 人｜報名截止 {_fmt_deadline(deadline)}"
    )


# --- 報名與取消 ---

NO_WEEK = "目前沒有開放報名的場次，請管理員用 /開週 日期 開啟"


def _register(ctx: Context, member: Member, guest_name: str | None) -> str:
    week = _active_week(ctx)
    if week is None:
        return NO_WEEK
    who = guest_name or member.display_name
    if ctx.db.find_active(week.game_date, member.id, guest_name) is not None:
        return f"{who} 已經報名過了"

    reg_id = ctx.db.add_registration(week.game_date, member.id, guest_name, ctx.now)
    roster = roster_for(ctx.db.entries(week.game_date), week)
    total = f"正取 {len(roster.confirmed)}/{week.capacity}"

    entry = next((e for e in roster.confirmed if e.id == reg_id), None)
    if entry is not None:
        kind = "季打" if entry.is_season else "零打"
        return f"✅ {who} 報名成功（{kind}）｜{total}"
    position = next(i for i, e in enumerate(roster.waitlist, start=1) if e.id == reg_id)
    return f"⏳ {who} 排候補第 {position} 位｜{total}"


def _cancel(ctx: Context, member: Member, guest_name: str | None) -> str:
    week = _active_week(ctx)
    if week is None:
        return NO_WEEK
    who = guest_name or member.display_name
    reg_id = ctx.db.find_active(week.game_date, member.id, guest_name)
    if reg_id is None:
        return f"{who} 目前沒有報名"

    before = roster_for(ctx.db.entries(week.game_date), week)
    ctx.db.cancel_registration(reg_id, ctx.now)
    after = roster_for(ctx.db.entries(week.game_date), week)

    lines = [f"❎ {who} 已取消"]
    # 取消後新進入正取的人，就是被遞補的人
    previously_confirmed = {e.id for e in before.confirmed}
    promoted = [e for e in after.confirmed if e.id not in previously_confirmed]
    if promoted:
        lines.append("🔔 候補遞補：" + "、".join(e.label for e in promoted))
    lines.append(f"目前正取 {len(after.confirmed)}/{week.capacity}")
    return "\n".join(lines)


def cmd_register(ctx: Context, member: Member, args: list[str]) -> str:
    return _register(ctx, member, None)


def cmd_cancel(ctx: Context, member: Member, args: list[str]) -> str:
    return _cancel(ctx, member, None)


def cmd_guest_add(ctx: Context, member: Member, args: list[str]) -> str:
    if not args:
        return "用法：/帶人 阿豪"
    return _register(ctx, member, " ".join(args))


def cmd_guest_cancel(ctx: Context, member: Member, args: list[str]) -> str:
    if not args:
        return "用法：/取消帶人 阿豪"
    return _cancel(ctx, member, " ".join(args))


def cmd_roster(ctx: Context, member: Member, args: list[str]) -> str:
    week = _active_week(ctx)
    if week is None:
        return NO_WEEK
    roster = roster_for(ctx.db.entries(week.game_date), week)
    return format_roster(week, roster, ctx.now)


# --- 成員管理 ---


def cmd_members(ctx: Context, member: Member, args: list[str]) -> str:
    members = ctx.db.list_members()
    if not members:
        return "還沒有認識任何成員"
    lines = ["👥 成員（編號.名稱）"]
    for m in members:
        tags = ("［季打］" if m.is_season else "") + ("［管理員］" if m.is_admin else "")
        lines.append(f"{m.id}.{m.display_name}{tags}")
    return "\n".join(lines)


def _set_season(ctx: Context, args: list[str], flag: bool) -> str:
    ids = _parse_ids(args)
    if not ids:
        return "請提供成員編號，例如：/設季打 3 7 12（編號用 /成員 查詢）"
    names, missing = [], []
    for member_id in ids:
        target = ctx.db.get_member(member_id)
        if target is None:
            missing.append(str(member_id))
            continue
        ctx.db.set_season(member_id, flag)
        names.append(target.display_name)

    action = "設為季打" if flag else "取消季打"
    lines = []
    if names:
        lines.append(f"✅ 已{action}：" + "、".join(names))
    if missing:
        lines.append("找不到編號：" + "、".join(missing))
    season_count = sum(1 for m in ctx.db.list_members() if m.is_season)
    lines.append(f"目前季打共 {season_count} 人")
    return "\n".join(lines)


def cmd_set_season(ctx: Context, member: Member, args: list[str]) -> str:
    return _set_season(ctx, args, True)


def cmd_unset_season(ctx: Context, member: Member, args: list[str]) -> str:
    return _set_season(ctx, args, False)


def cmd_reset_season(ctx: Context, member: Member, args: list[str]) -> str:
    ctx.db.clear_season()
    return "✅ 已清除所有季打標記，請用 /設季打 重新設定"


def cmd_admin(ctx: Context, member: Member, args: list[str]) -> str:
    ids = _parse_ids(args[1:]) if len(args) == 2 and args[0] == "加" else None
    if not ids:
        return "用法：/管理員 加 3（編號用 /成員 查詢）"
    target = ctx.db.get_member(ids[0])
    if target is None:
        return f"找不到編號 {ids[0]}"
    ctx.db.set_admin(target.id, True)
    return f"✅ {target.display_name} 已成為管理員"


def cmd_help(ctx: Context, member: Member, args: list[str]) -> str:
    return HELP_TEXT


# 指令對照表。Java 對照：類似 Map<String, Handler>，取代一長串 if-else
COMMANDS = {
    "/初始化": cmd_init,
    "/解除綁定": cmd_unbind,
    "/開週": cmd_open_week,
    "/報名": cmd_register,
    "/取消": cmd_cancel,
    "/帶人": cmd_guest_add,
    "/取消帶人": cmd_guest_cancel,
    "/名單": cmd_roster,
    "/成員": cmd_members,
    "/設季打": cmd_set_season,
    "/取消季打": cmd_unset_season,
    "/重設季打": cmd_reset_season,
    "/管理員": cmd_admin,
    "/說明": cmd_help,
}

ADMIN_COMMANDS = {"/解除綁定", "/開週", "/設季打", "/取消季打", "/重設季打", "/管理員"}
