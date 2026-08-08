from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any

from .app_query import DisposalQueryService, _similarity, open_query_database
from .catalog import normalize_term
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
                candidates.append({
                    "left": {"concept_id": left_id, "label": left_label},
                    "right": {"concept_id": right_id, "label": right_label},
                    "similarity": score,
                    "coverage": {
                        "left_municipalities": len(left_coverage),
                        "right_municipalities": len(right_coverage),
                        "symmetric_difference": len(left_coverage ^ right_coverage),
                    },
                    "review_reason": "Termini molto simili con copertura territoriale diversa",
                })
    return sorted(
        candidates,
        key=lambda item: (-item["similarity"], item["left"]["label"].casefold()),
    )


def audit_query_coverage(
    connection: sqlite3.Connection,
    *,
    generated_at: datetime,
    similarity_threshold: float = 0.94,
) -> dict[str, Any]:
    metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    municipality_ids = _entity_ids(connection, "municipality")
    municipalities = {item.removeprefix("istat:") for item in municipality_ids}
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
    concepts: dict[str, dict[str, Any]] = {}
    concept_cases = 0
    covered_concepts = 0
    term_bindings = 0
    runtime_statuses: dict[str, int] = defaultdict(int)
    defined_non_resolved: list[dict[str, Any]] = []
    local_concept_municipality_cases = 0
    guidance_concepts: dict[str, int] = defaultdict(int)
    guidance_cases: dict[str, int] = defaultdict(int)
    cases_without_local_or_consistent_guidance = 0
    for concept_id in _entity_ids(connection, "waste_concept"):
        concept = read_entity_data(
            connection, "waste_concept", concept_id, include_sources=False,
        ) or {}
        concepts[concept_id] = concept
        coverage = _municipality_coverage(concept)
        if coverage:
            covered_concepts += 1
        local_concept_municipality_cases += len(coverage & municipalities)
        non_local_municipalities = municipalities - coverage
        guidance = service._cross_territory_guidance(concept)
        if guidance and non_local_municipalities:
            guidance_concepts[guidance["basis"]] += 1
            guidance_cases[guidance["basis"]] += len(non_local_municipalities)
        else:
            cases_without_local_or_consistent_guidance += len(non_local_municipalities)
        concept_cases += _territorial_cases(coverage, zones_by_municipality)
        term_bindings += len({
            normalize_term(term)
            for term in [concept.get("preferred_label"), *(concept.get("terms") or [])]
            if isinstance(term, str) and normalize_term(term)
        })
        for municipality in sorted(coverage - municipalities):
            failures.append({
                "code": "concept_unknown_municipality",
                "entity_id": concept_id,
                "municipality_istat": municipality,
            })
        if coverage and not concept.get("preferred_label"):
            failures.append({"code": "concept_missing_label", "entity_id": concept_id})
        for municipality in sorted(coverage & municipalities):
            for zone_id in _zones_for(municipality, zones_by_municipality):
                answer = service.answer(
                    concept.get("preferred_label", concept_id),
                    municipality,
                    concept_id=concept_id,
                    zone_id=zone_id,
                )
                runtime_statuses[answer["status"]] += 1
                if answer["status"] not in {"resolved", "not_found"}:
                    defined_non_resolved.append({
                        "status": answer["status"],
                        "entity_type": "waste_concept",
                        "entity_id": concept_id,
                        "label": concept.get("preferred_label"),
                        "municipality_istat": municipality,
                        "zone_id": zone_id,
                        "question": answer.get("question"),
                    })
                if answer["status"] == "not_found":
                    failures.append({
                        "code": "territorial_concept_not_found",
                        "entity_id": concept_id,
                        "municipality_istat": municipality,
                        "zone_id": zone_id,
                    })

    alias_cases = 0
    alias_term_cases = 0
    alias_runtime_checks = 0
    membership: dict[str, str] = {}
    for group_id, group in service.alias_groups.items():
        members = group.get("member_concept_ids", [])
        missing = sorted(set(members) - concepts.keys())
        for concept_id in missing:
            failures.append({
                "code": "alias_unknown_member",
                "entity_id": group_id,
                "member_concept_id": concept_id,
            })
        for concept_id in members:
            membership[concept_id] = group_id
        choice = service._concept_for_choice(group_id)  # audited production composition
        coverage = _municipality_coverage(choice or {})
        alias_cases += _territorial_cases(coverage, zones_by_municipality)
        for municipality in sorted(coverage & municipalities):
            for zone_id in _zones_for(municipality, zones_by_municipality):
                answer = service.answer(
                    group.get("preferred_label", group_id),
                    municipality,
                    concept_id=group_id,
                    zone_id=zone_id,
                )
                runtime_statuses[answer["status"]] += 1
                if answer["status"] not in {"resolved", "not_found"}:
                    defined_non_resolved.append({
                        "status": answer["status"],
                        "entity_type": "waste_alias_group",
                        "entity_id": group_id,
                        "label": group.get("preferred_label"),
                        "municipality_istat": municipality,
                        "zone_id": zone_id,
                        "question": answer.get("question"),
                    })
                if answer["status"] == "not_found":
                    failures.append({
                        "code": "territorial_alias_not_found",
                        "entity_id": group_id,
                        "municipality_istat": municipality,
                        "zone_id": zone_id,
                    })
        search_terms = {
            normalize_term(term) for term in group.get("search_terms", [])
            if isinstance(term, str) and normalize_term(term)
        }
        alias_term_cases += len(search_terms) * _territorial_cases(
            coverage, zones_by_municipality,
        )
        for term in search_terms:
            results = service.search(term, limit=1)
            alias_runtime_checks += 1
            if not results or results[0]["concept_id"] != group_id or results[0]["score"] != 1.0:
                failures.append({
                    "code": "alias_exact_search_not_owned",
                    "entity_id": group_id,
                    "term": term,
                    "first_result": results[0] if results else None,
                })

    review_queue = _near_duplicate_candidates(
        concepts, membership, threshold=similarity_threshold,
    )
    exact_semantic_candidates = sum(
        item["similarity"] == 1.0 for item in review_queue
    )
    status_counts = {
        "territorial_concept_zone_cases": concept_cases,
        "territorial_alias_zone_cases": alias_cases,
        "territorial_alias_term_zone_cases": alias_term_cases,
    }
    return {
        "generated_at": generated_at.isoformat(),
        "dataset_revision": int(metadata.get("revision", 0)),
        "scope": {
            "guarantee": (
                "Every published territorial concept and approved alias has a defined "
                "destination path for every covered municipality and registered service zone."
            ),
            "excluded": (
                "General catalog concepts without territorial evidence are not asserted in every municipality."
            ),
        },
        "summary": {
            "status": "pass" if not failures else "fail",
            "release_ready": not failures and not review_queue,
            "review_status": "required" if review_queue else "complete",
            "failures": len(failures),
            "municipalities": len(municipalities),
            "service_zones": sum(map(len, zones_by_municipality.values())),
            "municipalities_with_service_zones": len(zones_by_municipality),
            "concepts": len(concepts),
            "concepts_with_territorial_destination": covered_concepts,
            "search_term_bindings": term_bindings,
            "approved_alias_groups": len(service.alias_groups),
            "approved_alias_search_terms": sum(
                len(group.get("search_terms", [])) for group in service.alias_groups.values()
            ),
            **status_counts,
            "total_guaranteed_cases": sum(status_counts.values()),
            "alias_exact_search_checks": alias_runtime_checks,
            "runtime_answer_checks": concept_cases + alias_cases,
            "runtime_answer_statuses": dict(sorted(runtime_statuses.items())),
            "catalog_municipality_cases": len(concepts) * len(municipalities),
            "local_concept_municipality_cases": local_concept_municipality_cases,
            "cross_territory_guidance_concepts": dict(sorted(guidance_concepts.items())),
            "cross_territory_guidance_cases": dict(sorted(guidance_cases.items())),
            "cases_without_local_or_consistent_guidance": (
                cases_without_local_or_consistent_guidance
            ),
            "near_duplicate_review_candidates": len(review_queue),
            "exact_semantic_review_candidates": exact_semantic_candidates,
        },
        "failures": failures,
        "defined_non_resolved": defined_non_resolved,
        "review_queue": review_queue,
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
