from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any


SPLIT_NAMES = ("train", "validation", "test")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unique(values: list[str], label: str) -> None:
    duplicates = sorted(value for value, count in Counter(values).items() if count > 1)
    if duplicates:
        raise ValueError(f"Duplicate {label}: {duplicates}")


def _validate_ranges(policy: dict[str, Any]) -> None:
    covered: dict[int, str] = {}
    for split in SPLIT_NAMES:
        start, end = policy[split]
        if start > end:
            raise ValueError(f"Invalid {split} split range: {start}-{end}")
        for bucket in range(start, end + 1):
            previous = covered.setdefault(bucket, split)
            if previous != split:
                raise ValueError(f"Split ranges overlap at bucket {bucket}")
    if set(covered) != set(range(100)):
        missing = sorted(set(range(100)) - set(covered))
        raise ValueError(f"Split ranges do not cover every bucket: {missing}")


def split_for_capture_group(capture_group_id: str, policy: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        f"{policy['seed']}\0{capture_group_id}".encode("utf-8")
    ).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    for split in SPLIT_NAMES:
        start, end = policy[split]
        if start <= bucket <= end:
            return split
    raise ValueError(f"No split configured for bucket {bucket}")


def validate_vision_corpus(
    manifest_path: Path,
    taxonomy_path: Path,
    assets_root: Path | None = None,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    taxonomy = _read_json(taxonomy_path)

    if manifest.get("version") != 1 or taxonomy.get("version") != 1:
        raise ValueError("Unsupported vision corpus or taxonomy version")
    taxonomy_ref = manifest["taxonomy"]
    if taxonomy_ref["taxonomy_id"] != taxonomy["taxonomy_id"]:
        raise ValueError("Manifest and taxonomy IDs differ")
    if taxonomy_ref["taxonomy_version"] != taxonomy["taxonomy_version"]:
        raise ValueError("Manifest and taxonomy versions differ")
    if taxonomy_ref["sha256"] != _sha256(taxonomy_path):
        raise ValueError("Manifest taxonomy SHA-256 does not match the taxonomy file")

    classes = taxonomy["classes"]
    category_ids = [item["category_id"] for item in classes]
    detector_indices = [item["detector_index"] for item in classes]
    _unique(category_ids, "taxonomy category ID")
    _unique([str(value) for value in detector_indices], "detector index")
    if sorted(detector_indices) != list(range(len(detector_indices))):
        raise ValueError("Detector indices must be contiguous and start at zero")

    policy = manifest["split_policy"]
    if policy.get("unit") != "capture_group" or policy.get("algorithm") != "sha256_mod_100":
        raise ValueError("Unsupported vision corpus split policy")
    _validate_ranges(policy)

    sources = manifest["sources"]
    assets = manifest["assets"]
    source_ids = [source["source_id"] for source in sources]
    _unique(source_ids, "source ID")
    source_by_id = {source["source_id"]: source for source in sources}
    _unique([asset["asset_id"] for asset in assets], "asset ID")
    _unique([asset["path"] for asset in assets], "asset path")
    _unique([asset["sha256"] for asset in assets], "asset SHA-256")
    _unique(
        [annotation["annotation_id"] for asset in assets for annotation in asset["annotations"]],
        "annotation ID",
    )

    split_counts = Counter()
    category_counts = Counter()
    origin_counts = Counter()
    errors: list[str] = []
    for source in sources:
        if source["personal_data_allowed"] is not False:
            errors.append(f"{source['source_id']}: personal data must not be allowed")
        if source["rights_basis"] == "open_license" and (
            not source["license_id"] or not source["license_url"]
        ):
            errors.append(
                f"{source['source_id']}: an open-license source needs license ID and URL"
            )
    for asset in assets:
        asset_id = asset["asset_id"]
        relative_path = Path(asset["path"])
        if relative_path.is_absolute() or ".." in relative_path.parts:
            errors.append(f"{asset_id}: asset path must stay below the assets root")
        source = source_by_id.get(asset["source_id"])
        if source is None:
            errors.append(f"{asset_id}: unknown source {asset['source_id']}")
        elif source["rights_review"] != "approved":
            errors.append(f"{asset_id}: source rights are not approved")
        if asset["privacy_review"] != "approved":
            errors.append(f"{asset_id}: privacy review is not approved")
        expected_split = split_for_capture_group(asset["capture_group_id"], policy)
        if asset["split"] != expected_split:
            errors.append(
                f"{asset_id}: split {asset['split']} does not match deterministic "
                f"capture-group split {expected_split}"
            )
        if asset["split"] == "test" and asset["content_origin"] != "real_photo":
            errors.append(f"{asset_id}: the test split accepts real photos only")
        split_counts[asset["split"]] += 1
        origin_counts[asset["content_origin"]] += 1
        if assets_root is not None:
            asset_path = assets_root / asset["path"]
            if not asset_path.is_file():
                errors.append(f"{asset_id}: asset file is missing")
            elif _sha256(asset_path) != asset["sha256"]:
                errors.append(f"{asset_id}: asset SHA-256 does not match")
        for annotation in asset["annotations"]:
            category_id = annotation["category_id"]
            if category_id not in category_ids:
                errors.append(
                    f"{asset_id}/{annotation['annotation_id']}: unknown category {category_id}"
                )
            box = annotation["bounding_box"]
            if not (0 <= box["x_min"] < box["x_max"] <= 1):
                errors.append(f"{asset_id}/{annotation['annotation_id']}: invalid horizontal box")
            if not (0 <= box["y_min"] < box["y_max"] <= 1):
                errors.append(f"{asset_id}/{annotation['annotation_id']}: invalid vertical box")
            if annotation["transcription_status"] == "exact" and not annotation["transcription"]:
                errors.append(
                    f"{asset_id}/{annotation['annotation_id']}: exact transcription is empty"
                )
            category_counts[category_id] += 1
    if errors:
        raise ValueError("Invalid vision corpus:\n- " + "\n- ".join(errors))

    return {
        "corpus_id": manifest["corpus_id"],
        "corpus_version": manifest["corpus_version"],
        "taxonomy_version": taxonomy["taxonomy_version"],
        "assets": len(assets),
        "annotations": sum(category_counts.values()),
        "capture_groups": len({asset["capture_group_id"] for asset in assets}),
        "sources": len(sources),
        "split_counts": {split: split_counts[split] for split in SPLIT_NAMES},
        "category_counts": dict(sorted(category_counts.items())),
        "content_origin_counts": dict(sorted(origin_counts.items())),
        "trainable": bool(assets) and bool(category_counts),
        "release_evaluation_ready": any(
            asset["split"] == "test"
            and asset["content_origin"] == "real_photo"
            and asset["annotations"]
            for asset in assets
        ),
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
