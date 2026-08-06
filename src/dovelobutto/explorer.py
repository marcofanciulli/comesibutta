from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any


PROVINCE_NAMES = {
    "AR": "Arezzo",
    "FI": "Firenze",
    "GR": "Grosseto",
    "LI": "Livorno",
    "LU": "Lucca",
    "MS": "Massa-Carrara",
    "PI": "Pisa",
    "PO": "Prato",
    "PT": "Pistoia",
    "SI": "Siena",
}
ATO_NAMES = {
    "ato-toscana-centro": "ATO Toscana Centro",
    "ato-toscana-costa": "ATO Toscana Costa",
    "ato-toscana-sud": "ATO Toscana Sud",
}


def build_explorer_dataset(
    input_dir: Path | list[Path],
    batch_report_paths: Path | list[Path],
    registry_path: Path | list[Path],
    generated_at: datetime,
    catalog_path: Path | None = None,
    eer_register_path: Path | None = None,
) -> dict[str, Any]:
    registry = {}
    registry_paths = [registry_path] if isinstance(registry_path, Path) else registry_path
    for path in registry_paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)["payload"]
            registry[payload["istat_code"]] = payload

    input_dirs = [input_dir] if isinstance(input_dir, Path) else input_dir
    paths = [batch_report_paths] if isinstance(batch_report_paths, Path) else batch_report_paths
    batch_reports = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    report_by_istat = {}
    for batch_report in batch_reports:
        report_by_istat.update({
            report["istat_code"]: report
            for report in batch_report["extraction"]["municipality_reports"]
        })
    municipalities = []
    all_records = []
    shared_waste_atos: set[str] = set()
    for istat_code, source in sorted(registry.items()):
        report = report_by_istat.get(istat_code)
        acquisition_path = next((
            directory / f"{source['source_slug']}-acquisition.jsonl"
            for directory in input_dirs
            if (directory / f"{source['source_slug']}-acquisition.jsonl").exists()
        ), input_dirs[0] / f"{source['source_slug']}-acquisition.jsonl")
        records = [
            json.loads(line)
            for line in acquisition_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ] if report and acquisition_path.exists() else []
        municipalities.append({
            "istat_code": istat_code,
            "name": source["name"],
            "slug": source["source_slug"],
            "ato_ref": source["ato_ref"],
            "ato_name": ATO_NAMES.get(source["ato_ref"], source["ato_ref"]),
            "province_code": source["province_code"],
            "province_name": PROVINCE_NAMES.get(source["province_code"], source["province_code"]),
            "operator_ref": source.get("operator_ref"),
            "local_operator_ref": source.get("local_operator_ref") or source.get("operator_ref"),
            "local_operator_name": source.get("local_operator_name") or "SEI Toscana",
            "local_operator_url": source.get("local_operator_url") or source.get("homepage_url"),
            "assignment_status": source.get("assignment_status") or "active",
            "assignment_note": source.get("assignment_note"),
            "acquisition_status": "acquired" if report else "registry_only",
            "records": len(records),
            "records_by_type": report["records_by_type"] if report else {},
            "pages_available": report["pages_available"] if report else 0,
            "pages_materialized": report["pages_materialized"] if report else 0,
            "warnings": report["warnings"] if report else [],
            "equivalent_pages": report["equivalent_pages"] if report else [],
        })
        local_records = records
        if source["ato_ref"] == "ato-toscana-centro":
            shared_waste = [record for record in records if record["record_type"] == "waste_lookup"]
            local_records = [record for record in records if record["record_type"] != "waste_lookup"]
            if source["ato_ref"] not in shared_waste_atos:
                all_records.extend({
                    **record,
                    "municipality_istat": istat_code,
                    "shared_ato_ref": source["ato_ref"],
                } for record in shared_waste)
                shared_waste_atos.add(source["ato_ref"])
        all_records.extend({**record, "municipality_istat": istat_code} for record in local_records)

    municipalities.sort(key=lambda item: item["name"])
    observed_at = max(report["observed_at"] for report in batch_reports)
    acquired_municipalities = sum(
        item["acquisition_status"] == "acquired" for item in municipalities
    )
    catalog = (
        json.loads(catalog_path.read_text(encoding="utf-8"))
        if catalog_path is not None else {"version": 2, "generated_at": generated_at.isoformat(), "eer_register": None, "concepts": []}
    )
    eer_register = (
        json.loads(eer_register_path.read_text(encoding="utf-8"))
        if eer_register_path is not None else {
            "version": 1,
            "register_id": None,
            "generated_at": generated_at.isoformat(),
            "valid_from": None,
            "status_at_generation": "unavailable",
            "sources": [],
            "changes": {"added_codes": [], "modified_codes": [], "retired_codes": []},
            "chapters": [],
            "subchapters": [],
            "entries": [],
            "retired_entries": [],
        }
    )
    return {
        "version": 1,
        "generated_at": generated_at.isoformat(),
        "batch": {
            "observed_at": observed_at,
            "pages_checked": sum(report["pages_checked"] for report in batch_reports),
            "pages_remaining": sum(report["pages_remaining"] for report in batch_reports),
            "records": sum(item["records"] for item in municipalities),
            "municipalities_registered": len(municipalities),
            "municipalities_acquired": acquired_municipalities,
            "warnings": sum(len(item["warnings"]) for item in municipalities),
            "errors": [error for report in batch_reports for error in report["errors"]],
        },
        "atos": [
            {
                "id": ato_ref,
                "name": ATO_NAMES.get(ato_ref, ato_ref),
                "provinces": sorted({
                    item["province_code"]
                    for item in municipalities
                    if item["ato_ref"] == ato_ref
                }),
            }
            for ato_ref in sorted({item["ato_ref"] for item in municipalities})
        ],
        "municipalities": municipalities,
        "records": all_records,
        "catalog": catalog,
        "eer_register": eer_register,
    }


def write_explorer_dataset(destination: Path, dataset: dict[str, Any]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "window.COMESIBUTTA_DATA = "
        + json.dumps(dataset, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the static data explorer bundle")
    parser.add_argument("--input-dir", type=Path, action="append", required=True)
    parser.add_argument("--batch-report", type=Path, action="append", required=True)
    parser.add_argument("--registry", type=Path, action="append", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--eer-register", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    dataset = build_explorer_dataset(
        args.input_dir,
        args.batch_report,
        args.registry,
        datetime.fromisoformat(args.generated_at),
        args.catalog,
        args.eer_register,
    )
    write_explorer_dataset(args.output, dataset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
