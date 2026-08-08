from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable
from uuid import NAMESPACE_URL, uuid5


@dataclass(frozen=True)
class SourceDocument:
    url: str
    retrieved_at: datetime
    content: str | bytes
    publisher: str = "SEI Toscana"
    parser: str = "sei_toscana_html"
    parser_version: str = "0.1.0"

    @property
    def sha256(self) -> str:
        body = self.content if isinstance(self.content, bytes) else self.content.encode("utf-8")
        return hashlib.sha256(body).hexdigest()

    def evidence(self, kind: str, selector: str | None, quote: str | None) -> dict[str, Any]:
        return {
            "url": self.url,
            "retrieved_at": self.retrieved_at.isoformat(),
            "content_sha256": self.sha256,
            "publisher": self.publisher,
            "document_date": None,
            "parser": self.parser,
            "parser_version": self.parser_version,
            "evidence": {
                "kind": kind,
                "selector": selector,
                "page": None,
                "quote": quote,
            },
        }


def make_record(
    *,
    record_type: str,
    natural_key: str,
    payload: dict[str, Any],
    source: SourceDocument,
    evidence_kind: str = "html",
    evidence_selector: str | None = None,
    evidence_quote: str | None = None,
    confidence: str = "high",
    validity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identity = f"{natural_key}|{source.url}|{source.sha256}"
    return {
        "record_id": str(uuid5(NAMESPACE_URL, identity)),
        "record_type": record_type,
        "natural_key": natural_key,
        "observed_at": source.retrieved_at.isoformat(),
        "validity": validity or {"valid_from": None, "valid_to": None, "inferred": True},
        "source": source.evidence(evidence_kind, evidence_selector, evidence_quote),
        "confidence": confidence,
        "payload": payload,
    }


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
