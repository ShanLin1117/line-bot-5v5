"""SQLite 存取層。

Java 對照：相當於 Repository / DAO，用標準函式庫 sqlite3（類似 JDBC）。
SQL 一律用 ? 佔位符傳參數，不要用字串拼接，避免 SQL injection。
"""
import sqlite3
from datetime import datetime
from pathlib import Path

from app.models import Entry, Member, Week

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    is_season    INTEGER NOT NULL DEFAULT 0,
    is_admin     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS weeks (
    game_date TEXT PRIMARY KEY,
    deadline  TEXT NOT NULL,
    capacity  INTEGER NOT NULL DEFAULT 20
);
CREATE TABLE IF NOT EXISTS registrations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    game_date     TEXT NOT NULL REFERENCES weeks(game_date),
    member_id     INTEGER NOT NULL REFERENCES members(id),
    guest_name    TEXT,  -- NULL 表示本人；有值表示 member_id 帶來的朋友
    registered_at TEXT NOT NULL,
    cancelled_at  TEXT
);
"""


def _member(row: sqlite3.Row) -> Member:
    return Member(
        id=row["id"],
        user_id=row["user_id"],
        display_name=row["display_name"],
        is_season=bool(row["is_season"]),
        is_admin=bool(row["is_admin"]),
    )


class Database:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False：FastAPI 可能在不同執行緒處理請求。
        # 這個專案流量很小，單一連線加上每次寫入立即 commit 就夠用
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # --- 設定 ---

    def get_setting(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        # `with self.conn` 相當於一個交易：區塊正常結束就 commit，丟例外就 rollback
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def delete_setting(self, key: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM settings WHERE key = ?", (key,))

    # --- 成員 ---

    def upsert_member(self, user_id: str, display_name: str) -> Member:
        """不存在就新增，存在就更新顯示名稱。

        刻意不用 INSERT ... ON CONFLICT：即使走到更新分支，SQLite 也會消耗一個
        自動遞增編號，造成成員編號跳號，而編號是要給管理員輸入的。
        """
        with self.conn:
            row = self.conn.execute(
                "SELECT * FROM members WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row is None:
                self.conn.execute(
                    "INSERT INTO members(user_id, display_name) VALUES (?, ?)",
                    (user_id, display_name),
                )
            elif row["display_name"] != display_name:
                self.conn.execute(
                    "UPDATE members SET display_name = ? WHERE user_id = ?",
                    (display_name, user_id),
                )
        row = self.conn.execute("SELECT * FROM members WHERE user_id = ?", (user_id,)).fetchone()
        return _member(row)

    def get_member(self, member_id: int) -> Member | None:
        row = self.conn.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
        return _member(row) if row else None

    def get_member_by_user_id(self, user_id: str) -> Member | None:
        row = self.conn.execute("SELECT * FROM members WHERE user_id = ?", (user_id,)).fetchone()
        return _member(row) if row else None

    def list_members(self) -> list[Member]:
        rows = self.conn.execute("SELECT * FROM members ORDER BY id").fetchall()
        return [_member(r) for r in rows]

    def set_season(self, member_id: int, flag: bool) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE members SET is_season = ? WHERE id = ?", (int(flag), member_id)
            )
        return cur.rowcount > 0

    def clear_season(self) -> None:
        with self.conn:
            self.conn.execute("UPDATE members SET is_season = 0")

    def set_admin(self, member_id: int, flag: bool) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE members SET is_admin = ? WHERE id = ?", (int(flag), member_id)
            )
        return cur.rowcount > 0

    # --- 場次 ---

    def create_week(self, game_date: str, deadline: datetime, capacity: int = 20) -> bool:
        """建立場次；同一天已存在則回傳 False。"""
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO weeks(game_date, deadline, capacity) VALUES (?, ?, ?)",
                    (game_date, deadline.isoformat(), capacity),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def current_week(self) -> Week | None:
        """目前場次 = 比賽日期最晚的那一場。"""
        row = self.conn.execute("SELECT * FROM weeks ORDER BY game_date DESC LIMIT 1").fetchone()
        if not row:
            return None
        return Week(
            game_date=row["game_date"],
            deadline=datetime.fromisoformat(row["deadline"]),
            capacity=row["capacity"],
        )

    # --- 報名 ---

    def add_registration(
        self, game_date: str, member_id: int, guest_name: str | None, now: datetime
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO registrations(game_date, member_id, guest_name, registered_at) "
                "VALUES (?, ?, ?, ?)",
                (game_date, member_id, guest_name, now.isoformat()),
            )
        return cur.lastrowid

    def find_active(self, game_date: str, member_id: int, guest_name: str | None) -> int | None:
        # SQLite 的 IS 運算子可以正確比較 NULL（用 = 比較 NULL 永遠不成立）
        row = self.conn.execute(
            "SELECT id FROM registrations "
            "WHERE game_date = ? AND member_id = ? AND guest_name IS ? AND cancelled_at IS NULL",
            (game_date, member_id, guest_name),
        ).fetchone()
        return row["id"] if row else None

    def cancel_registration(self, registration_id: int, now: datetime) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE registrations SET cancelled_at = ? WHERE id = ?",
                (now.isoformat(), registration_id),
            )

    def entries(self, game_date: str) -> list[Entry]:
        rows = self.conn.execute(
            "SELECT r.id, r.member_id, r.guest_name, r.registered_at, "
            "       m.display_name, m.is_season "
            "FROM registrations r JOIN members m ON m.id = r.member_id "
            "WHERE r.game_date = ? AND r.cancelled_at IS NULL "
            "ORDER BY r.registered_at, r.id",
            (game_date,),
        ).fetchall()
        result = []
        for r in rows:
            is_guest = r["guest_name"] is not None
            label = f"{r['guest_name']}（{r['display_name']} 帶）" if is_guest else r["display_name"]
            result.append(
                Entry(
                    id=r["id"],
                    label=label,
                    is_season=bool(r["is_season"]) and not is_guest,
                    registered_at=datetime.fromisoformat(r["registered_at"]),
                    owner_id=r["member_id"],
                    is_guest=is_guest,
                )
            )
        return result
