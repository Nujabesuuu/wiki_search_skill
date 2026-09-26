"""SQLite cache so repeated and follow-up questions do not re-download data.

- Daily pageviews are stored per (project, title, access); `coverage` keeps merged date
  intervals that are already known, so only missing ranges are requested.
- The last FRESH_DAYS days are never marked as covered: Wikimedia may still be filling them.
- Monthly project totals and JSON responses (Wikidata / MediaWiki) have their own tables.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import date, timedelta
from pathlib import Path

FRESH_DAYS = 3
JSON_TTL_SECONDS = 7 * 24 * 3600


def default_cache_path() -> Path:
    root = os.environ.get("WPV_CACHE_DIR") or os.path.join(
        os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "wiki-interest-research")
    return Path(root) / "cache.sqlite"


def subtract_intervals(covered: list[tuple[date, date]], start: date, end: date) -> list[tuple[date, date]]:
    """Parts of [start, end] (inclusive) not inside any covered interval."""
    gaps, cursor = [], start
    for s, e in sorted(covered):
        if e < cursor:
            continue
        if s > end:
            break
        if s > cursor:
            gaps.append((cursor, min(end, s - timedelta(days=1))))
        cursor = max(cursor, e + timedelta(days=1))
        if cursor > end:
            break
    if cursor <= end:
        gaps.append((cursor, end))
    return gaps


def merge_intervals(intervals: list[tuple[date, date]]) -> list[tuple[date, date]]:
    merged: list[tuple[date, date]] = []
    for s, e in sorted(intervals):
        if merged and s <= merged[-1][1] + timedelta(days=1):
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


class Cache:
    def __init__(self, path: Path | str | None = None, today: date | None = None):
        self.path = Path(path) if path else default_cache_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.today = today or date.today()
        self._lock = threading.Lock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS daily(project TEXT, title TEXT, access TEXT, day TEXT, views INTEGER,
                PRIMARY KEY(project, title, access, day));
            CREATE TABLE IF NOT EXISTS coverage(project TEXT, title TEXT, access TEXT, start TEXT, end TEXT);
            CREATE INDEX IF NOT EXISTS coverage_key ON coverage(project, title, access);
            CREATE TABLE IF NOT EXISTS monthly_total(project TEXT, month TEXT, views INTEGER,
                PRIMARY KEY(project, month));
            CREATE TABLE IF NOT EXISTS json_cache(key TEXT PRIMARY KEY, value TEXT, fetched_at REAL);
        """)

    # ------------------------------------------------------------ daily series
    def _covered(self, project: str, title: str, access: str) -> list[tuple[date, date]]:
        rows = self.db.execute("SELECT start, end FROM coverage WHERE project=? AND title=? AND access=?",
                               (project, title, access)).fetchall()
        return [(date.fromisoformat(s), date.fromisoformat(e)) for s, e in rows]

    def missing_ranges(self, project: str, title: str, access: str, start: date, end: date) -> list[tuple[date, date]]:
        with self._lock:
            return subtract_intervals(self._covered(project, title, access), start, end)

    def store_daily(self, project: str, title: str, access: str, start: date, end: date,
                    rows: dict[date, int]) -> None:
        final_end = min(end, self.today - timedelta(days=FRESH_DAYS))
        with self._lock, self.db:
            self.db.executemany(
                "INSERT OR REPLACE INTO daily VALUES (?,?,?,?,?)",
                [(project, title, access, d.isoformat(), int(v)) for d, v in rows.items()])
            if final_end >= start:
                merged = merge_intervals(self._covered(project, title, access) + [(start, final_end)])
                self.db.execute("DELETE FROM coverage WHERE project=? AND title=? AND access=?",
                                (project, title, access))
                self.db.executemany("INSERT INTO coverage VALUES (?,?,?,?,?)",
                                    [(project, title, access, s.isoformat(), e.isoformat()) for s, e in merged])

    def load_daily(self, project: str, title: str, access: str, start: date, end: date) -> dict[date, int]:
        with self._lock:
            rows = self.db.execute(
                "SELECT day, views FROM daily WHERE project=? AND title=? AND access=? AND day BETWEEN ? AND ?",
                (project, title, access, start.isoformat(), end.isoformat())).fetchall()
        return {date.fromisoformat(d): v for d, v in rows}

    # ------------------------------------------------------------ project totals
    def load_totals(self, project: str, months: list[str]) -> dict[str, int]:
        with self._lock:
            rows = self.db.execute(
                f"SELECT month, views FROM monthly_total WHERE project=? AND month IN ({','.join('?' * len(months))})",
                (project, *months)).fetchall()
        return dict(rows)

    def store_totals(self, project: str, totals: dict[str, int]) -> None:
        # Only complete months that are safely in the past are cached.
        cutoff = (self.today - timedelta(days=FRESH_DAYS)).strftime("%Y-%m")
        with self._lock, self.db:
            self.db.executemany("INSERT OR REPLACE INTO monthly_total VALUES (?,?,?)",
                                [(project, m, int(v)) for m, v in totals.items() if m < cutoff])

    # ------------------------------------------------------------ generic JSON
    def get_json(self, key: str, ttl: float = JSON_TTL_SECONDS):
        with self._lock:
            row = self.db.execute("SELECT value, fetched_at FROM json_cache WHERE key=?", (key,)).fetchone()
        if row and time.time() - row[1] < ttl:
            return json.loads(row[0])
        return None

    def put_json(self, key: str, value) -> None:
        with self._lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO json_cache VALUES (?,?,?)",
                            (key, json.dumps(value, ensure_ascii=False), time.time()))
