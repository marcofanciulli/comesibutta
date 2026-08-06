from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any


PROVINCE_NAMES = {
    "AR": "Arezzo",
    "GR": "Grosseto",
    "LI": "Livorno",
    "SI": "Siena",
}
ATO_NAMES = {"ato-toscana-sud": "ATO Toscana Sud"}


def build_explorer_dataset(
    input_dir: Path,
    batch_report_paths: Path | list[Path],
    registry_path: Path,
    generated_at: datetime,
) -> dict[str, Any]:
    registry = {}
    for line in registry_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)["payload"]
        registry[payload["istat_code"]] = payload

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
    for istat_code, report in sorted(report_by_istat.items()):
        source = registry[istat_code]
        acquisition_path = input_dir / f"{source['source_slug']}-acquisition.jsonl"
        records = [
            json.loads(line)
            for line in acquisition_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ] if acquisition_path.exists() else []
        municipalities.append({
            "istat_code": istat_code,
            "name": source["name"],
            "slug": source["source_slug"],
            "ato_ref": source["ato_ref"],
            "ato_name": ATO_NAMES.get(source["ato_ref"], source["ato_ref"]),
            "province_code": source["province_code"],
            "province_name": PROVINCE_NAMES.get(source["province_code"], source["province_code"]),
            "records": len(records),
            "records_by_type": report["records_by_type"],
            "pages_available": report["pages_available"],
            "pages_materialized": report["pages_materialized"],
            "warnings": report["warnings"],
            "equivalent_pages": report["equivalent_pages"],
        })
        all_records.extend({**record, "municipality_istat": istat_code} for record in records)

    municipalities.sort(key=lambda item: item["name"])
    observed_at = max(report["observed_at"] for report in batch_reports)
    return {
        "version": 1,
        "generated_at": generated_at.isoformat(),
        "batch": {
            "observed_at": observed_at,
            "pages_checked": sum(report["pages_checked"] for report in batch_reports),
            "pages_remaining": sum(report["pages_remaining"] for report in batch_reports),
            "records": len(all_records),
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
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--batch-report", type=Path, action="append", required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    dataset = build_explorer_dataset(
        args.input_dir,
        args.batch_report,
        args.registry,
        datetime.fromisoformat(args.generated_at),
    )
    write_explorer_dataset(args.output, dataset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
