"""Local at-most-once journal; IDs/status only, never keys or trails."""
from pathlib import Path
import sqlite3


class WorkerState:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, kind TEXT NOT NULL, round INTEGER NOT NULL, status TEXT NOT NULL)")
        self.db.commit()

    def claim(self, run_id, kind, *, round_number=None):
        if not isinstance(run_id, str) or not run_id or len(run_id) > 128 or kind not in ("red", "blue"):
            raise ValueError("invalid worker command")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            if self.db.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
                self.db.rollback()
                return None
            number = round_number or self.db.execute("SELECT COALESCE(MAX(round),0)+1 FROM runs WHERE kind=?", (kind,)).fetchone()[0]
            if number < 1:
                raise ValueError("round must be positive")
            self.db.execute("INSERT INTO runs VALUES (?,?,?,'running')", (run_id, kind, number))
            self.db.commit()
            return number
        except Exception:
            self.db.rollback()
            raise

    def finish(self, run_id, status):
        if status not in ("completed", "failed", "interrupted"):
            raise ValueError("invalid run status")
        self.db.execute("UPDATE runs SET status=? WHERE run_id=?", (status, run_id))
        self.db.commit()

    def close(self):
        self.db.close()
