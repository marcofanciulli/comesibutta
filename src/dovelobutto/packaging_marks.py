from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import unicodedata


DECISION_CELEX = "31997D0129"
DECISION_URL = "https://eur-lex.europa.eu/legal-content/IT/TXT/?uri=CELEX:31997D0129"

FAMILY_RANGES = (
    (1, 19, "plastic"),
    (20, 39, "paper_cardboard"),
    (40, 49, "metal"),
    (50, 59, "wood"),
    (60, 69, "textile"),
    (70, 79, "glass"),
    (80, 99, "composite"),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _family_for_code(code: int) -> str:
    for start, end, family in FAMILY_RANGES:
        if start <= code <= end:
            return family
    raise ValueError(f"Packaging material code outside the official range: {code}")


def _read_transcription(path: Path) -> dict[int, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    required = {
        "numeric_code", "material_family", "material_name_it", "abbreviation",
        "composition_it", "predominant_family",
    }
    if not rows or set(rows[0]) != required:
        raise ValueError("Unexpected packaging material transcription columns")
    result = {}
    for row in rows:
        code = int(row["numeric_code"])
        if code in result:
            raise ValueError(f"Duplicate packaging material code: {code}")
        expected_family = _family_for_code(code)
        if row["material_family"] != expected_family:
            raise ValueError(
                f"Packaging material code {code} belongs to {expected_family}, "
                f"not {row['material_family']}"
            )
        if expected_family == "composite":
            if row["abbreviation"] or not row["predominant_family"]:
                raise ValueError(f"Composite code {code} must use the predominant-material rule")
        elif not row["abbreviation"]:
            raise ValueError(f"Assigned code {code} has no abbreviation")
        result[code] = row
    if len(result) != 31:
        raise ValueError(f"Expected 31 assigned packaging material codes, found {len(result)}")
    return result


def _fold_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    folded = " ".join(
        "".join(character for character in decomposed if not unicodedata.combining(character))
        .casefold()
        .split()
    )
    return re.sub(r"\s*/\s*", "/", folded)


def _validate_transcription_source(
    assigned: dict[int, dict[str, str]], extracted_text_path: Path, html_path: Path,
) -> None:
    extracted = _fold_text(extracted_text_path.read_text(encoding="utf-8"))
    missing_labels = [
        row["material_name_it"]
        for row in assigned.values()
        if _fold_text(row["material_name_it"]) not in extracted
    ]
    if missing_labels:
        raise ValueError(f"Packaging transcription labels absent from PDF text: {missing_labels}")
    html = _fold_text(html_path.read_text(encoding="utf-8"))
    if "decisione della commissione" not in html or "97/129/ce" not in html.replace(" ", ""):
        raise ValueError("The EUR-Lex HTML source is not Decision 97/129/EC")


def _entry(code: int, row: dict[str, str] | None) -> dict[str, Any]:
    family = _family_for_code(code)
    if row is None:
        return {
            "mark_id": f"packaging-material:eu-97-129:{code}",
            "numeric_code": code,
            "material_family": family,
            "assignment_status": "unassigned",
            "material_name": None,
            "abbreviation": None,
            "abbreviation_rule": None,
            "composition": [],
            "predominant_family": None,
            "display_code": str(code),
            "recognition_tokens": [str(code)],
            "disposal_semantics": "none",
        }
    abbreviation = row["abbreviation"] or None
    composite = family == "composite"
    recognition_tokens = [str(code)]
    if abbreviation:
        recognition_tokens.insert(0, abbreviation)
    else:
        recognition_tokens.insert(0, "C/")
    return {
        "mark_id": f"packaging-material:eu-97-129:{code}",
        "numeric_code": code,
        "material_family": family,
        "assignment_status": "assigned",
        "material_name": row["material_name_it"],
        "abbreviation": abbreviation,
        "abbreviation_rule": "C/{predominant_material_abbreviation}" if composite else None,
        "composition": [
            item.strip() for item in row["composition_it"].split(";") if item.strip()
        ],
        "predominant_family": row["predominant_family"] or None,
        "display_code": (
            f"C/{{materiale predominante}} {code}" if composite
            else f"{abbreviation} {code}"
        ),
        "recognition_tokens": recognition_tokens,
        "disposal_semantics": "none",
    }


def build_packaging_material_register(
    transcription_path: Path,
    pdf_path: Path,
    html_path: Path,
    extracted_text_path: Path,
    generated_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    assigned = _read_transcription(transcription_path)
    _validate_transcription_source(assigned, extracted_text_path, html_path)
    sources = [
        {
            "role": "official_pdf",
            "celex": DECISION_CELEX,
            "url": DECISION_URL,
            "file": pdf_path.as_posix(),
            "sha256": _sha256(pdf_path),
        },
        {
            "role": "official_html",
            "celex": DECISION_CELEX,
            "url": DECISION_URL,
            "file": html_path.as_posix(),
            "sha256": _sha256(html_path),
        },
        {
            "role": "pdftotext_layout_transcription",
            "celex": DECISION_CELEX,
            "url": DECISION_URL,
            "file": extracted_text_path.as_posix(),
            "sha256": _sha256(extracted_text_path),
        },
        {
            "role": "checked_machine_readable_transcription",
            "celex": DECISION_CELEX,
            "url": DECISION_URL,
            "file": transcription_path.as_posix(),
            "sha256": _sha256(transcription_path),
        },
    ]
    entries = [_entry(code, assigned.get(code)) for code in range(1, 100)]
    register = {
        "version": 1,
        "register_id": "packaging-materials:eu:97-129-ec",
        "language": "it",
        "generated_at": generated_at.isoformat(),
        "scheme": {
            "name": "Sistema UE di identificazione dei materiali di imballaggio",
            "legal_basis": "Decisione 97/129/CE",
            "celex": DECISION_CELEX,
            "document_date": "1997-01-28",
            "publication_date": "1997-02-20",
            "use_at_source": "voluntary",
            "visual_specification": "not_defined",
            "scope": "material_identification",
        },
        "sources": sources,
        "entries": entries,
    }
    by_family = {
        family: sum(entry["material_family"] == family for entry in entries)
        for _, _, family in FAMILY_RANGES
    }
    assigned_by_family = {
        family: sum(
            entry["material_family"] == family
            and entry["assignment_status"] == "assigned"
            for entry in entries
        )
        for _, _, family in FAMILY_RANGES
    }
    report = {
        "generated_at": generated_at.isoformat(),
        "register_id": register["register_id"],
        "numeric_slots": len(entries),
        "assigned_codes": len(assigned),
        "unassigned_codes": len(entries) - len(assigned),
        "families": by_family,
        "assigned_by_family": assigned_by_family,
        "composite_codes": assigned_by_family["composite"],
        "entries_with_disposal_semantics": sum(
            entry["disposal_semantics"] != "none" for entry in entries
        ),
        "transcription_labels_verified": len(assigned),
        "sources": sources,
    }
    return register, report


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
