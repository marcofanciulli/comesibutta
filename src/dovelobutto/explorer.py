from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any


def build_explorer_dataset(
    input_dir: Path,
    batch_report_path: Path,
    registry_path: Path,
    generated_at: datetime,
) -> dict[str, Any]:
    registry = {}
    for line in registry_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)["payload"]
        registry[payload["istat_code"]] = payload

    batch_report = json.loads(batch_report_path.read_text(encoding="utf-8"))
    report_by_istat = {
        report["istat_code"]: report
        for report in batch_report["extraction"]["municipality_reports"]
    }
    municipalities = []
    all_records = []
    for acquisition_path in sorted(input_dir.glob("*-acquisition.jsonl")):
        records = [
            json.loads(line)
            for line in acquisition_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not records:
            continue
        municipality_ref = next(
            record["payload"].get("municipality_ref")
            for record in records
            if record["payload"].get("municipality_ref")
        )
        istat_code = municipality_ref.removeprefix("istat:")
        source = registry[istat_code]
        report = report_by_istat[istat_code]
        municipalities.append({
            "istat_code": istat_code,
            "name": source["name"],
            "slug": source["source_slug"],
            "province_code": source["province_code"],
            "records": len(records),
            "records_by_type": report["records_by_type"],
            "pages_available": report["pages_available"],
            "pages_materialized": report["pages_materialized"],
            "warnings": report["warnings"],
            "equivalent_pages": report["equivalent_pages"],
        })
        all_records.extend({**record, "municipality_istat": istat_code} for record in records)

    municipalities.sort(key=lambda item: item["name"])
    return {
        "version": 1,
        "generated_at": generated_at.isoformat(),
        "batch": {
            "observed_at": batch_report["observed_at"],
            "pages_checked": batch_report["pages_checked"],
            "pages_remaining": batch_report["pages_remaining"],
            "records": len(all_records),
            "warnings": sum(len(item["warnings"]) for item in municipalities),
            "errors": batch_report["errors"],
        },
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
    parser.add_argument("--batch-report", type=Path, required=True)
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
