from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from time import monotonic
from typing import Any

from .app_query import DisposalQueryService, _similarity, open_query_database
from .catalog import normalize_term
from .destination_quality import DestinationQualityAudit
from .sync import read_entity_data


_STOPWORDS = {
    "a", "al", "alla", "con", "da", "dal", "dalla", "de", "dei", "del",
    "della", "di", "e", "in", "il", "la", "le", "lo", "per", "un", "una",
}


def _entity_ids(connection: sqlite3.Connection, entity_type: str) -> list[str]:
    return [
        row["entity_id"]
        for row in connection.execute(
            "SELECT entity_id FROM entities WHERE entity_type = ? ORDER BY entity_id",
            (entity_type,),
        )
    ]


def _municipality_coverage(concept: dict[str, Any]) -> set[str]:
    return {
        municipality
        for destination in concept.get("local_destinations", [])
        for municipality in destination.get("municipality_istats", [])
    }


def _territorial_cases(
    municipalities: set[str], zones_by_municipality: dict[str, list[str]],
) -> int:
    return sum(max(1, len(zones_by_municipality.get(code, []))) for code in municipalities)


def _zones_for(
    municipality: str, zones_by_municipality: dict[str, list[str]],
) -> list[str | None]:
    return zones_by_municipality.get(municipality) or [None]


def _term_anchor(term: str) -> str | None:
    tokens = [token for token in normalize_term(term).split() if token not in _STOPWORDS]
    return tokens[0][:4] if tokens else None


def _near_duplicate_candidates(
    concepts: dict[str, dict[str, Any]],
    membership: dict[str, str],
    service: DisposalQueryService,
    *,
    threshold: float,
) -> list[dict[str, Any]]:
    buckets: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for concept_id, concept in concepts.items():
        anchor = _term_anchor(concept.get("preferred_label", ""))
        if anchor:
            buckets[anchor].append((concept_id, concept["preferred_label"]))
    candidates = []
    seen: set[tuple[str, str]] = set()
    for entries in buckets.values():
        for index, (left_id, left_label) in enumerate(entries):
            for right_id, right_label in entries[index + 1:]:
                pair = tuple(sorted((left_id, right_id)))
                if pair in seen or membership.get(left_id, left_id) == membership.get(right_id, right_id):
                    continue
                seen.add(pair)
                score = _similarity(normalize_term(left_label), normalize_term(right_label))
                if score < threshold:
                    continue
                left_coverage = _municipality_coverage(concepts[left_id])
                right_coverage = _municipality_coverage(concepts[right_id])
                if left_coverage == right_coverage:
                    continue
                left_signature = _portable_route_signature(service, left_id)
                right_signature = _portable_route_signature(service, right_id)
                route_equivalent = bool(left_signature) and left_signature == right_signature
                candidates.append({
                    "left": {"concept_id": left_id, "label": left_label},
                    "right": {"concept_id": right_id, "label": right_label},
                    "similarity": score,
                    "coverage": {
                        "left_municipalities": len(left_coverage),
                        "right_municipalities": len(right_coverage),
                        "symmetric_difference": len(left_coverage ^ right_coverage),
                    },
                    "portable_routes": {
                        "equivalent": route_equivalent,
                        "left": left_signature,
                        "right": right_signature,
                    },
                    "decision": (
                        "equivalent_portable_route"
                        if route_equivalent
                        else "manual_review_required"
                        if score == 1.0
                        else "lexical_similarity_only"
                    ),
                    "review_reason": "Termini molto simili con copertura territoriale diversa",
                })
    return sorted(
        candidates,
        key=lambda item: (-item["similarity"], item["left"]["label"].casefold()),
    )


def _portable_route_signature(
    service: DisposalQueryService, concept_id: str,
) -> dict[str, Any]:
    concept = service._concept_for_choice(concept_id) or {}
    disambiguation = service.disambiguations.get(concept_id)
    family_class_ids = sorted(concept.get("family_class_ids", []))
    signature = {
        "family_class_ids": family_class_ids,
        "question_id": (disambiguation or {}).get("group_id"),
    }
    if family_class_ids:
        return signature
    return {
        **signature,
        "family_stream_ids": sorted(concept.get("family_stream_ids", [])),
        "family_delivery_channel_ids": sorted(
            concept.get("family_delivery_channel_ids", [])
        ),
        "eer_codes": sorted({
            candidate["code"]
            for candidate in concept.get("eer", {}).get("candidates", [])
            if candidate.get("register_status") != "unknown_code"
        }),
    }


def audit_query_coverage(
    connection: sqlite3.Connection,
    *,
    generated_at: datetime,
    similarity_threshold: float = 0.94,
) -> dict[str, Any]:
    audit_started = monotonic()
    metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    municipality_ids = _entity_ids(connection, "municipality")
    municipalities = {item.removeprefix("istat:") for item in municipality_ids}
    municipality_metadata = {}
    for municipality_id in municipality_ids:
        municipality = read_entity_data(
            connection, "municipality", municipality_id, include_sources=False,
        ) or {}
        payload = municipality.get("payload") or municipality
        municipality_metadata[municipality_id.removeprefix("istat:")] = {
            "name": payload.get("name") or payload.get("municipality_name"),
            "province_code": (
                payload.get("province_code")
                or payload.get("province_abbreviation")
            ),
            "ato_ref": payload.get("ato_ref") or payload.get("ato_name"),
        }
    zones_by_municipality: dict[str, list[str]] = defaultdict(list)
    failures: list[dict[str, Any]] = []

    for zone_id in _entity_ids(connection, "service_zone"):
        zone = read_entity_data(connection, "service_zone", zone_id, include_sources=False) or {}
        municipality_ref = (zone.get("payload") or {}).get("municipality_ref")
        municipality = (municipality_ref or "").removeprefix("istat:")
        if municipality not in municipalities:
            failures.append({
                "code": "zone_unknown_municipality",
                "entity_id": zone_id,
                "municipality_ref": municipality_ref,
            })
        else:
            zones_by_municipality[municipality].append(zone_id)

    service = DisposalQueryService(connection)
    destination_quality = DestinationQualityAudit(service, municipality_metadata)
    contexts = [
        (municipality, zone_id)
        for municipality in sorted(municipalities)
        for zone_id in _zones_for(municipality, zones_by_municipality)
    ]
    zone_ids = {
        zone_id for _, zone_id in contexts if zone_id is not None
    }
    concepts: dict[str, dict[str, Any]] = {}
    covered_concepts = 0
    term_bindings = 0
    runtime_statuses: dict[str, int] = defaultdict(int)
    evidence_contexts: dict[str, int] = defaultdict(int)
    failure_counts: dict[str, int] = defaultdict(int)
    failure_groups: dict[tuple[str, str | None, str | None], dict[str, Any]] = {}
    defined_groups: dict[tuple[Any, ...], dict[str, Any]] = {}

    def add_failure(code: str, **detail: Any) -> None:
        failure_counts[code] += 1
        key = (code, detail.get("entity_type"), detail.get("entity_id"))
        aggregate = failure_groups.setdefault(key, {
            "code": code,
            "entity_type": detail.get("entity_type"),
            "entity_id": detail.get("entity_id"),
            "cases": 0,
            "examples": [],
        })
        aggregate["cases"] += 1
        if len(aggregate["examples"]) < 3:
            aggregate["examples"].append({
                field: detail.get(field)
                for field in ("municipality_istat", "zone_id", "question")
                if detail.get(field) is not None
            })
        if len(failures) < 1000:
            failures.append({"code": code, **detail})

    def record_answer(
        answer: dict[str, Any], *, entity_type: str, entity_id: str,
        label: str | None, municipality: str, zone_id: str | None,
        has_territorial_evidence: bool,
    ) -> None:
        status = answer["status"]
        runtime_statuses[status] += 1
        evidence_contexts[
            "with_territorial_evidence"
            if has_territorial_evidence else "without_territorial_evidence"
        ] += 1
        if status == "resolved":
            result = answer.get("result")
            if result is None:
                add_failure(
                    "resolved_without_result", entity_type=entity_type,
                    entity_id=entity_id, municipality_istat=municipality,
                    zone_id=zone_id,
                )
            if not (answer.get("provenance") or {}).get("sources"):
                add_failure(
                    "resolved_without_provenance", entity_type=entity_type,
                    entity_id=entity_id, municipality_istat=municipality,
                    zone_id=zone_id,
                )
            if result and result.get("destination_type") == "portable_route":
                invented_fields = [
                    field for field in (
                        "container", "presentation", "facility", "channel_services",
                    )
                    if result.get(field)
                ]
                if result.get("local_route_status") != "not_published" or invented_fields:
                    add_failure(
                        "portable_route_invents_local_detail", entity_type=entity_type,
                        entity_id=entity_id, municipality_istat=municipality,
                        zone_id=zone_id, fields=invented_fields,
                    )
            matched_id = (answer.get("query") or {}).get("matched_concept_id")
            matched_concept = (
                service._concept_for_choice(matched_id) if matched_id else None
            )
            if (
                result
                and matched_concept
                and service._hazard_requires_separate_handling(matched_concept)
            ):
                ordinary_fields = [
                    field for field in ("stream_id", "stream", "container", "presentation")
                    if result.get(field)
                ]
                eer_options = [
                    item for item in [
                        result.get("eer"),
                        *(result.get("eer_alternatives") or []),
                    ]
                    if item is not None
                ]
                non_hazardous_codes = [
                    item.get("code") for item in eer_options
                    if not item.get("hazardous")
                ]
                if (
                    result.get("hazard_status") != "separate_handling_required"
                    or ordinary_fields
                    or non_hazardous_codes
                ):
                    add_failure(
                        "hazardous_material_in_non_hazardous_route",
                        entity_type=entity_type,
                        entity_id=entity_id,
                        municipality_istat=municipality,
                        zone_id=zone_id,
                        fields=ordinary_fields,
                        eer_codes=non_hazardous_codes,
                    )
            matched_id = (answer.get("query") or {}).get("matched_concept_id")
            matched_concept = (
                service._concept_for_choice(matched_id) if matched_id else None
            )
            destination_quality.observe(
                answer,
                concept=matched_concept,
                concept_id=matched_id or entity_id,
                label=label,
                municipality=municipality,
                zone_id=zone_id,
            )
            return
        if status == "needs_question":
            question = answer.get("question") or {}
            options = question.get("options") or []
            valid_ids = {
                *concepts.keys(), *service.alias_groups.keys(),
                *service.class_outcomes.keys(), *zone_ids,
            }
            if not options or any(option.get("id") not in valid_ids for option in options):
                add_failure(
                    "question_without_complete_options", entity_type=entity_type,
                    entity_id=entity_id, municipality_istat=municipality,
                    zone_id=zone_id, question=question,
                )
                return
            key = (
                status, entity_type, entity_id, question.get("text"),
                tuple(option.get("id") for option in options),
            )
            aggregate = defined_groups.setdefault(key, {
                "status": status,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "label": label,
                "question": question,
                "cases": 0,
                "examples": [],
            })
            aggregate["cases"] += 1
            if len(aggregate["examples"]) < 3:
                aggregate["examples"].append({
                    "municipality_istat": municipality, "zone_id": zone_id,
                })
            return
        add_failure(
            f"answer_{status}", entity_type=entity_type, entity_id=entity_id,
            municipality_istat=municipality, zone_id=zone_id,
            question=answer.get("question"),
        )

    for concept_id in _entity_ids(connection, "waste_concept"):
        concept = read_entity_data(
            connection, "waste_concept", concept_id, include_sources=False,
        ) or {}
        concepts[concept_id] = concept
    for concept_id, concept in concepts.items():
        coverage = _municipality_coverage(concept)
        if coverage:
            covered_concepts += 1
        term_bindings += len({
            normalize_term(term)
            for term in [concept.get("preferred_label"), *(concept.get("terms") or [])]
            if isinstance(term, str) and normalize_term(term)
        })
        for municipality in sorted(coverage - municipalities):
            add_failure(
                "concept_unknown_municipality", entity_id=concept_id,
                municipality_istat=municipality,
            )
        if not concept.get("preferred_label"):
            add_failure("concept_missing_label", entity_id=concept_id)
        for municipality, zone_id in contexts:
            answer = service.answer(
                concept.get("preferred_label", concept_id), municipality,
                concept_id=concept_id, zone_id=zone_id,
            )
            record_answer(
                answer, entity_type="waste_concept", entity_id=concept_id,
                label=concept.get("preferred_label"), municipality=municipality,
                zone_id=zone_id, has_territorial_evidence=municipality in coverage,
            )

    alias_term_cases = 0
    alias_runtime_checks = 0
    membership: dict[str, str] = {}
    for group_id, group in service.alias_groups.items():
        members = group.get("member_concept_ids", [])
        for concept_id in sorted(set(members) - concepts.keys()):
            add_failure(
                "alias_unknown_member", entity_id=group_id,
                member_concept_id=concept_id,
            )
        for concept_id in members:
            membership[concept_id] = group_id
        choice = service._concept_for_choice(group_id) or {}
        coverage = _municipality_coverage(choice)
        for municipality, zone_id in contexts:
            answer = service.answer(
                group.get("preferred_label", group_id), municipality,
                concept_id=group_id, zone_id=zone_id,
            )
            record_answer(
                answer, entity_type="waste_alias_group", entity_id=group_id,
                label=group.get("preferred_label"), municipality=municipality,
                zone_id=zone_id, has_territorial_evidence=municipality in coverage,
            )
        search_terms = {
            normalize_term(term) for term in group.get("search_terms", [])
            if isinstance(term, str) and normalize_term(term)
        }
        alias_term_cases += len(search_terms) * len(contexts)
        for term in search_terms:
            results = service.search(term, limit=1)
            alias_runtime_checks += 1
            if not results or results[0]["concept_id"] != group_id or results[0]["score"] != 1.0:
                add_failure(
                    "alias_exact_search_not_owned", entity_id=group_id,
                    term=term, first_result=results[0] if results else None,
                )

    for outcome_id, (_, outcome) in service.class_outcomes.items():
        for municipality, zone_id in contexts:
            answer = service.answer(
                outcome["label"], municipality,
                concept_id=outcome_id, zone_id=zone_id,
            )
            record_answer(
                answer, entity_type="waste_class_outcome", entity_id=outcome_id,
                label=outcome.get("label"), municipality=municipality,
                zone_id=zone_id, has_territorial_evidence=False,
            )

    candidates = _near_duplicate_candidates(
        concepts, membership, service, threshold=similarity_threshold,
    )
    equivalent_candidates = [
        item for item in candidates if item["decision"] == "equivalent_portable_route"
    ]
    lexical_candidates = [
        item for item in candidates if item["decision"] == "lexical_similarity_only"
    ]
    review_queue = [
        item for item in candidates if item["decision"] == "manual_review_required"
    ]
    exact_semantic_candidates = sum(item["similarity"] == 1.0 for item in candidates)
    failure_total = sum(failure_counts.values())
    concept_cases = len(concepts) * len(contexts)
    alias_cases = len(service.alias_groups) * len(contexts)
    outcome_cases = len(service.class_outcomes) * len(contexts)
    runtime_checks = concept_cases + alias_cases + outcome_cases
    duration_seconds = monotonic() - audit_started
    status_counts = {
        "territorial_concept_zone_cases": concept_cases,
        "territorial_alias_zone_cases": alias_cases,
        "conditional_outcome_zone_cases": outcome_cases,
    }
    quality_report = destination_quality.report()
    quality_ready = quality_report["summary"]["release_ready"]
    return {
        "generated_at": generated_at.isoformat(),
        "dataset_revision": int(metadata.get("revision", 0)),
        "scope": {
            "guarantee": (
                "Every canonical concept, approved alias, and conditional outcome has "
                "a defined answer for every Tuscan municipality and every registered "
                "service zone; municipalities without zones are checked municipality-wide."
            ),
            "excluded": "No canonical waste concept or Tuscan municipality is excluded.",
        },
        "summary": {
            "status": "pass" if not failure_total and quality_ready else "fail",
            "release_ready": not failure_total and not review_queue and quality_ready,
            "review_status": "required" if review_queue else "complete",
            "failures": failure_total,
            "failure_counts": dict(sorted(failure_counts.items())),
            "municipalities": len(municipalities),
            "service_zones": sum(map(len, zones_by_municipality.values())),
            "municipalities_with_service_zones": len(zones_by_municipality),
            "municipalities_without_service_zones": len(municipalities) - len(zones_by_municipality),
            "municipality_zone_contexts": len(contexts),
            "concepts": len(concepts),
            "concepts_with_territorial_destination": covered_concepts,
            "search_term_bindings": term_bindings,
            "approved_alias_groups": len(service.alias_groups),
            "approved_alias_search_terms": sum(
                len(group.get("search_terms", [])) for group in service.alias_groups.values()
            ),
            **status_counts,
            "total_guaranteed_cases": sum(status_counts.values()),
            "contexts_with_territorial_evidence": evidence_contexts[
                "with_territorial_evidence"
            ],
            "contexts_without_territorial_evidence": evidence_contexts[
                "without_territorial_evidence"
            ],
            "conditional_outcomes": len(service.class_outcomes),
            "alias_exact_search_checks": alias_runtime_checks,
            "alias_term_context_bindings": alias_term_cases,
            "runtime_answer_checks": runtime_checks,
            "duration_seconds": round(duration_seconds, 3),
            "checks_per_second": round(runtime_checks / duration_seconds, 1),
            "runtime_answer_statuses": dict(sorted(runtime_statuses.items())),
            "near_duplicate_candidates": len(candidates),
            "route_equivalent_duplicate_candidates": len(equivalent_candidates),
            "lexical_similarity_candidates": len(lexical_candidates),
            "near_duplicate_review_candidates": len(review_queue),
            "exact_semantic_review_candidates": exact_semantic_candidates,
        },
        "failures": failures,
        "failure_groups": sorted(
            failure_groups.values(),
            key=lambda item: (-item["cases"], item["code"], item.get("entity_id") or ""),
        ),
        "defined_non_resolved": sorted(
            defined_groups.values(),
            key=lambda item: (item["entity_type"], item["entity_id"]),
        ),
        "route_equivalent_duplicates": equivalent_candidates,
        "lexical_similarity_candidates": lexical_candidates,
        "review_queue": review_queue,
        "destination_quality": quality_report,
    }


def audit_query_coverage_path(
    database: Path,
    *,
    generated_at: datetime,
    similarity_threshold: float = 0.94,
) -> dict[str, Any]:
    connection = open_query_database(database)
    try:
        return audit_query_coverage(
            connection,
            generated_at=generated_at,
            similarity_threshold=similarity_threshold,
        )
    finally:
        connection.close()


def write_coverage_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_destination_quality_report(
    path: Path, report: dict[str, Any], *, generated_at: datetime,
) -> None:
    quality = {
        "generated_at": generated_at.isoformat(),
        "dataset_revision": report.get("dataset_revision"),
        **report["destination_quality"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(quality, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
