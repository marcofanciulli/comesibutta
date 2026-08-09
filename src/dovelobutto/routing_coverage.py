from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

from .catalog import normalize_term
from .curation import matching_collection_streams, matching_delivery_channels


def build_routing_coverage(
    catalog: dict[str, Any],
    curation: dict[str, Any],
    *,
    generated_at: datetime,
) -> dict[str, Any]:
    curated_eer: dict[str, list[dict[str, Any]]] = {}
    for mapping in curation.get("eer_mappings", []):
        for concept_id in mapping.get("concept_ids", []):
            curated_eer.setdefault(concept_id, []).append(mapping)
    curated_stream: dict[str, list[dict[str, Any]]] = {}
    for mapping in curation.get("stream_mappings", []):
        for concept_id in mapping.get("concept_ids", []):
            curated_stream.setdefault(concept_id, []).append(mapping)
    questions = {
        concept_id: group
        for group in curation.get("disambiguation_groups", [])
        for concept_id in group.get("trigger_concept_ids", [])
    }
    family_mapping_by_category = {
        category.strip(): mapping
        for mapping in curation.get("family_mappings", [])
        for category in mapping.get("source_categories", [])
    }
    family_mapping_by_destination = {
        normalize_term(destination): mapping
        for mapping in curation.get("family_mappings", [])
        for destination in mapping.get("destination_aliases", [])
    }
    classes_by_id = {
        waste_class["class_id"]: waste_class
        for waste_class in curation.get("waste_classes", [])
    }
    hazard_profiles = curation.get("hazard_material_profiles", [])
    hazardous_profile_codes = {
        code for profile in hazard_profiles
        for code in profile.get("hazardous_eer_codes", [])
    }

    def hazard_profiles_for(concept: dict[str, Any]) -> list[dict[str, Any]]:
        terms = [
            normalize_term(concept.get("preferred_label", "")),
            normalize_term(concept.get("normalized_term", "")),
            *(normalize_term(term) for term in concept.get("terms", [])),
        ]
        return [
            profile for profile in hazard_profiles
            if any(
                re.search(pattern, term)
                for pattern in profile.get("term_patterns", [])
                for term in terms
            )
            and not any(
                re.search(pattern, term)
                for pattern in profile.get("excluded_term_patterns", [])
                for term in terms
            )
        ]

    def class_is_hazard_compatible(waste_class: dict[str, Any]) -> bool:
        if waste_class.get("hazard_compatible"):
            return True
        routes = [
            waste_class,
            *((waste_class.get("question") or {}).get("options", [])),
        ]
        codes = [code for route in routes for code in route.get("eer_codes", [])]
        return bool(codes) and not any(
            route.get("stream_ids") for route in routes
        ) and all(code in hazardous_profile_codes for code in codes)

    concepts = [
        *catalog.get("concepts", []),
        *(
            _curated_concept_stub(concept)
            for concept in curation.get("curated_concepts", [])
        ),
    ]
    entries = []
    counts: Counter[str] = Counter()
    for concept in sorted(concepts, key=lambda item: item["concept_id"]):
        concept_id = concept["concept_id"]
        destinations = sorted({
            destination["label"]
            for destination in concept.get("local_destinations", [])
            if destination.get("label")
        })
        observed_streams = sorted({
            match["stream_id"]
            for destination in destinations
            for match in matching_collection_streams(
                destination, curation.get("collection_streams", []),
            )
        })
        observed_channels = sorted({
            match["channel_id"]
            for destination in destinations
            for match in matching_delivery_channels(
                destination, curation.get("delivery_channels", []),
            )
        })
        unmapped_destinations = sorted(
            destination for destination in destinations
            if not matching_collection_streams(
                destination, curation.get("collection_streams", []),
            )
            and not matching_delivery_channels(
                destination, curation.get("delivery_channels", []),
            )
            and normalize_term(destination) not in family_mapping_by_destination
        )
        source_eer = sorted({
            candidate["code"]
            for candidate in (concept.get("eer") or {}).get("candidates", [])
            if candidate.get("register_status") != "unknown_code"
        })
        reviewed_eer = sorted({
            mapping["eer_code"] for mapping in curated_eer.get(concept_id, [])
        })
        reviewed_streams = sorted({
            mapping["stream_id"] for mapping in curated_stream.get(concept_id, [])
        })
        matched_hazard_profiles = hazard_profiles_for(concept)
        hazard_restricted = bool(matched_hazard_profiles)
        if hazard_restricted:
            reviewed_eer = [
                code for code in reviewed_eer if code in hazardous_profile_codes
            ]
            source_eer = [
                code for code in source_eer if code in hazardous_profile_codes
            ]
            reviewed_streams = []
        safe_observed_channels = observed_channels if hazard_restricted else []
        has_question = concept_id in questions
        source_categories = sorted(set(concept.get("source_categories", [])))
        matched_family_mappings = [
            *(
                family_mapping_by_category[category.strip()]
                for category in source_categories
                if category.strip() in family_mapping_by_category
            ),
            *(
                family_mapping_by_destination[normalize_term(destination)]
                for destination in destinations
                if normalize_term(destination) in family_mapping_by_destination
            ),
            *(
                mapping
                for mapping in curation.get("family_mappings", [])
                if any(
                    re.search(pattern, concept.get("normalized_term", ""))
                    for pattern in mapping.get("term_patterns", [])
                )
                and not any(
                    re.search(pattern, concept.get("normalized_term", ""))
                    for pattern in mapping.get("excluded_term_patterns", [])
                )
            ),
        ]
        mappings_by_dimension: dict[str, list[dict[str, Any]]] = {}
        for mapping in matched_family_mappings:
            waste_class = classes_by_id[mapping["class_id"]]
            dimension = waste_class.get("dimension", waste_class["class_id"])
            mappings_by_dimension.setdefault(dimension, []).append(mapping)
        selected_family_mappings = []
        family_dimension_conflict = False
        for dimension_mappings in mappings_by_dimension.values():
            maximum_priority = max(
                mapping.get("priority", 0) for mapping in dimension_mappings
            )
            winners = {
                mapping["class_id"]: mapping for mapping in dimension_mappings
                if mapping.get("priority", 0) == maximum_priority
            }
            if len(winners) > 1:
                family_dimension_conflict = True
            selected_family_mappings.extend(
                mapping for mapping in winners.values()
                if not hazard_restricted
                or class_is_hazard_compatible(classes_by_id[mapping["class_id"]])
            )
        family_class_ids = sorted({
            mapping["class_id"] for mapping in selected_family_mappings
        })
        family_question_count = sum(
            bool(classes_by_id[class_id].get("question"))
            for class_id in family_class_ids
        )
        has_family_question = family_question_count == 1
        conflicts = []
        if (
            len(source_eer) > 1 and not has_question and not has_family_question
            and not reviewed_eer
        ):
            conflicts.append("multiple_source_eer_codes")
        if family_dimension_conflict or family_question_count > 1:
            conflicts.append("multiple_family_classes")

        portable_classification = bool(
            has_question or reviewed_eer or reviewed_streams
            or source_eer or family_class_ids or safe_observed_channels
            or hazard_restricted
        )
        if conflicts:
            status = "conflict"
        elif not portable_classification:
            status = "unclassified"
        elif unmapped_destinations:
            status = "partially_classified"
        else:
            status = "classified"
        counts[status] += 1
        entries.append({
            "concept_id": concept_id,
            "preferred_label": concept.get("preferred_label"),
            "terms": sorted(set(concept.get("terms", []))),
            "status": status,
            "question_id": questions.get(concept_id, {}).get("group_id"),
            "source_categories": source_categories,
            "family_class_ids": family_class_ids,
            "reviewed_stream_ids": reviewed_streams,
            "observed_stream_ids": observed_streams,
            "reviewed_eer_codes": reviewed_eer,
            "source_eer_codes": source_eer,
            "portable_classification": portable_classification,
            "local_route_observed": bool(observed_streams or observed_channels),
            "observed_channel_ids": observed_channels,
            "observed_destinations": destinations,
            "unmapped_destinations": unmapped_destinations,
            "source_urls": sorted({
                evidence["source_url"]
                for evidence in concept.get("evidence", [])
                if evidence.get("source_url")
            }),
            "conflicts": conflicts,
            "hazard_profile_ids": sorted(
                profile["profile_id"] for profile in matched_hazard_profiles
            ),
            "hazard_status": (
                "separate_handling_required" if hazard_restricted else None
            ),
            "suppressed_observed_stream_ids": (
                observed_streams if hazard_restricted else []
            ),
        })

    alias_entries = []
    for group in sorted(
        curation.get("alias_groups", []), key=lambda item: item["group_id"],
    ):
        class_id = group.get("waste_class_id")
        waste_class = classes_by_id.get(class_id)
        complete = bool(waste_class) and _class_has_complete_routes(waste_class)
        alias_entries.append({
            "group_id": group["group_id"],
            "preferred_label": group.get("preferred_label"),
            "member_concept_ids": group.get("member_concept_ids", []),
            "waste_class_id": class_id,
            "status": "classified" if complete else "unclassified",
            "portable_classification": complete,
        })

    incomplete = [entry for entry in entries if entry["status"] != "classified"]
    incomplete_aliases = [
        entry for entry in alias_entries if entry["status"] != "classified"
    ]
    release_ready = not incomplete and not incomplete_aliases
    return {
        "report_id": "waste-routing-coverage:toscana",
        "version": 1,
        "generated_at": generated_at.isoformat(),
        "catalog_generated_at": catalog["generated_at"],
        "curation_generated_at": curation["generated_at"],
        "summary": {
            "status": "pass" if release_ready else "fail",
            "release_ready": release_ready,
            "concepts": len(entries),
            "classified": counts["classified"],
            "partially_classified": counts["partially_classified"],
            "conflicts": counts["conflict"],
            "unclassified": counts["unclassified"],
            "incomplete": len(incomplete) + len(incomplete_aliases),
            "alias_groups": len(alias_entries),
            "classified_alias_groups": len(alias_entries) - len(incomplete_aliases),
            "incomplete_alias_groups": len(incomplete_aliases),
        },
        "entries": entries,
        "alias_entries": alias_entries,
        "review_queue": [*incomplete, *incomplete_aliases],
    }


def _class_has_complete_routes(waste_class: dict[str, Any]) -> bool:
    question = waste_class.get("question")
    routes = question.get("options", []) if question else [waste_class]
    return bool(routes) and all(
        route.get("stream_ids")
        or route.get("eer_codes")
        or route.get("delivery_channels")
        for route in routes
    )


def _curated_concept_stub(concept: dict[str, Any]) -> dict[str, Any]:
    return {
        "concept_id": concept["concept_id"],
        "preferred_label": concept["preferred_label"],
        "normalized_term": normalize_term(concept["preferred_label"]),
        "terms": [concept["preferred_label"], *concept.get("search_terms", [])],
        "eer": {"candidates": []},
        "local_destinations": [],
    }


def build_routing_coverage_paths(
    catalog_path: Path,
    curation_path: Path,
    *,
    generated_at: datetime,
) -> dict[str, Any]:
    return build_routing_coverage(
        json.loads(catalog_path.read_text(encoding="utf-8")),
        json.loads(curation_path.read_text(encoding="utf-8")),
        generated_at=generated_at,
    )


def write_routing_coverage(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
