from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from .catalog import normalize_term


_PRIVATE_PATTERN = re.compile(
    r"(?:https?://|www\.|\b[^\s@]+@[^\s@]+\b|\b\d{7,}\b)", re.IGNORECASE,
)


class MissingQueryStore:
    def __init__(self, database: Path) -> None:
        self.database = database

    def record(
        self,
        text: str,
        *,
        municipality_istat: str,
        zone_id: str | None,
        user_type: str,
        dataset_revision: int | None,
        reason: str,
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        display_query = " ".join(text.strip().split())[:160]
        normalized_query = normalize_term(display_query)
        if (
            len(normalized_query) < 2
            or _PRIVATE_PATTERN.search(display_query)
            or reason not in {"unknown_term", "known_without_route"}
        ):
            return {"recorded": False, "reason": "privacy_or_quality_filter"}
        observed_at = observed_at or datetime.now(timezone.utc)
        fingerprint = hashlib.sha256(json.dumps({
            "query": normalized_query,
            "municipality": municipality_istat,
            "zone": zone_id,
            "user_type": user_type,
            "reason": reason,
        }, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database, timeout=10)
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS missing_queries (
                    fingerprint TEXT PRIMARY KEY,
                    normalized_query TEXT NOT NULL,
                    display_query TEXT NOT NULL,
                    municipality_istat TEXT NOT NULL,
                    zone_id TEXT,
                    user_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    first_dataset_revision INTEGER,
                    last_dataset_revision INTEGER,
                    occurrence_count INTEGER NOT NULL,
                    review_status TEXT NOT NULL DEFAULT 'pending',
                    review_note TEXT
                )"""
            )
            connection.execute(
                """INSERT INTO missing_queries (
                    fingerprint, normalized_query, display_query,
                    municipality_istat, zone_id, user_type, reason,
                    first_seen_at, last_seen_at, first_dataset_revision,
                    last_dataset_revision, occurrence_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    display_query = excluded.display_query,
                    last_seen_at = excluded.last_seen_at,
                    last_dataset_revision = excluded.last_dataset_revision,
                    occurrence_count = missing_queries.occurrence_count + 1""",
                (
                    fingerprint, normalized_query, display_query,
                    municipality_istat, zone_id, user_type, reason,
                    observed_at.isoformat(), observed_at.isoformat(),
                    dataset_revision, dataset_revision,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return {"recorded": True, "fingerprint": fingerprint}

    def report(self, *, min_count: int = 1, limit: int = 1000) -> dict[str, Any]:
        if not self.database.exists():
            rows: list[sqlite3.Row] = []
        else:
            connection = sqlite3.connect(self.database)
            connection.row_factory = sqlite3.Row
            try:
                rows = connection.execute(
                    """SELECT * FROM missing_queries
                    WHERE occurrence_count >= ?
                    ORDER BY occurrence_count DESC, last_seen_at DESC
                    LIMIT ?""",
                    (max(1, min_count), max(1, min(limit, 10000))),
                ).fetchall()
            finally:
                connection.close()
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "privacy": {
                "stores_ip": False,
                "stores_location_coordinates": False,
                "stores_user_identifier": False,
                "rejected_patterns": ["email", "url", "digit_sequence_7_plus"],
            },
            "entries": [dict(row) for row in rows],
        }

    def set_review_status(
        self, fingerprint: str, status: str, note: str | None = None,
    ) -> bool:
        if status not in {"pending", "accepted", "rejected", "mapped"}:
            raise ValueError("Unknown missing-query review status")
        if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            raise ValueError("Invalid missing-query fingerprint")
        if not self.database.exists():
            return False
        connection = sqlite3.connect(self.database)
        try:
            cursor = connection.execute(
                """UPDATE missing_queries
                SET review_status = ?, review_note = ?
                WHERE fingerprint = ?""",
                (status, note, fingerprint),
            )
            connection.commit()
            return cursor.rowcount == 1
        finally:
            connection.close()


def write_missing_query_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
