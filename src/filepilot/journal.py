from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from .models import FileRecord, MovePlan
from .safety import SafetyError, absolute, path_key


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_data_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "FilePilot"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "filepilot"


def record_json(file: FileRecord) -> str:
    return json.dumps({"relative": file.relative, "size": file.size, "mtime_ns": file.mtime_ns,
                       "device": file.device, "inode": file.inode, "category": file.category}, ensure_ascii=False)


def record_from_item(item: dict, *, at_destination: bool = False) -> FileRecord:
    fields = json.loads(item["snapshot"])
    path = Path(item["destination"] if at_destination else item["source"])
    return FileRecord(path=path, digest=item["digest"], **fields)


class Journal:
    def __init__(self, path: Path | str):
        self.path = absolute(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise SafetyError("历史数据库版本较新，请使用相应版本的 FilePilot。")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS batches (
                    id TEXT PRIMARY KEY, created TEXT NOT NULL, updated TEXT NOT NULL,
                    kind TEXT NOT NULL, root TEXT NOT NULL, destination_root TEXT NOT NULL,
                    state TEXT NOT NULL, message TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS items (
                    batch_id TEXT NOT NULL REFERENCES batches(id), position INTEGER NOT NULL,
                    source TEXT NOT NULL, destination TEXT NOT NULL, snapshot TEXT NOT NULL,
                    digest TEXT NOT NULL, state TEXT NOT NULL, message TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (batch_id, position)
                );
                CREATE INDEX IF NOT EXISTS items_batch_state ON items(batch_id, state);
                PRAGMA user_version = 1;
            """)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def operation_lock(self) -> Iterator[None]:
        # An OS lock is automatically released if the process crashes. No stale-lock deletion.
        lock_path = self.path.with_suffix(".lock")
        stream = lock_path.open("a+b")
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        acquired = False
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as exc:
            stream.close()
            raise SafetyError("另一项文件操作正在进行，请稍后重试。") from exc
        try:
            yield
        finally:
            if acquired:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()

    def begin(self, plan: MovePlan, digests: dict[str, str]) -> str:
        batch_id = uuid4().hex
        stamp = now_iso()
        with self.connect() as connection:
            connection.execute("INSERT INTO batches VALUES (?, ?, ?, ?, ?, ?, 'executing', '')",
                               (batch_id, stamp, stamp, plan.kind, str(plan.root), str(plan.destination_root)))
            connection.executemany("INSERT INTO items VALUES (?, ?, ?, ?, ?, ?, 'planned', '')",
                                   [(batch_id, position, str(item.file.path), str(item.destination), record_json(item.file),
                                     digests[path_key(item.file.path)]) for position, item in enumerate(plan.items)])
        return batch_id

    def item_state(self, batch_id: str, position: int, state: str, message: str = "") -> None:
        with self.connect() as connection:
            connection.execute("UPDATE items SET state = ?, message = ? WHERE batch_id = ? AND position = ?",
                               (state, message, batch_id, position))

    def batch_state(self, batch_id: str, state: str, message: str = "") -> None:
        with self.connect() as connection:
            connection.execute("UPDATE batches SET state = ?, message = ?, updated = ? WHERE id = ?",
                               (state, message, now_iso(), batch_id))

    def items(self, batch_id: str) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM items WHERE batch_id = ? ORDER BY position", (batch_id,))]

    def batch(self, batch_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
        if row is None:
            raise SafetyError("找不到该操作的历史记录。")
        return dict(row)

    def recent(self, limit: int = 200) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("""
                SELECT b.*, COUNT(i.position) AS total,
                       SUM(CASE WHEN i.state = 'moved' THEN 1 ELSE 0 END) AS moved,
                       SUM(CASE WHEN i.state = 'undone' THEN 1 ELSE 0 END) AS undone
                FROM batches b LEFT JOIN items i ON i.batch_id = b.id
                GROUP BY b.id ORDER BY b.created DESC, b.rowid DESC LIMIT ?
            """, (limit,))]
