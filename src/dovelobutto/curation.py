from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from typing import Any

from .catalog import normalize_term


_EER_CODE_RE = re.compile(r"^\d{6}$")


def matching_delivery_channels(
    value: str,
    channels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized = normalize_term(value)
    matches = []
    for channel in channels:
        aliases = sorted(
            {
                alias for alias in channel.get("aliases", [])
                if normalize_term(alias) and _contains_phrase(normalized, normalize_term(alias))
            },
            key=lambda item: (-len(normalize_term(item)), item.casefold()),
        )
        if aliases:
            matches.append({
                "channel_id": channel["channel_id"],
                "preferred_label": channel["preferred_label"],
                "destination_type": channel["destination_type"],
                "matched_aliases": aliases,
            })
    return matches


def _contains_phrase(value: str, phrase: str) -> bool:
    return f" {phrase} " in f" {value} "


def validate_waste_curation(
    register: dict[str, Any],
    catalog: dict[str, Any],
) -> dict[str, Any]:
    catalog_concept_ids = {
        concept["concept_id"] for concept in catalog.get("concepts", [])
    }
    curated_concept_ids = set()
    curated_search_terms = set()
    for concept in register.get("curated_concepts", []):
        concept_id = concept["concept_id"]
        if concept_id in catalog_concept_ids:
            raise ValueError(f"Curated concept {concept_id} already exists in the catalog")
        if concept_id in curated_concept_ids:
            raise ValueError(f"Duplicate curated concept {concept_id}")
        if concept.get("review_status") != "approved":
            raise ValueError(f"Curated concept {concept_id} is not approved")
        if not concept.get("search_terms"):
            raise ValueError(f"Curated concept {concept_id} requires search terms")
        curated_concept_ids.add(concept_id)
        for term in concept["search_terms"]:
            normalized = normalize_term(term)
            if not normalized:
                raise ValueError(f"Empty search term in {concept_id}")
            curated_search_terms.add(normalized)
    concept_ids = catalog_concept_ids | curated_concept_ids
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

    mapping_ids = set()
    mapped_concepts: dict[str, list[dict[str, str]]] = defaultdict(list)
    for mapping in register.get("eer_mappings", []):
        mapping_id = mapping["mapping_id"]
        if mapping_id in mapping_ids:
            raise ValueError(f"Duplicate EER mapping {mapping_id}")
        mapping_ids.add(mapping_id)
        if mapping.get("review_status") != "approved":
            raise ValueError(f"EER mapping {mapping_id} is not approved")
        if not _EER_CODE_RE.fullmatch(str(mapping.get("eer_code", ""))):
            raise ValueError(f"Invalid EER code in {mapping_id}")
        for concept_id in mapping.get("concept_ids", []):
            if concept_id not in concept_ids:
                raise ValueError(f"Unknown concept {concept_id} in {mapping_id}")
            previous = mapped_concepts[concept_id]
            condition = normalize_term(mapping.get("condition", ""))
            if previous and not condition:
                raise ValueError(
                    f"Concept {concept_id} requires a condition in {mapping_id} "
                    "because it has multiple EER mappings"
                )
            if any(not item["condition"] for item in previous):
                raise ValueError(
                    f"Concept {concept_id} already has an unconditional EER mapping"
                )
            if any(
                item["code"] == mapping["eer_code"] or item["condition"] == condition
                for item in previous
            ):
                raise ValueError(
                    f"Concept {concept_id} repeats an EER code or condition in {mapping_id}"
                )
            previous.append({
                "mapping_id": mapping_id,
                "code": mapping["eer_code"],
                "condition": condition,
            })

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

    stream_mapping_ids = set()
    stream_mapped_concepts = set()
    for mapping in register.get("stream_mappings", []):
        mapping_id = mapping["mapping_id"]
        if mapping_id in stream_mapping_ids:
            raise ValueError(f"Duplicate stream mapping {mapping_id}")
        stream_mapping_ids.add(mapping_id)
        if mapping.get("review_status") != "approved":
            raise ValueError(f"Stream mapping {mapping_id} is not approved")
        if mapping.get("stream_id") not in stream_ids:
            raise ValueError(f"Unknown stream {mapping.get('stream_id')} in {mapping_id}")
        for concept_id in mapping.get("concept_ids", []):
            if concept_id not in concept_ids:
                raise ValueError(f"Unknown concept {concept_id} in {mapping_id}")
            if concept_id in stream_mapped_concepts:
                raise ValueError(f"Concept {concept_id} has multiple stream mappings")
            stream_mapped_concepts.add(concept_id)

    disambiguation_ids = set()
    disambiguation_triggers = set()
    for group in register.get("disambiguation_groups", []):
        group_id = group["group_id"]
        if group_id in disambiguation_ids:
            raise ValueError(f"Duplicate disambiguation group {group_id}")
        disambiguation_ids.add(group_id)
        if group.get("review_status") != "approved":
            raise ValueError(f"Disambiguation group {group_id} is not approved")
        option_ids = [option["concept_id"] for option in group.get("options", [])]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError(f"Duplicate options in {group_id}")
        for concept_id in [*group.get("trigger_concept_ids", []), *option_ids]:
            if concept_id not in concept_ids:
                raise ValueError(f"Unknown concept {concept_id} in {group_id}")
        for concept_id in group.get("trigger_concept_ids", []):
            if concept_id in disambiguation_triggers:
                raise ValueError(f"Concept {concept_id} triggers multiple questions")
            disambiguation_triggers.add(concept_id)

    channel_ids = set()
    channel_alias_owner: dict[str, str] = {}
    channels = register.get("delivery_channels", [])
    for channel in channels:
        channel_id = channel["channel_id"]
        if channel_id in channel_ids:
            raise ValueError(f"Duplicate delivery channel {channel_id}")
        channel_ids.add(channel_id)
        for alias in channel.get("aliases", []):
            normalized = normalize_term(alias)
            if not normalized:
                raise ValueError(f"Empty alias in {channel_id}")
            if (
                normalized in channel_alias_owner
                and channel_alias_owner[normalized] != channel_id
            ):
                raise ValueError(
                    f"Channel alias {alias!r} belongs to both "
                    f"{channel_alias_owner[normalized]} and {channel_id}"
                )
            channel_alias_owner[normalized] = channel_id

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
    channel_label_counts = Counter()
    channel_assertion_counts = Counter()
    multi_channel_labels = 0
    multi_channel_assertions = 0
    unresolved = []
    channel_matches_by_label = {
        label: matching_delivery_channels(label, channels)
        for label in destination_counts
    }
    for label, count in destination_counts.items():
        matches = channel_matches_by_label[label]
        if matches:
            channel_ids_for_label = [match["channel_id"] for match in matches]
            channel_label_counts.update(channel_ids_for_label)
            channel_assertion_counts.update({
                channel_id: count for channel_id in channel_ids_for_label
            })
            if len(matches) > 1:
                multi_channel_labels += 1
                multi_channel_assertions += count
        if label not in alias_owner and not matches:
            unresolved.append({"label": label, "assertions": count})
    channel_mapped_labels = sum(map(bool, channel_matches_by_label.values()))
    channel_mapped_assertions = sum(
        count for label, count in destination_counts.items()
        if channel_matches_by_label[label]
    )
    return {
        "register_id": register["register_id"],
        "register_version": register["version"],
        "catalog_generated_at": catalog["generated_at"],
        "curated_concepts": len(curated_concept_ids),
        "curated_search_terms": len(curated_search_terms),
        "alias_groups": len(group_ids),
        "alias_members": len(member_owner),
        "approved_search_terms": len(search_owner),
        "eer_mappings": len(mapping_ids),
        "eer_mapped_concepts": len(mapped_concepts),
        "stream_mappings": len(stream_mapping_ids),
        "stream_mapped_concepts": len(stream_mapped_concepts),
        "disambiguation_groups": len(disambiguation_ids),
        "disambiguation_triggers": len(disambiguation_triggers),
        "collection_streams": len(stream_ids),
        "stream_aliases": len(alias_owner),
        "delivery_channels": len(channel_ids),
        "channel_aliases": len(channel_alias_owner),
        "destination_labels": len(destination_counts),
        "destination_assertions": sum(destination_counts.values()),
        "mapped_destination_labels": sum(label in alias_owner for label in destination_counts),
        "mapped_destination_assertions": mapped_assertions,
        "channel_mapped_destination_labels": channel_mapped_labels,
        "channel_mapped_destination_assertions": channel_mapped_assertions,
        "multi_channel_destination_labels": multi_channel_labels,
        "multi_channel_destination_assertions": multi_channel_assertions,
        "channel_destination_labels": dict(sorted(channel_label_counts.items())),
        "channel_destination_assertions": dict(sorted(channel_assertion_counts.items())),
        "alias_group_territorial_conflicts": sum(map(len, conflicts.values())),
        "conflicts_by_group": dict(conflicts),
        "top_unmapped_destinations": unmapped[:50],
        "top_destinations_without_stream_or_channel": sorted(
            unresolved, key=lambda item: (-item["assertions"], item["label"])
        )[:50],
    }


def validate_waste_curation_paths(
    register_path: Path,
    catalog_path: Path,
) -> dict[str, Any]:
    register = json.loads(register_path.read_text(encoding="utf-8"))
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    return validate_waste_curation(register, catalog)
