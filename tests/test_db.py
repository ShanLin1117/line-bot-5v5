import sqlite3
from datetime import datetime

from app.db import Database
from app.models import TZ

DEADLINE = datetime(2026, 10, 23, 12, 30, tzinfo=TZ)
NOW = datetime(2026, 10, 18, 20, 0, tzinfo=TZ)


def test_old_database_is_upgraded_without_losing_data(tmp_path):
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE weeks (
            game_date TEXT PRIMARY KEY, deadline TEXT NOT NULL,
            capacity INTEGER NOT NULL DEFAULT 20
        );
        INSERT INTO weeks VALUES ('2026-10-25', '2026-10-23T12:30:00+08:00', 20);
        """
    )
    old.commit()
    old.close()

    db = Database(path)  # 開啟時應自動補上 kind 與 note

    week = db.get_week("2026-10-25")
    assert (week.kind, week.note, week.capacity) == ("regular", "", 20)
    assert db.create_week("2026-11-06", DEADLINE, 15, kind="extra", note="晚上7點")
    assert db.get_week("2026-11-06").is_extra

    Database(path)  # 再開一次不會因為欄位已存在而失敗


def test_current_week_ignores_extras_and_open_extras_filters_by_date():
    db = Database(":memory:")
    db.create_week("2026-10-25", DEADLINE)
    db.create_week("2026-11-06", DEADLINE, kind="extra")
    db.create_week("2026-11-13", DEADLINE, kind="extra")
    db.create_week("2026-10-30", DEADLINE, kind="extra")

    assert db.current_week().game_date == "2026-10-25"
    assert [w.game_date for w in db.open_extras("2026-11-01")] == ["2026-11-06", "2026-11-13"]
    assert [w.game_date for w in db.open_extras("2026-11-06")] == ["2026-11-06", "2026-11-13"]
    assert db.open_extras("2026-11-14") == []


def test_delete_week_removes_registrations_and_counts_active_ones():
    db = Database(":memory:")
    db.create_week("2026-11-06", DEADLINE, kind="extra")
    bob = db.upsert_member("U1", "Bob")
    cat = db.upsert_member("U2", "Cat")
    db.add_registration("2026-11-06", bob.id, None, NOW)
    cancelled = db.add_registration("2026-11-06", cat.id, None, NOW)
    db.cancel_registration(cancelled, NOW)

    assert db.delete_week("2026-11-06") == 1  # 只算有效報名
    assert db.get_week("2026-11-06") is None
    assert db.entries("2026-11-06") == []
    assert db.delete_week("2026-11-06") == 0
