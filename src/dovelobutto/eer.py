from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from .html import clean_text, parse_html, table_matrix


BASE_CELEX = "02000D0532-20231206"
AMENDMENT_CELEX = "32025D0934"
CORRIGENDUM_CELEX = "32025D0934R(01)"
BASE_URL = f"https://eur-lex.europa.eu/legal-content/IT/TXT/HTML/?uri=CELEX:{BASE_CELEX}"
AMENDMENT_URL = f"https://eur-lex.europa.eu/legal-content/IT/TXT/HTML/?uri=CELEX:{AMENDMENT_CELEX}"
CORRIGENDUM_URL = (
    "https://eur-lex.europa.eu/legal-content/IT/TXT/HTML/"
    f"?uri=CELEX:{CORRIGENDUM_CELEX}"
)

_CODE_CELL_RE = re.compile(
    r"^[«\s]*(\d{2}(?:\s+\d{2}){0,2})\s*(\*)?\s*[»;,.]*$"
)
_ENTRY_REFERENCE_RE = re.compile(r"(?<!\d)(\d{2})\s+(\d{2})\s+(\d{2})(?!\d)")
_EDITORIAL_MARKER_RE = re.compile(r"[►◄]\s*[A-Z]?\d*\s*")
_TRAILING_FOOTNOTE_RE = re.compile(r"\s*\(\s*\d+\s*\)\s*$")
_ITALIAN_MONTHS = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}


def normalize_eer_code(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return digits if len(digits) == 6 else None


def display_eer_code(code: str) -> str:
    return f"{code[:2]} {code[2:4]} {code[4:]}"


def _clean_title(value: str) -> str:
    title = _EDITORIAL_MARKER_RE.sub("", clean_text(value)).strip(" «")
    title = re.sub(r"[»;]+\.?$", "", title).strip()
    return _TRAILING_FOOTNOTE_RE.sub("", title).strip()


def _parse_code_cell(value: str) -> tuple[str, bool] | None:
    match = _CODE_CELL_RE.fullmatch(clean_text(value))
    if match is None:
        return None
    code = re.sub(r"\s", "", match.group(1))
    return code, bool(match.group(2))


def _catalog_rows(html: str) -> list[list[str]]:
    root = parse_html(html)
    tables = root.find_all(lambda element: element.tag == "table")
    if not tables:
        raise ValueError("The EUR-Lex source does not contain tables")
    candidates = [table_matrix(table)[1] for table in tables]
    rows = max(candidates, key=len)
    if sum(_parse_code_cell(row[0]) is not None for row in rows if row) < 900:
        raise ValueError("The consolidated EER table appears incomplete")
    return rows


def parse_consolidated_eer(html: str) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {
        "chapters": {},
        "subchapters": {},
        "entries": {},
    }
    for row in _catalog_rows(html):
        if len(row) < 2:
            continue
        parsed = _parse_code_cell(row[0])
        if parsed is None:
            continue
        code, hazardous = parsed
        title = _clean_title(row[1])
        if len(code) not in {2, 4, 6} or not title:
            continue
        if len(code) == 2:
            result["chapters"][code] = {
                "chapter_id": f"eer-chapter:{code}",
                "code": code,
                "display_code": code,
                "title": title,
            }
        elif len(code) == 4:
            result["subchapters"][code] = {
                "subchapter_id": f"eer-subchapter:{code}",
                "code": code,
                "display_code": f"{code[:2]} {code[2:]}",
                "title": title,
                "chapter_ref": f"eer-chapter:{code[:2]}",
            }
        else:
            result["entries"][code] = _entry(code, title, hazardous, BASE_CELEX)
    if len(result["chapters"]) != 20 or len(result["entries"]) != 842:
        raise ValueError(
            "Unexpected consolidated EER counts: "
            f"{len(result['chapters'])} chapters, {len(result['entries'])} entries"
        )
    return result


def _entry(code: str, title: str, hazardous: bool, source_celex: str) -> dict[str, Any]:
    return {
        "entry_id": f"eer:{code}",
        "code": code,
        "display_code": display_eer_code(code),
        "title": title,
        "hazardous": hazardous,
        "chapter_ref": f"eer-chapter:{code[:2]}",
        "subchapter_ref": f"eer-subchapter:{code[:4]}",
        "source_celex": source_celex,
    }


def _amendment_rows(html: str) -> dict[str, dict[str, Any]]:
    root = parse_html(html)
    items: dict[str, dict[str, Any]] = {}
    for table in root.find_all(lambda element: element.tag == "table"):
        for row in table_matrix(table)[1]:
            if len(row) < 2:
                continue
            parsed = _parse_code_cell(row[0])
            if parsed is None:
                continue
            code, hazardous = parsed
            if len(code) not in {4, 6}:
                continue
            title = _clean_title(row[1])
            if not title:
                continue
            candidate = {
                "code": code,
                "title": title,
                "hazardous": hazardous,
            }
            previous = items.get(code)
            if previous is not None and previous != candidate:
                raise ValueError(f"Conflicting amendment rows for EER {code}")
            items[code] = candidate
    return items


def _amendment_instructions(html: str) -> tuple[set[str], set[str]]:
    text = parse_html(html).text
    replaced_subchapters = {
        re.sub(r"\s", "", match.group(1))
        for match in re.finditer(
            r"(?:capitolo|sottocapitolo)\s+(\d{2}\s+\d{2})\s+è sostituito",
            text,
            re.IGNORECASE,
        )
    }
    deleted_codes = {
        re.sub(r"\s", "", match.group(1))
        for match in re.finditer(
            r"la voce\s+(\d{2}\s+\d{2}\s+\d{2})\*?\s+è soppressa",
            text,
            re.IGNORECASE,
        )
    }
    for match in re.finditer(
        r"le voci\s+(.{1,160}?)\s+sono soppresse",
        text,
        re.IGNORECASE,
    ):
        deleted_codes.update(
            "".join(groups)
            for groups in _ENTRY_REFERENCE_RE.findall(match.group(1))
        )
    return replaced_subchapters, deleted_codes


def _corrected_applicability_date(corrigendum_html: str) -> date:
    text = parse_html(corrigendum_html).text
    match = re.search(
        r"leggasi:\s*«?Essa si applica a decorrere dal\s+"
        r"(\d{1,2})\s+([a-zà]+)\s+(\d{4})",
        text,
        re.IGNORECASE,
    )
    if match is None:
        raise ValueError("The corrigendum applicability date was not found")
    month = _ITALIAN_MONTHS.get(match.group(2).casefold())
    if month is None:
        raise ValueError(f"Unknown Italian month: {match.group(2)}")
    return date(int(match.group(3)), month, int(match.group(1)))


def _source(path: Path, celex: str, url: str, document_date: str) -> dict[str, Any]:
    return {
        "celex": celex,
        "url": url,
        "document_date": document_date,
        "file": path.as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _add_references(
    entries: dict[str, dict[str, Any]], retired: dict[str, dict[str, Any]]
) -> None:
    for entry in entries.values():
        reference_codes = []
        for groups in _ENTRY_REFERENCE_RE.findall(entry["title"]):
            code = "".join(groups)
            if code not in reference_codes:
                reference_codes.append(code)
        references = []
        for code in reference_codes:
            target = entries.get(code) or retired.get(code)
            references.append(
                {
                    "code": code,
                    "display_code": display_eer_code(code),
                    "title": target["title"] if target else None,
                    "hazardous": target["hazardous"] if target else None,
                    "status": "active" if code in entries else "retired" if code in retired else "unknown",
                }
            )
        entry["references"] = references

        def expand(match: re.Match[str]) -> str:
            code = "".join(match.groups())
            target = entries.get(code) or retired.get(code)
            if target is None:
                return match.group(0)
            return f"{target['title']} ({display_eer_code(code)})"

        entry["title_expanded"] = _ENTRY_REFERENCE_RE.sub(expand, entry["title"])


def build_eer_register(
    base_path: Path,
    amendment_path: Path,
    corrigendum_path: Path,
    generated_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    base = parse_consolidated_eer(base_path.read_text(encoding="utf-8"))
    final = deepcopy(base)
    amendment_html = amendment_path.read_text(encoding="utf-8")
    amendment_rows = _amendment_rows(amendment_html)
    replaced_subchapters, explicitly_deleted = _amendment_instructions(amendment_html)

    removed_by_replacement = {
        code
        for code, entry in final["entries"].items()
        if entry["subchapter_ref"].split(":")[-1] in replaced_subchapters
    }
    for code in removed_by_replacement | explicitly_deleted:
        final["entries"].pop(code, None)
    for subchapter in replaced_subchapters:
        final["subchapters"].pop(subchapter, None)

    for code, item in amendment_rows.items():
        if len(code) == 4:
            final["subchapters"][code] = {
                "subchapter_id": f"eer-subchapter:{code}",
                "code": code,
                "display_code": f"{code[:2]} {code[2:]}",
                "title": item["title"],
                "chapter_ref": f"eer-chapter:{code[:2]}",
                "source_celex": AMENDMENT_CELEX,
            }
        else:
            final["entries"][code] = _entry(
                code, item["title"], item["hazardous"], AMENDMENT_CELEX
            )

    base_entries = base["entries"]
    final_entries = final["entries"]
    added_codes = sorted(set(final_entries) - set(base_entries))
    removed_codes = sorted(set(base_entries) - set(final_entries))
    modified_codes = sorted(
        code
        for code in set(base_entries) & set(final_entries)
        if (
            base_entries[code]["title"],
            base_entries[code]["hazardous"],
        )
        != (final_entries[code]["title"], final_entries[code]["hazardous"])
    )
    applicability = _corrected_applicability_date(
        corrigendum_path.read_text(encoding="utf-8")
    )
    retired = {
        code: {
            **base_entries[code],
            "valid_to": date.fromordinal(applicability.toordinal() - 1).isoformat(),
            "retired_by_celex": AMENDMENT_CELEX,
        }
        for code in removed_codes
    }
    _add_references(final_entries, retired)

    for chapter in final["chapters"].values():
        chapter["subchapter_refs"] = [
            f"eer-subchapter:{code}"
            for code in sorted(final["subchapters"])
            if code.startswith(chapter["code"])
        ]
    for subchapter in final["subchapters"].values():
        subchapter["entry_refs"] = [
            f"eer:{code}"
            for code in sorted(final_entries)
            if code.startswith(subchapter["code"])
        ]

    sources = [
        _source(base_path, BASE_CELEX, BASE_URL, "2023-12-06"),
        _source(amendment_path, AMENDMENT_CELEX, AMENDMENT_URL, "2025-05-20"),
        _source(
            corrigendum_path,
            CORRIGENDUM_CELEX,
            CORRIGENDUM_URL,
            "2025-08-19",
        ),
    ]
    register = {
        "version": 1,
        "register_id": "eer:eu:2025-934-corrigendum-01",
        "language": "it",
        "generated_at": generated_at.isoformat(),
        "valid_from": applicability.isoformat(),
        "status_at_generation": (
            "applicable" if generated_at.date() >= applicability else "future"
        ),
        "sources": sources,
        "changes": {
            "added_codes": added_codes,
            "modified_codes": modified_codes,
            "retired_codes": removed_codes,
        },
        "chapters": [final["chapters"][code] for code in sorted(final["chapters"])],
        "subchapters": [
            final["subchapters"][code] for code in sorted(final["subchapters"])
        ],
        "entries": [final_entries[code] for code in sorted(final_entries)],
        "retired_entries": [retired[code] for code in sorted(retired)],
    }
    unresolved_reference_details = [
        {
            "entry_code": entry["code"],
            "entry_title": entry["title"],
            "referenced_code": reference["code"],
        }
        for entry in register["entries"]
        for reference in entry["references"]
        if reference["status"] == "unknown"
    ]
    report = {
        "generated_at": generated_at.isoformat(),
        "valid_from": applicability.isoformat(),
        "status_at_generation": register["status_at_generation"],
        "chapters": len(register["chapters"]),
        "subchapters": len(register["subchapters"]),
        "entries": len(register["entries"]),
        "hazardous_entries": sum(entry["hazardous"] for entry in register["entries"]),
        "entries_with_references": sum(bool(entry["references"]) for entry in register["entries"]),
        "unresolved_references": len(unresolved_reference_details),
        "unresolved_reference_details": unresolved_reference_details,
        "changes": register["changes"],
        "sources": sources,
    }
    return register, report


def validate_acquired_eer(
    register: dict[str, Any], input_dirs: Iterable[Path]
) -> dict[str, Any]:
    active = {entry["code"]: entry for entry in register["entries"]}
    retired = {entry["code"]: entry for entry in register["retired_entries"]}
    assertions: list[dict[str, Any]] = []
    for input_dir in input_dirs:
        for path in sorted(input_dir.rglob("*-acquisition.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("record_type") != "facility_acceptance":
                    continue
                payload = record["payload"]
                code = normalize_eer_code(
                    payload.get("eer_code_normalized") or payload.get("eer_code_raw")
                )
                if code in active:
                    status = "active_in_target"
                    official = active[code]
                elif code in retired:
                    status = "retired_in_target"
                    official = retired[code]
                else:
                    status = "missing_or_malformed" if code is None else "unknown_code"
                    official = None
                assertions.append(
                    {
                        "record_id": record["record_id"],
                        "source_file": path.as_posix(),
                        "source_url": record["source"]["url"],
                        "facility_ref": payload["facility_ref"],
                        "source_code": payload.get("eer_code_raw"),
                        "normalized_code": code,
                        "source_description": payload["description_raw"],
                        "status": status,
                        "official_title": official["title"] if official else None,
                        "official_hazardous": official["hazardous"] if official else None,
                    }
                )
    by_status = {
        status: sum(item["status"] == status for item in assertions)
        for status in (
            "active_in_target",
            "retired_in_target",
            "unknown_code",
            "missing_or_malformed",
        )
    }
    return {
        "register_id": register["register_id"],
        "register_valid_from": register["valid_from"],
        "assertions": len(assertions),
        "unique_codes": sorted(
            {item["normalized_code"] for item in assertions if item["normalized_code"]}
        ),
        "by_status": by_status,
        "issues": [
            item for item in assertions if item["status"] != "active_in_target"
        ],
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
