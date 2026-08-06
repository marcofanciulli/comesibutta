from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable


EER_PATTERN = re.compile(r"\bEER\s+([0-9]{6})(\*)?\s*:\s*([^|]+)", re.IGNORECASE)
CATEGORY_PATTERN = re.compile(r"\bCategoria\s+[^:]+:\s*([^|]+)", re.IGNORECASE)


def normalize_term(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_value = "".join(character for character in decomposed if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", ascii_value).strip()


def concept_id(normalized_term: str) -> str:
    return "waste:" + normalized_term.replace(" ", "-")


def display_label(labels: Iterable[str]) -> str:
    unique = sorted(
        {label.strip() for label in labels if label.strip()},
        key=lambda item: (item.isupper(), len(item), item.casefold(), item),
    )
    label = unique[0]
    if label.isupper() and len(label) > 4:
        return label.capitalize()
    return label


def _source_assertion_key(record: dict[str, Any]) -> tuple[str, ...]:
    payload = record["payload"]
    source = record["source"]
    return (
        source["url"],
        source["content_sha256"],
        normalize_term(payload["term"]),
        payload.get("destination_raw") or "",
        payload.get("instructions_raw") or "",
    )


def _read_municipal_records(
    input_dirs: list[Path], registry_paths: list[Path]
) -> list[dict[str, Any]]:
    municipalities: dict[str, dict[str, Any]] = {}
    for registry_path in registry_paths:
        for line in registry_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                payload = json.loads(line)["payload"]
                municipalities[payload["istat_code"]] = payload

    records = []
    for istat_code, municipality in municipalities.items():
        path = next(
            (
                directory / f"{municipality['source_slug']}-acquisition.jsonl"
                for directory in input_dirs
                if (directory / f"{municipality['source_slug']}-acquisition.jsonl").exists()
            ),
            None,
        )
        if path is None:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record["record_type"] == "waste_lookup":
                records.append({**record, "municipality_istat": istat_code})
    return records


def build_waste_catalog(
    records: list[dict[str, Any]],
    generated_at: datetime,
    eer_register: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    official_entries = {
        entry["code"]: ("active_in_target", entry)
        for entry in (eer_register or {}).get("entries", [])
    }
    official_entries.update({
        entry["code"]: ("retired_in_target", entry)
        for entry in (eer_register or {}).get("retired_entries", [])
    })
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        normalized = normalize_term(record["payload"]["term"])
        if normalized:
            grouped[normalized].append(record)

    concepts = []
    unique_assertions_total = 0
    for normalized, term_records in sorted(grouped.items()):
        assertion_groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for record in term_records:
            assertion_groups[_source_assertion_key(record)].append(record)
        unique_assertions_total += len(assertion_groups)

        labels = sorted(
            {record["payload"]["term"].strip() for record in term_records},
            key=lambda item: (item.casefold(), item),
        )
        eer_candidates: dict[str, dict[str, Any]] = {}
        categories: dict[str, str] = {}
        destination_groups: dict[str, dict[str, Any]] = {}
        evidence = []

        for assertion_records in assertion_groups.values():
            representative = assertion_records[0]
            payload = representative["payload"]
            source = representative["source"]
            municipalities = sorted({record["municipality_istat"] for record in assertion_records})
            instructions = payload.get("instructions_raw") or ""

            category_match = CATEGORY_PATTERN.search(instructions)
            category = category_match.group(1).strip() if category_match else None
            if category:
                categories.setdefault(normalize_term(category), category)

            eer_match = EER_PATTERN.search(instructions)
            if eer_match:
                code = eer_match.group(1)
                candidate = eer_candidates.setdefault(
                    code,
                    {
                        "code": code,
                        "source_labels": set(),
                        "hazardous_assertions": set(),
                        "source_urls": set(),
                    },
                )
                candidate["source_labels"].add(eer_match.group(3).strip())
                if eer_match.group(2) or (category and "pericol" in category.casefold()):
                    candidate["hazardous_assertions"].add(True)
                candidate["source_urls"].add(source["url"])

            destination = payload.get("destination_raw")
            if destination:
                destination_key = normalize_term(destination)
                local = destination_groups.setdefault(
                    destination_key,
                    {"label": destination, "municipality_istats": set(), "source_urls": set()},
                )
                local["municipality_istats"].update(municipalities)
                local["source_urls"].add(source["url"])

            evidence.append(
                {
                    "source_url": source["url"],
                    "publisher": source.get("publisher"),
                    "retrieved_at": source["retrieved_at"],
                    "municipality_istats": municipalities,
                    "destination_raw": destination,
                    "instructions_raw": payload.get("instructions_raw"),
                    "quote": source["evidence"].get("quote"),
                }
            )

        candidates = []
        for code, candidate in sorted(eer_candidates.items()):
            hazardous: bool | None = True if True in candidate["hazardous_assertions"] else None
            official_status, official = official_entries.get(
                code, ("unknown_code" if eer_register else "not_checked", None)
            )
            candidates.append(
                {
                    "code": code,
                    "source_labels": sorted(candidate["source_labels"], key=lambda item: (item.casefold(), item)),
                    "hazardous": hazardous,
                    "source_urls": sorted(candidate["source_urls"]),
                    "register_status": official_status,
                    "official_title": official["title"] if official else None,
                    "official_hazardous": official["hazardous"] if official else None,
                    "valid_to": official.get("valid_to") if official else None,
                }
            )
        if len(candidates) == 1:
            eer_status = "source_consensus"
        elif candidates:
            eer_status = "conflict"
        else:
            eer_status = "not_available"

        local_destinations = [
            {
                "label": item["label"],
                "municipality_istats": sorted(item["municipality_istats"]),
                "source_urls": sorted(item["source_urls"]),
            }
            for _, item in sorted(destination_groups.items())
        ]
        concepts.append(
            {
                "concept_id": concept_id(normalized),
                "preferred_label": display_label(labels),
                "normalized_term": normalized,
                "terms": labels,
                "language": "it",
                "eer": {"status": eer_status, "candidates": candidates},
                "source_categories": sorted(categories.values(), key=lambda item: (item.casefold(), item)),
                "local_destinations": local_destinations,
                "coverage": {
                    "municipalities": sorted({record["municipality_istat"] for record in term_records}),
                    "publishers": sorted({record["source"].get("publisher") or "Fonte non indicata" for record in term_records}),
                    "source_assertions": len(assertion_groups),
                },
                "general_details": {
                    "material": None,
                    "conditions": [],
                    "environmental_note": None,
                    "review_status": "automatic_source_identity",
                },
                "evidence": sorted(evidence, key=lambda item: (item["source_url"], item["destination_raw"] or "")),
            }
        )

    candidate_statuses = [
        candidate["register_status"]
        for concept in concepts
        for candidate in concept["eer"]["candidates"]
    ]
    report = {
        "generated_at": generated_at.isoformat(),
        "waste_lookup_records": len(records),
        "source_assertions": unique_assertions_total,
        "concepts": len(concepts),
        "concepts_with_eer": sum(concept["eer"]["status"] == "source_consensus" for concept in concepts),
        "eer_conflicts": sum(concept["eer"]["status"] == "conflict" for concept in concepts),
        "concepts_without_eer": sum(concept["eer"]["status"] == "not_available" for concept in concepts),
        "concepts_with_multiple_local_destinations": sum(len(concept["local_destinations"]) > 1 for concept in concepts),
        "general_details_pending": len(concepts),
        "eer_register_id": (eer_register or {}).get("register_id"),
        "eer_candidates_by_register_status": {
            status: candidate_statuses.count(status)
            for status in (
                "active_in_target",
                "retired_in_target",
                "unknown_code",
                "not_checked",
            )
        },
    }
    return {
        "version": 2,
        "generated_at": generated_at.isoformat(),
        "eer_register": (
            {
                "register_id": eer_register["register_id"],
                "valid_from": eer_register["valid_from"],
                "status_at_generation": eer_register["status_at_generation"],
            }
            if eer_register else None
        ),
        "concepts": concepts,
    }, report


def build_catalog_from_paths(
    input_dirs: list[Path],
    registry_paths: list[Path],
    generated_at: datetime,
    eer_register_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return build_waste_catalog(
        _read_municipal_records(input_dirs, registry_paths),
        generated_at,
        (
            json.loads(eer_register_path.read_text(encoding="utf-8"))
            if eer_register_path else None
        ),
    )


def write_catalog(path: Path, catalog: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
