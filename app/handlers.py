"""指令處理。

Java 對照：相當於 Service 層。所有函式只依賴 Database 與 Context，
不依賴 LINE SDK 與 FastAPI，所以可以直接單元測試。
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from urllib.parse import parse_qs

from app.card import INFO_FIELDS, WEEKDAYS, Card, build_card
from app.db import BOUND_GROUP_KEY, Database
from app.models import TZ, Member, Week
from app.roster import format_roster, roster_for
from app.scheduler import default_deadline, next_open, target_game_date

HELP_TEXT = """📖 指令說明
每週日 20:00 Bot 會自動發出報名卡，直接按按鈕即可。
也可以用指令：
/報名　報名本場次
/取消　取消自己的報名
/帶人 阿豪　幫朋友報名
/取消帶人 阿豪　取消朋友的報名
/名單　查看目前名單
/成員　列出成員與編號
指令都在最後加上日期，就是指定加開場，例如：/名單 11/06

🔧 管理員
/報名卡　重新發出報名卡（含所有開放的加開場）
/加開場 11/06 20 晚上7點 中正運動中心　加開場次（人數、說明可省略，先搶先贏）
/取消加開場 11/06　取消加開場，報名資料一併清除
/排程狀態　查看自動推播的時間與狀態
/開週 10/25　手動開放例行場報名
/設季打 3 7 12　依編號標記季打
/取消季打 5　取消季打標記
/重設季打　新季開始時清除全部季打
/管理員 加 3　依編號新增管理員
/解除綁定　解除群組綁定

🖊 設定報名卡上顯示的文字（管理員）
/設定　查看目前內容
/設定 地點 威湧運動中心
/設定 時間 07:00-09:00
/設定 費用 200
/設定 備註 第15季 4/13次
只打項目、不打內容（例如「/設定 備註」）就是清除"""


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


def check_group_postback(bound_group_id: str | None, group_id: str) -> str:
    """按鈕事件的群組檢查：尚未綁定時一律忽略，其他群組一律退出。"""
    if bound_group_id is None:
        return "ignore"
    return "allow" if group_id == bound_group_id else "leave"


def handle_postback(ctx: Context, data: str) -> str | None:
    """處理報名卡按鈕。data 格式：a=動作&w=場次日期，例如 a=register&w=2026-11-01。"""
    params = parse_qs(data)
    action = params.get("a", [""])[0]
    game_date = params.get("w", [""])[0]
    handler = POSTBACK_ACTIONS.get(action)
    if handler is None:
        return None

    member = ctx.db.upsert_member(ctx.user_id, ctx.display_name)
    week = ctx.db.get_week(game_date)
    current = _active_week(ctx)
    expired = (
        week is None
        or ctx.now.date() > date.fromisoformat(week.game_date)
        # 例行場只能報「目前」這一場；舊卡仍然可以按，但場次已經換了，不能讓人誤報到新的場次
        or (not week.is_extra and (current is None or current.game_date != week.game_date))
    )
    if expired:
        return "這張報名卡已經過期，請使用最新的報名卡，或傳 /報名卡 重新發出"
    return handler(ctx, member, week)


def handle_command(ctx: Context, text: str) -> str | Card | None:
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


NO_WEEK = "目前沒有開放報名的場次，請管理員用 /開週 日期 開啟"
_DATE_TOKEN = re.compile(r"(?:\d{4}[-/])?\d{1,2}[-/]\d{1,2}")


def _active_week(ctx: Context) -> Week | None:
    """目前的例行場；已經過了比賽日就視為沒有。"""
    week = ctx.db.current_week()
    if week is None or ctx.now.date() > date.fromisoformat(week.game_date):
        return None
    return week


def _split_date(args: list[str]) -> tuple[list[str], str | None]:
    """指令最後一個參數若是日期，就拆出來，用來指定加開場。"""
    if args and _DATE_TOKEN.fullmatch(args[-1]):
        return args[:-1], args[-1]
    return args, None


def _pick_week(ctx: Context, raw_date: str | None) -> Week | str:
    """沒指定日期用目前的例行場；指定日期則找該日的場次。失敗時回傳錯誤訊息。"""
    if raw_date is None:
        return _active_week(ctx) or NO_WEEK
    game_date = _parse_game_date(raw_date, ctx.now.date())
    week = ctx.db.get_week(game_date.isoformat()) if game_date else None
    if week is None or ctx.now.date() > date.fromisoformat(week.game_date):
        return f"找不到 {raw_date} 的場次"
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

    deadline = default_deadline(game_date)
    if not ctx.db.create_week(game_date.isoformat(), deadline):
        return f"{game_date.month}/{game_date.day} 的場次已經存在了"
    return (
        f"✅ 已開放 {game_date.month}/{game_date.day} 場次報名\n"
        f"名額 20 人｜報名截止 {_fmt_deadline(deadline)}"
    )


def cmd_open_extra(ctx: Context, member: Member, args: list[str]) -> str | Card:
    """加開場：不分季打零打，依報名順序先搶先贏。例如 /加開場 11/06 20 晚上7點 中正運動中心"""
    usage = "用法：/加開場 11/06 [人數] [說明]\n例如：/加開場 11/06 20 晚上7點 中正運動中心"
    if not args:
        return usage
    game_date = _parse_game_date(args[0], ctx.now.date())
    if game_date is None:
        return "日期格式不正確\n" + usage
    if game_date < ctx.now.date():
        return "這個日期已經過了"

    rest, capacity = args[1:], 20
    if rest and rest[0].isdigit():
        capacity, rest = int(rest[0]), rest[1:]
        if not 1 <= capacity <= 60:
            return "人數請輸入 1 到 60"

    # 加開場沒有「截止」的概念，截止時間只是填給資料表用，設在比賽日當天結束
    deadline = datetime.combine(game_date, time(23, 59), tzinfo=TZ)
    created = ctx.db.create_week(
        game_date.isoformat(), deadline, capacity, kind="extra", note=" ".join(rest)
    )
    if not created:
        return f"{game_date.month}/{game_date.day} 已經有場次了（同一天只能有一個場次）"
    return _combined_card(ctx)


def cmd_cancel_extra(ctx: Context, member: Member, args: list[str]) -> str:
    if len(args) != 1:
        return "用法：/取消加開場 11/06"
    game_date = _parse_game_date(args[0], ctx.now.date())
    week = ctx.db.get_week(game_date.isoformat()) if game_date else None
    if week is None or not week.is_extra:
        return f"找不到 {args[0]} 的加開場"
    removed = ctx.db.delete_week(week.game_date)
    suffix = f"（已清除 {removed} 筆報名）" if removed else ""
    return f"✅ 已取消 {game_date.month}/{game_date.day} 加開場{suffix}"


# --- 報名與取消 ---


def _register(ctx: Context, member: Member, week: Week, guest_name: str | None) -> str:
    who = guest_name or member.display_name
    if ctx.db.find_active(week.game_date, member.id, guest_name) is not None:
        return f"{who} 已經報名過了"

    reg_id = ctx.db.add_registration(week.game_date, member.id, guest_name, ctx.now)
    roster = roster_for(ctx.db.entries(week.game_date), week)
    total = f"正取 {len(roster.confirmed)}/{week.capacity}"

    entry = next((e for e in roster.confirmed if e.id == reg_id), None)
    if entry is not None:
        # 加開場不分季打零打，所以不標示身分
        kind = "" if week.is_extra else ("（季打）" if entry.is_season else "（零打）")
        return f"✅ {who} 報名成功{kind}｜{total}"
    position = next(i for i, e in enumerate(roster.waitlist, start=1) if e.id == reg_id)
    return f"⏳ {who} 排候補第 {position} 位｜{total}"


def _cancel(ctx: Context, member: Member, week: Week, guest_name: str | None) -> str:
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
    week = _pick_week(ctx, _split_date(args)[1])
    return week if isinstance(week, str) else _register(ctx, member, week, None)


def cmd_cancel(ctx: Context, member: Member, args: list[str]) -> str:
    week = _pick_week(ctx, _split_date(args)[1])
    return week if isinstance(week, str) else _cancel(ctx, member, week, None)


def cmd_guest_add(ctx: Context, member: Member, args: list[str]) -> str:
    name_parts, raw_date = _split_date(args)
    if not name_parts:
        return "用法：/帶人 阿豪（加開場在最後加日期，例如 /帶人 阿豪 11/06）"
    week = _pick_week(ctx, raw_date)
    return week if isinstance(week, str) else _register(ctx, member, week, " ".join(name_parts))


def cmd_guest_cancel(ctx: Context, member: Member, args: list[str]) -> str:
    name_parts, raw_date = _split_date(args)
    if not name_parts:
        return "用法：/取消帶人 阿豪（加開場在最後加日期，例如 /取消帶人 阿豪 11/06）"
    week = _pick_week(ctx, raw_date)
    return week if isinstance(week, str) else _cancel(ctx, member, week, " ".join(name_parts))


def cmd_roster(ctx: Context, member: Member, args: list[str]) -> str:
    week = _pick_week(ctx, _split_date(args)[1])
    return week if isinstance(week, str) else _roster_text(ctx, week)


def _roster_text(ctx: Context, week: Week) -> str:
    roster = roster_for(ctx.db.entries(week.game_date), week)
    return format_roster(week, roster, ctx.now)


# 報名卡按鈕的處理：與指令共用 _register / _cancel，差別只在場次由按鈕提供


def _button_register(ctx: Context, member: Member, week: Week) -> str:
    return _register(ctx, member, week, None)


def _button_cancel(ctx: Context, member: Member, week: Week) -> str:
    return _cancel(ctx, member, week, None)


def _button_guest(ctx: Context, member: Member, week: Week) -> str:
    """「帶朋友 +1」按鈕：自動命名為「名稱友1」「名稱友2」…，不用打字。"""
    n = 1
    while ctx.db.find_active(week.game_date, member.id, f"{member.display_name}友{n}") is not None:
        n += 1
    name = f"{member.display_name}友{n}"
    reply = _register(ctx, member, week, name)
    # 加開場的指令要多帶日期，才知道是哪一場
    on = f" {_short_date(week)}" if week.is_extra else ""
    return reply + f"\n要改名字：/取消帶人 {name}{on}，再 /帶人 新名字{on}"


def _button_roster(ctx: Context, member: Member, week: Week) -> str:
    return _roster_text(ctx, week)


def _short_date(week: Week) -> str:
    game = date.fromisoformat(week.game_date)
    return f"{game.month}/{game.day}"


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


def _combined_card(ctx: Context) -> str | Card:
    """合併報名卡：目前的例行場，加上所有尚未過期的加開場。"""
    regular = _active_week(ctx)
    extras = ctx.db.open_extras(ctx.now.date().isoformat())
    if regular is None and not extras:
        return NO_WEEK
    return build_card(regular, ctx.db.get_card_info(), extras)


def cmd_card(ctx: Context, member: Member, args: list[str]) -> str | Card:
    return _combined_card(ctx)


def _fmt_moment(dt: datetime) -> str:
    return f"{dt.month}/{dt.day}（{WEEKDAYS[dt.weekday()]}）{dt:%H:%M}"


def cmd_schedule_status(ctx: Context, member: Member, args: list[str]) -> str:
    """說明排程現在會做什麼，不需要等到週日就能確認排程設定是否正常。"""
    lines = ["🕒 排程狀態", f"現在時間：{_fmt_moment(ctx.now)}"]

    target = target_game_date(ctx.now)
    if target is None:
        lines.append("目前不在自動推播的報名期間")
    else:
        pushed_at = ctx.db.get_setting(f"card_pushed_{target.isoformat()}")
        state = f"已於 {_fmt_moment(datetime.fromisoformat(pushed_at))} 推播" if pushed_at else "尚未推播（排程會在一分鐘內補發）"
        lines.append(f"報名期間中的場次：{target.month}/{target.day}，報名卡{state}")

    game_date, opens_at = next_open(ctx.now)
    lines.append(f"下次自動推播：{_fmt_moment(opens_at)}（場次 {game_date.month}/{game_date.day}）")
    lines.append("提醒：伺服器與 ngrok 都要保持開著，排程才會執行")
    return "\n".join(lines)


def cmd_info(ctx: Context, member: Member, args: list[str]) -> str:
    """設定報名卡上顯示的資訊，例如 /設定 地點 威湧運動中心。"""
    if not args:
        info = ctx.db.get_card_info()
        lines = ["⚙️ 目前卡片資訊"]
        for label, key in INFO_FIELDS.items():
            lines.append(f"{label}：{info.get(key, '（未設定）')}")
        lines.append("設定方式：/設定 地點 威湧運動中心（想清除就不填內容）")
        return "\n".join(lines)

    label, value = args[0], " ".join(args[1:])
    key = INFO_FIELDS.get(label)
    if key is None:
        return "可設定的項目：" + "、".join(INFO_FIELDS)
    if value:
        ctx.db.set_setting(f"info_{key}", value)
        return f"✅ 已設定{label}：{value}\n之後發出的報名卡會使用新內容"
    ctx.db.delete_setting(f"info_{key}")
    return f"✅ 已清除{label}"


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
    "/報名卡": cmd_card,
    "/加開場": cmd_open_extra,
    "/取消加開場": cmd_cancel_extra,
    "/排程狀態": cmd_schedule_status,
    "/設定": cmd_info,
    "/說明": cmd_help,
}

ADMIN_COMMANDS = {
    "/解除綁定", "/開週", "/設季打", "/取消季打", "/重設季打", "/管理員",
    "/報名卡", "/加開場", "/取消加開場", "/排程狀態", "/設定",
}

# 報名卡按鈕對照表，動作名稱與 card.py 的 postback data 一致
POSTBACK_ACTIONS = {
    "register": _button_register,
    "cancel": _button_cancel,
    "guest": _button_guest,
    "roster": _button_roster,
}
