from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

from .catalog import normalize_term


def validate_waste_curation(
    register: dict[str, Any],
    catalog: dict[str, Any],
) -> dict[str, Any]:
    concept_ids = {concept["concept_id"] for concept in catalog.get("concepts", [])}
    group_ids = set()
    member_owner: dict[str, str] = {}
    search_owner: dict[str, str] = {}
    for group in register.get("alias_groups", []):
        group_id = group["group_id"]
        if group_id in group_ids:
            raise ValueError(f"Duplicate alias group {group_id}")
        group_ids.add(group_id)
        if group.get("review_status") != "approved":
            raise ValueError(f"Alias group {group_id} is not approved")
        if len(group.get("member_concept_ids", [])) < 2:
            raise ValueError(f"Alias group {group_id} requires at least two members")
        if not group.get("search_terms"):
            raise ValueError(f"Alias group {group_id} requires search terms")
        for term in group["search_terms"]:
            normalized = normalize_term(term)
            if normalized in search_owner and search_owner[normalized] != group_id:
                raise ValueError(
                    f"Search term {term!r} belongs to both {search_owner[normalized]} and {group_id}"
                )
            search_owner[normalized] = group_id
        for concept_id in group["member_concept_ids"]:
            if concept_id not in concept_ids:
                raise ValueError(f"Unknown concept {concept_id} in {group_id}")
            if concept_id in member_owner:
                raise ValueError(
                    f"Concept {concept_id} belongs to both {member_owner[concept_id]} and {group_id}"
                )
            member_owner[concept_id] = group_id

    stream_ids = set()
    alias_owner: dict[str, str] = {}
    for stream in register.get("collection_streams", []):
        stream_id = stream["stream_id"]
        if stream_id in stream_ids:
            raise ValueError(f"Duplicate collection stream {stream_id}")
        stream_ids.add(stream_id)
        for alias in stream.get("aliases", []):
            normalized = normalize_term(alias)
            if not normalized:
                raise ValueError(f"Empty alias in {stream_id}")
            if normalized in alias_owner and alias_owner[normalized] != stream_id:
                raise ValueError(
                    f"Stream alias {alias!r} belongs to both {alias_owner[normalized]} and {stream_id}"
                )
            alias_owner[normalized] = stream_id

    destination_counts = Counter(
        normalize_term(destination["label"])
        for concept in catalog.get("concepts", [])
        for destination in concept.get("local_destinations", [])
        if normalize_term(destination["label"])
    )
    mapped_assertions = sum(
        count for label, count in destination_counts.items() if label in alias_owner
    )
    conflicts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    concepts = {concept["concept_id"]: concept for concept in catalog.get("concepts", [])}
    for group in register.get("alias_groups", []):
        by_municipality: dict[str, set[str]] = defaultdict(set)
        for concept_id in group["member_concept_ids"]:
            for destination in concepts[concept_id].get("local_destinations", []):
                for municipality in destination["municipality_istats"]:
                    by_municipality[municipality].add(normalize_term(destination["label"]))
        for municipality, destinations in sorted(by_municipality.items()):
            canonical = {alias_owner.get(destination, destination) for destination in destinations}
            if len(canonical) > 1:
                conflicts[group["group_id"]].append({
                    "municipality_istat": municipality,
                    "destinations": sorted(destinations),
                    "canonical_destinations": sorted(canonical),
                })

    unmapped = [
        {"label": label, "assertions": count}
        for label, count in destination_counts.most_common()
        if label not in alias_owner
    ]
    return {
        "register_id": register["register_id"],
        "register_version": register["version"],
        "catalog_generated_at": catalog["generated_at"],
        "alias_groups": len(group_ids),
        "alias_members": len(member_owner),
        "approved_search_terms": len(search_owner),
        "collection_streams": len(stream_ids),
        "stream_aliases": len(alias_owner),
        "destination_labels": len(destination_counts),
        "destination_assertions": sum(destination_counts.values()),
        "mapped_destination_labels": sum(label in alias_owner for label in destination_counts),
        "mapped_destination_assertions": mapped_assertions,
        "alias_group_territorial_conflicts": sum(map(len, conflicts.values())),
        "conflicts_by_group": dict(conflicts),
        "top_unmapped_destinations": unmapped[:50],
    }


def validate_waste_curation_paths(
    register_path: Path,
    catalog_path: Path,
) -> dict[str, Any]:
    register = json.loads(register_path.read_text(encoding="utf-8"))
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    return validate_waste_curation(register, catalog)
