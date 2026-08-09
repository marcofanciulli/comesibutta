from __future__ import annotations

from datetime import date
from difflib import SequenceMatcher
import json
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
import re
import sqlite3
from typing import Any

from .catalog import normalize_term
from .curation import matching_collection_streams, matching_delivery_channels
from .sync import DATASET_ID, STORAGE_VERSION, read_entity_data


def open_query_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    if metadata.get("dataset_id") != DATASET_ID:
        connection.close()
        raise ValueError("The database does not contain the expected dataset")
    if int(metadata.get("storage_version", 0)) != STORAGE_VERSION:
        connection.close()
        raise ValueError("The database must be rebuilt from a current snapshot")
    return connection


def _similarity(query: str, candidate: str) -> float:
    if query == candidate:
        return 1.0
    if not query or not candidate:
        return 0.0
    if _italian_inflection_equivalent(query, candidate):
        return 0.98
    stopwords = {"a", "al", "alla", "con", "da", "dal", "dalla", "de", "dei", "del", "della", "di", "e", "in", "il", "la", "le", "lo", "per", "un", "una"}
    query_tokens = [token for token in query.split() if token not in stopwords]
    candidate_tokens = [token for token in candidate.split() if token not in stopwords]
    if not query_tokens:
        query_tokens = query.split()
    if not candidate_tokens:
        candidate_tokens = candidate.split()
    sequence = SequenceMatcher(None, query, candidate).ratio()
    containment = 0.0
    if query in candidate or candidate in query:
        containment = 0.9 * min(len(query), len(candidate)) / max(len(query), len(candidate)) + 0.1
    query_coverage = sum(
        max(SequenceMatcher(None, token, other).ratio() for other in candidate_tokens)
        for token in query_tokens
    ) / len(query_tokens)
    candidate_coverage = sum(
        max(SequenceMatcher(None, token, other).ratio() for other in query_tokens)
        for token in candidate_tokens
    ) / len(candidate_tokens)
    token_fuzzy = (
        2 * query_coverage * candidate_coverage / (query_coverage + candidate_coverage)
        if query_coverage + candidate_coverage else 0.0
    )
    exact_coverage = len(set(query_tokens) & set(candidate_tokens)) / len(set(query_tokens))
    token_score = 0.45 * sequence + 0.35 * token_fuzzy + 0.2 * exact_coverage
    if token_fuzzy >= 0.88:
        token_score = max(token_score, sequence, token_fuzzy)
    return round(max(token_score, containment), 6)


def _italian_inflection_equivalent(left: str, right: str) -> bool:
    left_tokens = left.split()
    right_tokens = right.split()
    if len(left_tokens) != len(right_tokens):
        return False
    differences = [
        (left_token, right_token)
        for left_token, right_token in zip(left_tokens, right_tokens)
        if left_token != right_token
    ]
    if len(differences) != 1:
        return False
    left_token, right_token = differences[0]
    if len(left_token) != len(right_token) or len(left_token) < 4:
        return False
    if left_token[:-1] != right_token[:-1]:
        return False
    return frozenset((left_token[-1], right_token[-1])) in {
        frozenset(("a", "e")),
        frozenset(("o", "i")),
        frozenset(("e", "i")),
    }


def _destination_type(destination: str) -> str:
    normalized = normalize_term(destination)
    if any(token in normalized for token in ("centro di raccolta", "ecocentro", "stazione ecologica")):
        return "facility"
    if any(token in normalized for token in ("ritiro", "domicilio", "prenotazione")):
        return "pickup"
    if "punto" in normalized:
        return "collection_point"
    return "collection_stream"


def _description_matches_terms(description: str, terms: set[str]) -> bool:
    description_tokens = description.split()
    stopwords = {"a", "al", "con", "da", "dei", "del", "di", "e", "in", "la", "le", "per"}
    for term in terms:
        term_tokens = [
            token for token in term.split()
            if token not in stopwords and len(token) >= 5
        ]
        if term_tokens and all(
            any(
                token == candidate
                or (
                    len(candidate) >= 5
                    and token[:-1] == candidate[:-1]
                )
                for candidate in description_tokens
            )
            for token in term_tokens
        ):
            return True
    return False


def _distance_km(
    latitude_a: float | None,
    longitude_a: float | None,
    latitude_b: float | None,
    longitude_b: float | None,
) -> float | None:
    if None in {latitude_a, longitude_a, latitude_b, longitude_b}:
        return None
    lat_a, lon_a, lat_b, lon_b = map(
        radians, (latitude_a, longitude_a, latitude_b, longitude_b),
    )
    latitude_delta = lat_b - lat_a
    longitude_delta = lon_b - lon_a
    haversine = (
        sin(latitude_delta / 2) ** 2
        + cos(lat_a) * cos(lat_b) * sin(longitude_delta / 2) ** 2
    )
    return 6371.0088 * 2 * asin(sqrt(haversine))


def _source_summary(source: dict[str, Any]) -> dict[str, Any] | None:
    url = source.get("url") or source.get("source_url")
    retrieved_at = source.get("retrieved_at")
    if not url or not retrieved_at:
        return None
    return {
        "url": url,
        "retrieved_at": retrieved_at,
        "label": source.get("publisher"),
    }


class DisposalQueryService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.revision = int(dict(
            connection.execute("SELECT key, value FROM metadata")
        ).get("revision", 0))
        self.alias_groups: dict[str, dict[str, Any]] = {}
        self.alias_membership: dict[str, str] = {}
        self.streams: dict[str, dict[str, Any]] = {}
        self.stream_aliases: dict[str, str] = {}
        self.delivery_channels: list[dict[str, Any]] = []
        self.eer_mappings: dict[str, list[dict[str, Any]]] = {}
        self.stream_mappings: dict[str, dict[str, Any]] = {}
        self.disambiguations: dict[str, dict[str, Any]] = {}
        self.waste_classes: dict[str, dict[str, Any]] = {}
        self.hazard_material_profiles: list[dict[str, Any]] = []
        self.family_classes: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        self.family_destination_classes: dict[
            str, tuple[dict[str, Any], dict[str, Any]]
        ] = {}
        self.family_mappings_by_class: dict[str, list[dict[str, Any]]] = {}
        self.class_outcomes: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        self.family_term_classes: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self._concept_cache: dict[str, dict[str, Any] | None] = {}
        self._matching_rules_cache: dict[
            tuple[str, str, str | None, str, bool], list[dict[str, Any]]
        ] = {}
        self._canonical_stream_cache: dict[str, str | None] = {}
        self._channel_matches_cache: dict[str, list[dict[str, Any]]] = {}
        self._destination_key_cache: dict[str, str] = {}
        self._facility_access_cache: dict[
            tuple[str, str], dict[str, list[dict[str, Any]]]
        ] = {}
        self._facility_entity_cache: dict[str, dict[str, Any] | None] = {}
        self._facility_acceptance_items_cache: dict[
            tuple[str, str], tuple[list[dict[str, Any]], list[dict[str, Any]]]
        ] = {}
        self._facility_opening_cache: dict[
            str, tuple[list[dict[str, Any]], list[dict[str, Any]]]
        ] = {}
        self._eer_entry_cache: dict[str, dict[str, Any] | None] = {}
        self._facility_fallback_cache: dict[
            tuple[str, str, str, float | None, float | None],
            tuple[dict[str, Any] | None, list[dict[str, Any]]],
        ] = {}
        for row in connection.execute(
            """SELECT entity_id FROM entities
            WHERE entity_type = 'waste_alias_group' ORDER BY entity_id"""
        ):
            group = read_entity_data(
                connection, "waste_alias_group", row["entity_id"], include_sources=False,
            )
            if group:
                self.alias_groups[group["group_id"]] = group
                for concept_id in group["member_concept_ids"]:
                    self.alias_membership[concept_id] = group["group_id"]
        for row in connection.execute(
            """SELECT entity_id FROM entities
            WHERE entity_type = 'collection_stream' ORDER BY entity_id"""
        ):
            stream = read_entity_data(
                connection, "collection_stream", row["entity_id"], include_sources=False,
            )
            if stream:
                self.streams[stream["stream_id"]] = stream
                for alias in stream["aliases"]:
                    self.stream_aliases[normalize_term(alias)] = stream["stream_id"]
        for row in connection.execute(
            """SELECT entity_id FROM entities
            WHERE entity_type = 'delivery_channel' ORDER BY entity_id"""
        ):
            channel = read_entity_data(
                connection, "delivery_channel", row["entity_id"], include_sources=False,
            )
            if channel:
                self.delivery_channels.append(channel)
        for row in connection.execute(
            """SELECT entity_id FROM entities
            WHERE entity_type = 'waste_eer_mapping' ORDER BY entity_id"""
        ):
            mapping = read_entity_data(
                connection, "waste_eer_mapping", row["entity_id"], include_sources=False,
            )
            if not mapping:
                continue
            entry = read_entity_data(
                connection, "eer_entry", f"eer:{mapping['eer_code']}",
                include_sources=False,
            ) or {}
            candidate = {
                "code": mapping["eer_code"],
                "source_labels": [mapping["preferred_label"]],
                "source_urls": mapping.get("source_urls", []),
                "hazardous": entry.get("hazardous"),
                "official_hazardous": entry.get("hazardous"),
                "official_title": entry.get("title"),
                "register_status": (
                    "retired_in_target" if entry.get("valid_to")
                    else "active_in_target" if entry else "unknown_code"
                ),
                "valid_to": entry.get("valid_to"),
                "mapping_condition": mapping.get("condition"),
                "mapping_id": mapping["mapping_id"],
                "mapping_delivery_channels": mapping.get("delivery_channels", []),
                "mapping_sources": [
                    {
                        "url": url,
                        "publisher": "Classificazione EER revisionata",
                        "retrieved_at": mapping["reviewed_at"],
                    }
                    for url in mapping.get("source_urls", [])
                    if mapping.get("reviewed_at")
                ],
            }
            for concept_id in mapping.get("concept_ids", []):
                self.eer_mappings.setdefault(concept_id, []).append(candidate)
        for row in connection.execute(
            """SELECT entity_id FROM entities
            WHERE entity_type = 'waste_stream_mapping' ORDER BY entity_id"""
        ):
            mapping = read_entity_data(
                connection, "waste_stream_mapping", row["entity_id"],
                include_sources=False,
            )
            if mapping:
                mapping = dict(mapping)
                mapping["sources"] = self._reviewed_mapping_sources(mapping)
                for concept_id in mapping.get("concept_ids", []):
                    self.stream_mappings[concept_id] = mapping
        for row in connection.execute(
            """SELECT entity_id FROM entities
            WHERE entity_type = 'waste_disambiguation_group' ORDER BY entity_id"""
        ):
            group = read_entity_data(
                connection, "waste_disambiguation_group", row["entity_id"],
                include_sources=False,
            )
            if group:
                for concept_id in group.get("trigger_concept_ids", []):
                    self.disambiguations[concept_id] = group
        for row in connection.execute(
            """SELECT entity_id FROM entities
            WHERE entity_type = 'hazard_material_profile' ORDER BY entity_id"""
        ):
            profile = read_entity_data(
                connection, "hazard_material_profile", row["entity_id"],
                include_sources=False,
            )
            if profile:
                self.hazard_material_profiles.append(profile)
        for row in connection.execute(
            """SELECT entity_id FROM entities
            WHERE entity_type = 'waste_class' ORDER BY entity_id"""
        ):
            waste_class = read_entity_data(
                connection, "waste_class", row["entity_id"], include_sources=False,
            )
            if waste_class:
                self.waste_classes[waste_class["class_id"]] = waste_class
                for outcome in (waste_class.get("question") or {}).get("options", []):
                    self.class_outcomes[outcome["outcome_id"]] = (waste_class, outcome)
        for row in connection.execute(
            """SELECT entity_id FROM entities
            WHERE entity_type = 'waste_family_mapping' ORDER BY entity_id"""
        ):
            mapping = read_entity_data(
                connection, "waste_family_mapping", row["entity_id"],
                include_sources=False,
            )
            if not mapping:
                continue
            waste_class = self.waste_classes.get(mapping["class_id"])
            if waste_class:
                self.family_mappings_by_class.setdefault(
                    waste_class["class_id"], [],
                ).append(mapping)
                for category in mapping.get("source_categories", []):
                    self.family_classes[category.strip()] = (mapping, waste_class)
                for destination in mapping.get("destination_aliases", []):
                    self.family_destination_classes[normalize_term(destination)] = (
                        mapping, waste_class,
                    )
                if mapping.get("term_patterns"):
                    self.family_term_classes.append((mapping, waste_class))

    @staticmethod
    def _reviewed_mapping_sources(mapping: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "url": url,
                "publisher": "Classificazione revisionata",
                "retrieved_at": mapping["reviewed_at"],
            }
            for url in mapping.get("source_urls", [])
            if mapping.get("reviewed_at")
        ]

    def _with_curated_eer(self, concept: dict[str, Any]) -> dict[str, Any]:
        mappings = self.eer_mappings.get(concept["concept_id"], [])
        if not mappings:
            return self._with_hazard_eer_precedence(concept)
        source_candidates = concept.get("eer", {}).get("candidates", [])
        candidates = {candidate["code"]: candidate for candidate in mappings}
        candidates.update({candidate["code"]: candidate for candidate in source_candidates})
        source_codes = {candidate["code"] for candidate in source_candidates}
        result = dict(concept)
        result["eer"] = {
            "status": (
                "source_consensus" if len(source_codes) == 1 and len(candidates) == 1
                else "curated_mapping" if not source_codes and len(candidates) == 1
                else "conflict" if candidates else "not_available"
            ),
            "candidates": [candidates[code] for code in sorted(candidates)],
        }
        return self._with_hazard_eer_precedence(result)

    def _with_hazard_eer_precedence(
        self, concept: dict[str, Any],
    ) -> dict[str, Any]:
        candidates = (concept.get("eer") or {}).get("candidates", [])
        hazardous = [
            candidate for candidate in candidates
            if self._candidate_is_hazardous(candidate)
        ]
        if not concept.get("hazard_profile_ids") and not hazardous:
            return concept
        suppressed = [
            candidate for candidate in candidates if candidate not in hazardous
        ]
        result = dict(concept)
        result["suppressed_non_hazardous_eer_codes"] = sorted({
            *result.get("suppressed_non_hazardous_eer_codes", []),
            *(candidate["code"] for candidate in suppressed),
        })
        result["eer"] = {
            "status": (
                "curated_mapping" if len(hazardous) == 1
                else "conflict" if hazardous else "not_available"
            ),
            "candidates": sorted(hazardous, key=lambda item: item["code"]),
        }
        return result

    def _with_hazard_profiles(self, concept: dict[str, Any]) -> dict[str, Any]:
        terms = [
            concept.get("normalized_term", ""),
            *(normalize_term(term) for term in concept.get("terms", [])),
        ]
        matched = [
            profile for profile in self.hazard_material_profiles
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
        if not matched:
            return concept
        result = dict(concept)
        result["hazard_profile_ids"] = sorted({
            profile["profile_id"] for profile in matched
        })
        result["hazard_sources"] = [
            source
            for profile in matched
            for source in self._reviewed_mapping_sources(profile)
        ]
        return result

    def _hazard_requires_separate_handling(self, concept: dict[str, Any]) -> bool:
        candidates = (concept.get("eer") or {}).get("candidates", [])
        return bool(
            concept.get("hazard_profile_ids")
            or any(self._candidate_is_hazardous(candidate) for candidate in candidates)
            or (not candidates and any(
                "pericolos" in normalize_term(category)
                for category in concept.get("source_categories", [])
            ))
        )

    def _hazard_metadata(self, concept: dict[str, Any]) -> dict[str, Any]:
        required = self._hazard_requires_separate_handling(concept)
        return {
            "hazard_status": "separate_handling_required" if required else None,
            "hazard_profile_ids": concept.get("hazard_profile_ids", []),
            "suppressed_non_hazardous_eer_codes": concept.get(
                "suppressed_non_hazardous_eer_codes", []
            ),
        }

    def _hazard_compatible_destination(self, destination: str) -> bool:
        return bool(self._channel_matches(destination)) and not self._canonical_stream(
            destination
        )

    def _class_is_hazard_compatible(self, waste_class: dict[str, Any]) -> bool:
        if waste_class.get("hazard_compatible"):
            return True
        routes = [
            waste_class,
            *((waste_class.get("question") or {}).get("options", [])),
        ]
        codes = [code for route in routes for code in route.get("eer_codes", [])]
        if not codes or any(route.get("stream_ids") for route in routes):
            return False
        return all(
            bool((self._eer_entry(code) or {}).get("hazardous"))
            for code in codes
        )

    def _with_family_class(self, concept: dict[str, Any]) -> dict[str, Any]:
        matches: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}

        def add_match(mapping: dict[str, Any], waste_class: dict[str, Any]) -> None:
            class_id = waste_class["class_id"]
            existing = matches.get(class_id)
            if (
                existing is None
                or mapping.get("priority", 0) > existing[0].get("priority", 0)
            ):
                matches[class_id] = mapping, waste_class

        for selector in [
            *(category.strip() for category in concept.get("source_categories", [])),
            *(
                normalize_term(destination.get("label", ""))
                for destination in concept.get("local_destinations", [])
            ),
        ]:
            match = (
                self.family_classes.get(selector)
                or self.family_destination_classes.get(selector)
            )
            if match is not None:
                add_match(*match)
        normalized_term = concept.get("normalized_term", "")
        for mapping, waste_class in self.family_term_classes:
            if not any(
                re.search(pattern, normalized_term)
                for pattern in mapping.get("term_patterns", [])
            ):
                continue
            if any(
                re.search(pattern, normalized_term)
                for pattern in mapping.get("excluded_term_patterns", [])
            ):
                continue
            add_match(mapping, waste_class)
        selected: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        by_dimension: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
        for mapping, waste_class in matches.values():
            dimension = waste_class.get("dimension", waste_class["class_id"])
            by_dimension.setdefault(dimension, []).append((mapping, waste_class))
        for dimension_matches in by_dimension.values():
            if self._hazard_requires_separate_handling(concept):
                specific_hazardous = [
                    item for item in dimension_matches
                    if self._class_is_hazard_compatible(item[1])
                    and item[1].get("eer_codes")
                    and not item[1].get("fallback")
                ]
                if specific_hazardous:
                    dimension_matches = specific_hazardous
            maximum_priority = max(
                mapping.get("priority", 0) for mapping, _ in dimension_matches
            )
            winners = [
                (mapping, waste_class)
                for mapping, waste_class in dimension_matches
                if mapping.get("priority", 0) == maximum_priority
            ]
            if len(winners) != 1:
                return concept
            mapping, waste_class = winners[0]
            selected[waste_class["class_id"]] = (mapping, waste_class)
        if sum(bool(item.get("question")) for _, item in selected.values()) > 1:
            return concept
        result = concept
        for mapping, waste_class in selected.values():
            if (
                self._hazard_requires_separate_handling(result)
                and not self._class_is_hazard_compatible(waste_class)
            ):
                continue
            result = self._apply_class_route(result, mapping, waste_class, waste_class)
        return self._with_hazard_eer_precedence(result)

    def _apply_class_route(
        self,
        concept: dict[str, Any],
        mapping: dict[str, Any],
        waste_class: dict[str, Any],
        route: dict[str, Any],
    ) -> dict[str, Any]:
        result = dict(concept)
        result["family_class_ids"] = sorted({
            *result.get("family_class_ids", []), waste_class["class_id"],
        })
        result["family_stream_ids"] = sorted({
            *result.get("family_stream_ids", []), *route.get("stream_ids", []),
        })
        result["family_delivery_channel_ids"] = sorted({
            *result.get("family_delivery_channel_ids", []),
            *route.get("delivery_channels", []),
        })
        result["family_acceptance_terms"] = sorted({
            *result.get("family_acceptance_terms", []),
            *waste_class.get("facility_acceptance_terms", []),
            *route.get("facility_acceptance_terms", []),
        })
        result["family_sources"] = [
            *result.get("family_sources", []), *self._reviewed_mapping_sources(mapping),
        ]
        if route is waste_class and waste_class.get("question"):
            result["family_question"] = waste_class["question"]
        candidates = {
            candidate["code"]: candidate
            for candidate in (concept.get("eer") or {}).get("candidates", [])
        }
        channel_labels = [
            channel["preferred_label"]
            for channel_id in route.get("delivery_channels", [])
            for channel in self.delivery_channels
            if channel["channel_id"] == channel_id
        ]
        for code in route.get("eer_codes", []):
            entry = read_entity_data(
                self.connection, "eer_entry", f"eer:{code}", include_sources=False,
            ) or {}
            candidates.setdefault(code, {
                "code": code,
                "source_labels": [route.get("label", waste_class["preferred_label"])],
                "source_urls": mapping.get("source_urls", []),
                "hazardous": entry.get("hazardous"),
                "official_hazardous": entry.get("hazardous"),
                "official_title": entry.get("title"),
                "register_status": (
                    "retired_in_target" if entry.get("valid_to")
                    else "active_in_target" if entry else "unknown_code"
                ),
                "valid_to": entry.get("valid_to"),
                "mapping_condition": None,
                "mapping_id": mapping["mapping_id"],
                "mapping_delivery_channels": channel_labels,
                "mapping_sources": result["family_sources"],
            })
        result["eer"] = {
            "status": (
                "curated_mapping" if len(candidates) == 1
                else "conflict" if candidates else "not_available"
            ),
            "candidates": [candidates[code] for code in sorted(candidates)],
        }
        return result

    def _with_explicit_family_class(
        self, concept: dict[str, Any], class_id: str,
    ) -> dict[str, Any]:
        waste_class = self.waste_classes.get(class_id)
        mappings = self.family_mappings_by_class.get(class_id, [])
        if waste_class is None or not mappings:
            return concept
        if (
            self._hazard_requires_separate_handling(concept)
            and not self._class_is_hazard_compatible(waste_class)
        ):
            return concept
        mapping = {
            **mappings[0],
            "mapping_id": (
                "family-map:alias-"
                f"{concept['concept_id'].removeprefix('waste-alias:')}"
            ),
            "reviewed_at": max(item["reviewed_at"] for item in mappings),
            "source_urls": sorted({
                url for item in mappings for url in item.get("source_urls", [])
            }),
        }
        return self._apply_class_route(
            concept, mapping, waste_class, waste_class,
        )

    def search(
        self,
        text: str,
        *,
        municipality_istat: str | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        normalized_query = normalize_term(text)
        if not normalized_query:
            return []
        best: dict[str, dict[str, Any]] = {}
        for row in self.connection.execute(
            """SELECT entity.entity_id, term.term, term.normalized_term
            FROM waste_search_terms term
            JOIN entities entity ON entity.entity_key = term.entity_key
            WHERE entity.entity_type = 'waste_concept'"""
        ):
            score = _similarity(normalized_query, row["normalized_term"])
            candidate = best.get(row["entity_id"])
            if candidate is None or score > candidate["score"]:
                best[row["entity_id"]] = {
                    "concept_id": row["entity_id"],
                    "label": row["term"],
                    "normalized_term": row["normalized_term"],
                    "score": score,
                }
        grouped: dict[str, dict[str, Any]] = {}
        for candidate in best.values():
            choice_id = self.alias_membership.get(
                candidate["concept_id"], candidate["concept_id"],
            )
            current = grouped.get(choice_id)
            if current is None or candidate["score"] > current["score"]:
                group = self.alias_groups.get(choice_id)
                grouped[choice_id] = {
                    **candidate,
                    "concept_id": choice_id,
                    "label": group["preferred_label"] if group else candidate["label"],
                    "matched_member_concept_id": candidate["concept_id"],
                    "member_concept_ids": (
                        group["member_concept_ids"] if group else [candidate["concept_id"]]
                    ),
                }
        for group_id, group in self.alias_groups.items():
            score, matched_term = max(
                (
                    (_similarity(normalized_query, normalize_term(term)), term)
                    for term in group["search_terms"]
                ),
                default=(0.0, group["preferred_label"]),
            )
            current = grouped.get(group_id)
            if current is None or score > current["score"]:
                grouped[group_id] = {
                    "concept_id": group_id,
                    "label": group["preferred_label"],
                    "normalized_term": normalize_term(matched_term),
                    "score": score,
                    "matched_member_concept_id": None,
                    "member_concept_ids": group["member_concept_ids"],
                }
        ranked = sorted(
            grouped.values(),
            key=lambda item: (-item["score"], len(item["normalized_term"]), item["label"].casefold()),
        )
        if municipality_istat:
            for candidate in ranked[: max(limit * 4, 20)]:
                concept = self._concept_for_choice(candidate["concept_id"])
                candidate["available_in_municipality"] = any(
                    municipality_istat in destination["municipality_istats"]
                    for destination in (concept or {}).get("local_destinations", [])
                )
            ranked.sort(key=lambda item: (
                -(
                    item["score"]
                    + (0.08 if item.get("available_in_municipality", False) else 0)
                ),
                len(item["normalized_term"]),
            ))
        return ranked[:limit]

    def answer(
        self,
        text: str,
        municipality_istat: str,
        *,
        concept_id: str | None = None,
        zone_id: str | None = None,
        user_type: str = "domestic",
        as_of: date | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> dict[str, Any]:
        if len(municipality_istat) != 6 or not municipality_istat.isdigit():
            raise ValueError("Municipality ISTAT code must contain six digits")
        if user_type not in {"domestic", "non_domestic"}:
            raise ValueError("User type must be domestic or non_domestic")
        if (latitude is None) != (longitude is None):
            raise ValueError("Latitude and longitude must be provided together")
        if latitude is not None and not -90 <= latitude <= 90:
            raise ValueError("Latitude must be between -90 and 90")
        if longitude is not None and not -180 <= longitude <= 180:
            raise ValueError("Longitude must be between -180 and 180")
        as_of = as_of or date.today()
        if concept_id:
            selected_concept = self._concept_for_choice(concept_id)
            if selected_concept:
                suggestions = [{
                    "concept_id": concept_id,
                    "label": selected_concept["preferred_label"],
                    "normalized_term": selected_concept["normalized_term"],
                    "score": 1.0,
                    "available_in_municipality": any(
                        municipality_istat in destination["municipality_istats"]
                        for destination in selected_concept.get("local_destinations", [])
                    ),
                    "member_concept_ids": selected_concept.get(
                        "member_concept_ids", [selected_concept["concept_id"]],
                    ),
                }]
            else:
                suggestions = []
        else:
            suggestions = self.search(text, municipality_istat=municipality_istat, limit=6)
        base = {
            "query": {"text": text, "matched_concept_id": None, "matched_label": None},
            "context": {
                "municipality_istat": municipality_istat,
                "zone_id": zone_id,
                "user_type": user_type,
                "as_of": as_of.isoformat(),
                "location": (
                    {"latitude": latitude, "longitude": longitude}
                    if latitude is not None else None
                ),
            },
            "status": "not_found",
            "question": None,
            "result": None,
            "alternatives": suggestions,
            "provenance": {
                "verified_at": None,
                "dataset_revision": self.revision,
                "review_status": "automatic",
                "sources": [],
            },
        }
        if not suggestions or suggestions[0]["score"] < 0.55:
            return base
        selected = next(
            (
                candidate for candidate in suggestions
                if candidate.get("available_in_municipality") and candidate["score"] >= 0.55
            ),
            suggestions[0],
        )
        if concept_id is None and selected["score"] < 0.88:
            local_options = [
                item for item in suggestions
                if item.get("available_in_municipality") and item["score"] >= 0.55
            ]
            option_pool = local_options or suggestions
            base["status"] = "needs_question"
            base["question"] = {
                "text": "Non ho trovato una corrispondenza certa. Quale rifiuto intendi?",
                "options": [
                    {"id": item["concept_id"], "label": item["label"]}
                    for item in option_pool if item["score"] >= 0.55
                ],
            }
            return base
        close = [
            candidate for candidate in suggestions
            if candidate["concept_id"] != selected["concept_id"]
            if (
                not selected.get("available_in_municipality")
                or candidate.get("available_in_municipality")
            )
            if candidate["score"] >= 0.72 and selected["score"] - candidate["score"] < 0.08
        ]
        if close and selected["score"] < 0.96:
            base["status"] = "needs_question"
            base["question"] = {
                "text": "Quale di questi rifiuti intendi?",
                "options": [
                    {"id": item["concept_id"], "label": item["label"]}
                    for item in [selected, *close]
                ],
            }
            return base
        concept = self._concept_for_choice(selected["concept_id"])
        if concept is None:
            return base
        base["query"].update({
            "matched_concept_id": concept["concept_id"],
            "matched_label": concept["preferred_label"],
        })
        disambiguation = self.disambiguations.get(concept["concept_id"])
        if disambiguation is not None:
            base["status"] = "needs_question"
            base["question"] = {
                "text": disambiguation["prompt"],
                "options": [
                    {
                        "id": option["concept_id"],
                        "label": option["label"],
                        "hint": option["hint"],
                    }
                    for option in disambiguation["options"]
                ],
            }
            return base
        hazard_restricted = self._hazard_requires_separate_handling(concept)
        destinations = []
        for destination in concept.get("local_destinations", []):
            if municipality_istat in destination["municipality_istats"]:
                if hazard_restricted and not self._hazard_compatible_destination(
                    destination["label"]
                ):
                    continue
                key = self._canonical_destination_key(destination["label"])
                existing_keys = {
                    self._canonical_destination_key(item["label"])
                    for item in destinations
                }
                if key not in existing_keys:
                    destinations.append(destination)
        evidence = [
            item for item in concept.get("evidence", [])
            if municipality_istat in item.get("municipality_istats", [])
        ]
        stream_mapping = self.stream_mappings.get(concept["concept_id"])
        if not hazard_restricted and not destinations and stream_mapping is not None:
            stream = self.streams.get(stream_mapping["stream_id"])
            if stream is not None:
                destinations.append({
                    "label": stream["preferred_label"],
                    "municipality_istats": [municipality_istat],
                    "source_urls": stream_mapping.get("source_urls", []),
                })
                evidence.extend(stream_mapping.get("sources", []))
        family_destinations_added = False
        if (
            not hazard_restricted
            and not destinations
            and concept.get("family_stream_ids")
        ):
            matching_streams = []
            for stream_id in concept["family_stream_ids"]:
                stream = self.streams.get(stream_id)
                if stream and self._matching_rules(
                    stream["preferred_label"], municipality_istat,
                    zone_id=zone_id, user_type=user_type,
                    require_canonical_match=True,
                ):
                    matching_streams.append(stream)
            for stream in matching_streams:
                destinations.append({
                    "label": stream["preferred_label"],
                    "municipality_istats": [municipality_istat],
                    "source_urls": [],
                })
                family_destinations_added = True
            evidence.extend(concept.get("family_sources", []))
        self._set_provenance(base, evidence)
        family_question = concept.get("family_question")
        if not destinations and family_question is not None:
            base["status"] = "needs_question"
            base["question"] = {
                "text": family_question["prompt"],
                "options": [
                    {
                        "id": option["outcome_id"],
                        "label": option["label"],
                        "hint": option["hint"],
                    }
                    for option in family_question["options"]
                ],
            }
            return base
        if not destinations:
            fallback, fallback_sources = self._facility_fallback(
                concept,
                municipality_istat=municipality_istat,
                user_type=user_type,
                latitude=latitude,
                longitude=longitude,
            )
            if fallback is not None:
                base["status"] = "resolved"
                base["result"] = fallback
                self._set_provenance(base, [
                    *[
                        item for item in concept.get("evidence", [])
                        if municipality_istat in item.get("municipality_istats", [])
                    ],
                    *fallback_sources,
                ])
            else:
                portable = self._portable_route_fallback(concept)
                if portable is not None:
                    base["status"] = "resolved"
                    base["result"] = portable
                    self._set_provenance(base, self._portable_route_sources(concept))
            return base
        if len(destinations) > 1:
            if family_destinations_added:
                portable = self._portable_route_fallback(concept)
                if portable is not None:
                    base["status"] = "resolved"
                    base["result"] = portable
                    return base
            stream_ids = {
                stream_id
                for item in destinations
                for stream_id in [self._canonical_stream(item["label"])]
                if stream_id is not None
            }
            unresolved_route_keys = {
                normalize_term(item["label"])
                for item in destinations
                if self._canonical_stream(item["label"]) is None
                and not self._channel_matches(item["label"])
            }
            if len(stream_ids) + len(unresolved_route_keys) > 1:
                base["status"] = "conflict"
                base["question"] = {
                    "text": "Le fonti pubblicano piu destinazioni per questo rifiuto.",
                    "options": [
                        {
                            "id": normalize_term(item["label"]).replace(" ", "-"),
                            "label": item["label"],
                        }
                        for item in destinations
                    ],
                }
                return base
            destination = ", ".join(item["label"] for item in destinations)
            rules = self._matching_rules(
                destination, municipality_istat,
                zone_id=zone_id, user_type=user_type,
            ) if stream_ids else []
            base["status"] = "resolved"
            base["result"], facility_sources = self._result(
                concept, destination, rules[0] if rules else None,
                municipality_istat=municipality_istat,
                zone_id=zone_id,
                user_type=user_type,
                latitude=latitude,
                longitude=longitude,
            )
            self._set_provenance(base, [
                *evidence, *facility_sources,
                *(rules[0].get("sources", []) if rules else []),
            ])
            return base
        destination = destinations[0]["label"]
        rules = []
        if self._canonical_stream(destination) or not self._channel_matches(destination):
            rules = self._matching_rules(
                destination, municipality_istat, zone_id=zone_id, user_type=user_type,
            )
        if zone_id is None:
            zone_ids = sorted({item["payload"].get("zone_ref") for item in rules if item["payload"].get("zone_ref")})
            signatures = {self._rule_signature(item) for item in rules}
            if len(zone_ids) > 1 and len(signatures) > 1:
                base["status"] = "needs_question"
                base["question"] = {
                    "text": "In quale zona di raccolta ti trovi?",
                    "options": [
                        {"id": item, "label": self._zone_label(item)} for item in zone_ids
                    ],
                }
                return base
        rule = rules[0] if rules else None
        base["status"] = "resolved"
        base["result"], facility_sources = self._result(
            concept, destination, rule,
            municipality_istat=municipality_istat,
            zone_id=zone_id,
            user_type=user_type,
            latitude=latitude,
            longitude=longitude,
        )
        self._set_provenance(base, [
            *evidence,
            *((rule or {}).get("sources", [])),
            *facility_sources,
        ])
        return base

    def _matching_rules(
        self,
        destination: str,
        municipality_istat: str,
        *,
        zone_id: str | None,
        user_type: str,
        require_canonical_match: bool = False,
    ) -> list[dict[str, Any]]:
        cache_key = (
            normalize_term(destination), municipality_istat, zone_id,
            user_type, require_canonical_match,
        )
        cached = self._matching_rules_cache.get(cache_key)
        if cached is not None:
            return cached
        candidates = []
        for row in self.connection.execute(
            """SELECT entity_id, zone_ref, stream_name FROM entities
            WHERE entity_type = 'collection_rule' AND municipality_ref = ?""",
            (f"istat:{municipality_istat}",),
        ):
            destination_stream = self._canonical_stream(destination)
            rule_stream = self._canonical_stream(row["stream_name"] or "")
            score = (
                1.0
                if destination_stream and destination_stream == rule_stream
                else 0.0
                if require_canonical_match and destination_stream
                else _similarity(
                    normalize_term(destination), normalize_term(row["stream_name"] or ""),
                )
            )
            if score < 0.45:
                continue
            data = read_entity_data(self.connection, "collection_rule", row["entity_id"])
            if data is None:
                continue
            payload = data.get("payload") or {}
            if payload.get("user_type") not in {None, "all", "unspecified", user_type}:
                continue
            if zone_id and payload.get("zone_ref") not in {None, zone_id}:
                continue
            data["_score"] = score
            candidates.append(data)
        result = sorted(candidates, key=lambda item: (
            -item["_score"],
            item["payload"].get("zone_ref") or "",
            item.get("natural_key", ""),
        ))
        self._matching_rules_cache[cache_key] = result
        return result

    @staticmethod
    def _rule_signature(rule: dict[str, Any]) -> str:
        payload = rule["payload"]
        return json.dumps({
            "stream": payload.get("stream_name"),
            "container_type": payload.get("container_type"),
            "container_color": payload.get("container_color"),
            "presentation": payload.get("presentation"),
        }, ensure_ascii=False, sort_keys=True)

    def _zone_label(self, zone_id: str) -> str:
        zone = read_entity_data(
            self.connection, "service_zone", zone_id, include_sources=False,
        )
        return (zone or {}).get("payload", {}).get("name") or zone_id

    def _canonical_stream(self, value: str) -> str | None:
        normalized = normalize_term(value)
        if normalized in self._canonical_stream_cache:
            return self._canonical_stream_cache[normalized]
        exact = self.stream_aliases.get(normalized)
        if exact:
            self._canonical_stream_cache[normalized] = exact
            return exact
        matches = matching_collection_streams(value, list(self.streams.values()))
        result = matches[0]["stream_id"] if len(matches) == 1 else None
        self._canonical_stream_cache[normalized] = result
        return result

    def _channel_matches(self, value: str) -> list[dict[str, Any]]:
        normalized = normalize_term(value)
        if normalized not in self._channel_matches_cache:
            self._channel_matches_cache[normalized] = matching_delivery_channels(
                value, self.delivery_channels,
            )
        return self._channel_matches_cache[normalized]

    def _canonical_destination_key(self, value: str) -> str:
        normalized = normalize_term(value)
        if normalized in self._destination_key_cache:
            return self._destination_key_cache[normalized]
        stream_id = self._canonical_stream(value)
        if stream_id:
            result = stream_id
        else:
            channels = self._channel_matches(value)
            result = (
                channels[0]["channel_id"]
                if len(channels) == 1 and any(
                    normalized == normalize_term(alias)
                    for alias in channels[0]["matched_aliases"]
                )
                else normalized
            )
        self._destination_key_cache[normalized] = result
        return result

    def _concept_for_choice(self, choice_id: str) -> dict[str, Any] | None:
        if choice_id in self._concept_cache:
            return self._concept_cache[choice_id]
        class_outcome = self.class_outcomes.get(choice_id)
        if class_outcome is not None:
            waste_class, outcome = class_outcome
            mappings = self.family_mappings_by_class.get(waste_class["class_id"], [])
            if not mappings:
                return None
            mapping = {
                **mappings[0],
                "mapping_id": f"family-map:outcome-{choice_id.removeprefix('waste-outcome:')}",
                "reviewed_at": max(item["reviewed_at"] for item in mappings),
                "source_urls": sorted({
                    url for item in mappings for url in item.get("source_urls", [])
                }),
            }
            concept = self._apply_class_route({
                "concept_id": choice_id,
                "preferred_label": outcome["label"],
                "normalized_term": normalize_term(outcome["label"]),
                "terms": [outcome["label"]],
                "source_categories": [],
                "local_destinations": [],
                "evidence": [],
                "eer": {"status": "not_available", "candidates": []},
                "general_details": {"environmental_note": None},
            }, mapping, waste_class, outcome)
            self._concept_cache[choice_id] = concept
            return concept
        group = self.alias_groups.get(choice_id)
        if group is None:
            concept = read_entity_data(
                self.connection, "waste_concept", choice_id, include_sources=False,
            )
            if concept:
                concept = self._with_hazard_profiles(concept)
                concept = self._with_curated_eer(concept)
                concept = self._with_family_class(concept)
            self._concept_cache[choice_id] = concept
            return concept
        members = []
        for concept_id in group["member_concept_ids"]:
            member = read_entity_data(
                self.connection, "waste_concept", concept_id, include_sources=False,
            )
            if member is not None:
                member = self._with_hazard_profiles(member)
                member = self._with_curated_eer(member)
                members.append(self._with_family_class(member))
        destinations: dict[str, dict[str, Any]] = {}
        evidence = []
        terms = set()
        eer_candidates: dict[str, dict[str, Any]] = {}
        hazard_profile_ids = set()
        hazard_sources = []
        for member in members:
            terms.update(member.get("terms", []))
            for destination in member.get("local_destinations", []):
                key = normalize_term(destination["label"])
                aggregate = destinations.setdefault(key, {
                    "label": destination["label"],
                    "municipality_istats": set(),
                    "source_urls": set(),
                })
                aggregate["municipality_istats"].update(destination["municipality_istats"])
                aggregate["source_urls"].update(destination["source_urls"])
            evidence.extend(member.get("evidence", []))
            for candidate in member.get("eer", {}).get("candidates", []):
                eer_candidates.setdefault(candidate["code"], candidate)
            hazard_profile_ids.update(member.get("hazard_profile_ids", []))
            hazard_sources.extend(member.get("hazard_sources", []))
        candidates = [eer_candidates[code] for code in sorted(eer_candidates)]
        concept = {
            "concept_id": group["group_id"],
            "member_concept_ids": group["member_concept_ids"],
            "preferred_label": group["preferred_label"],
            "normalized_term": normalize_term(group["preferred_label"]),
            "terms": sorted(terms, key=lambda item: (item.casefold(), item)),
            "local_destinations": [
                {
                    "label": item["label"],
                    "municipality_istats": sorted(item["municipality_istats"]),
                    "source_urls": sorted(item["source_urls"]),
                }
                for _, item in sorted(destinations.items())
            ],
            "evidence": evidence,
            "eer": {
                "status": (
                    "source_consensus" if len(candidates) == 1
                    else "conflict" if candidates else "not_available"
                ),
                "candidates": candidates,
            },
            "general_details": {
                "environmental_note": next((
                    member.get("general_details", {}).get("environmental_note")
                    for member in members
                    if member.get("general_details", {}).get("environmental_note")
                ), None),
            },
            "hazard_profile_ids": sorted(hazard_profile_ids),
            "hazard_sources": hazard_sources,
        }
        if group.get("waste_class_id"):
            concept = self._with_explicit_family_class(
                concept, group["waste_class_id"],
            )
        self._concept_cache[choice_id] = concept
        return concept

    def _result(
        self,
        concept: dict[str, Any],
        destination: str,
        rule: dict[str, Any] | None,
        *,
        municipality_istat: str,
        zone_id: str | None,
        user_type: str,
        latitude: float | None,
        longitude: float | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        payload = (rule or {}).get("payload") or {}
        presentation = payload.get("presentation") or None
        instructions = []
        if presentation and presentation.get("instructions_raw"):
            instructions.append(presentation["instructions_raw"])
        eer = self._eer_summary(concept)
        warnings = []
        hazard_restricted = self._hazard_requires_separate_handling(concept)
        if hazard_restricted:
            warnings.append(
                "Il materiale richiede gestione separata: non conferirlo nelle "
                "raccolte generiche e verifica le condizioni del gestore."
            )
        if eer and eer.get("condition"):
            warnings.append(f"Il codice EER vale {eer['condition']}.")
        channels = self._channel_matches(destination)
        if rule is None and not channels:
            warnings.append("La destinazione e pubblicata, ma non e collegata a una regola di preparazione locale.")
        facilities = []
        facility_sources: list[dict[str, Any]] = []
        if any(channel["destination_type"] == "facility" for channel in channels):
            facilities, facility_sources = self._resolve_facilities(
                concept,
                destination,
                municipality_istat=municipality_istat,
                user_type=user_type,
                latitude=latitude,
                longitude=longitude,
            )
        selectable = [
            facility for facility in facilities
            if facility["acceptance"]["status"].startswith("verified_")
            and facility["operational_status"] not in {"closed", "temporarily_closed"}
        ]
        primary = None
        if len(selectable) == 1 or (selectable and latitude is not None):
            primary = selectable[0]
        elif selectable:
            acceptance_rank = {"verified_eer": 0, "verified_description": 1}
            status_rank = {"open": 0, "unknown": 1}
            best_quality = min(
                (
                    acceptance_rank[facility["acceptance"]["status"]],
                    status_rank.get(facility["operational_status"], 1),
                    not facility["_local"],
                )
                for facility in selectable
            )
            best = [
                facility for facility in selectable
                if (
                    acceptance_rank[facility["acceptance"]["status"]],
                    status_rank.get(facility["operational_status"], 1),
                    not facility["_local"],
                ) == best_quality
            ]
            if len(best) == 1:
                primary = best[0]
        for facility in facilities:
            facility.pop("_local", None)
        if channels and any(
            channel["destination_type"] == "facility" for channel in channels
        ):
            if not facilities:
                warnings.append("La fonte indica il centro di raccolta, ma non pubblica una struttura accessibile per questa utenza.")
            elif not selectable:
                warnings.append("Nessun centro accessibile ha una conferma pubblicata di accettazione per questo rifiuto.")
            elif primary is None:
                warnings.append("Sono disponibili piu centri compatibili: usa la posizione per ordinare quelli piu vicini.")
        channel_services, unresolved_channels, service_sources = self._resolve_channel_services(
            channels,
            concept,
            destination,
            municipality_istat=municipality_istat,
            zone_id=zone_id,
            user_type=user_type,
            latitude=latitude,
            longitude=longitude,
        )
        for channel in unresolved_channels:
            if channel["status"] == "not_published":
                warnings.append(
                    f"La fonte indica {channel['preferred_label'].casefold()}, "
                    "ma non pubblica un servizio operativo collegabile per questo comune."
                )
            elif channel["status"] == "acceptance_not_published":
                warnings.append(
                    f"Il servizio {channel['preferred_label'].casefold()} e pubblicato, "
                    "ma il suo elenco dei rifiuti accettati non e disponibile."
                )
            elif channel["status"] == "compatibility_not_verified":
                warnings.append(
                    f"Il servizio {channel['preferred_label'].casefold()} e pubblicato, "
                    "ma i dati non confermano che accetti questo rifiuto."
                )
        stream_id = (
            None if hazard_restricted
            else self._canonical_stream(payload.get("stream_name") or destination)
        )
        if channels:
            destination_type = (
                channels[0]["destination_type"] if len(channels) == 1 else "special_case"
            )
        else:
            destination_type = _destination_type(destination)
        stream = None if hazard_restricted else payload.get("stream_name")
        if stream is None and stream_id:
            stream = self.streams[stream_id]["preferred_label"]
        if stream is None and not channels:
            stream = destination
        result = {
            "destination_type": destination_type,
            "stream_id": stream_id,
            "stream": stream,
            "source_destination": destination,
            "channel_relation": (
                "alternatives" if len(channels) > 1 else "single" if channels else None
            ),
            "delivery_channels": channels,
            "container": (
                {
                    "type": payload.get("container_type"),
                    "color": payload.get("container_color"),
                    "access_credential": payload.get("access_credential"),
                }
                if rule and not hazard_restricted else None
            ),
            "presentation": (
                {"mode": presentation.get("mode") or "unspecified", "instructions": instructions}
                if presentation and not hazard_restricted else None
            ),
            "eer": eer,
            "facility": primary,
            "facility_alternatives": [
                facility for facility in facilities if facility is not primary
            ],
            "channel_services": channel_services,
            "unresolved_channels": unresolved_channels,
            "environmental_note": concept.get("general_details", {}).get("environmental_note"),
            "warnings": warnings,
            **self._hazard_metadata(concept),
        }
        return result, [*facility_sources, *service_sources]

    def _eer_summary(self, concept: dict[str, Any]) -> dict[str, Any] | None:
        candidates = concept.get("eer", {}).get("candidates", [])
        if concept.get("eer", {}).get("status") not in {
            "source_consensus", "curated_mapping",
        } or len(candidates) != 1:
            return None
        candidate = candidates[0]
        if candidate.get("register_status") == "unknown_code":
            return None
        source_labels = candidate.get("source_labels") or []
        return {
            "code": candidate["code"],
            "official_label": (
                candidate.get("official_title")
                or (source_labels[0] if source_labels else candidate["code"])
            ),
            "hazardous": self._candidate_is_hazardous(candidate),
            "facility_operational_label": source_labels[0] if source_labels else None,
            "condition": candidate.get("mapping_condition"),
        }

    def _facility_fallback(
        self,
        concept: dict[str, Any],
        *,
        municipality_istat: str,
        user_type: str,
        latitude: float | None,
        longitude: float | None,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        cache_key = (
            concept["concept_id"], municipality_istat, user_type,
            latitude, longitude,
        )
        if cache_key not in self._facility_fallback_cache:
            self._facility_fallback_cache[cache_key] = (
                self._facility_fallback_uncached(
                    concept,
                    municipality_istat=municipality_istat,
                    user_type=user_type,
                    latitude=latitude,
                    longitude=longitude,
                )
            )
        return self._facility_fallback_cache[cache_key]

    def _portable_route_fallback(
        self, concept: dict[str, Any],
    ) -> dict[str, Any] | None:
        hazard_restricted = self._hazard_requires_separate_handling(concept)
        streams = [
            {
                "stream_id": stream_id,
                "preferred_label": self.streams[stream_id]["preferred_label"],
            }
            for stream_id in concept.get("family_stream_ids", [])
            if stream_id in self.streams
        ] if not hazard_restricted else []
        channel_ids = set(concept.get("family_delivery_channel_ids", []))
        if hazard_restricted and not channel_ids:
            channel_ids = {
                "channel:collection-centre", "channel:specialist-operator",
            }
        channels = [
            {
                "channel_id": channel["channel_id"],
                "preferred_label": channel["preferred_label"],
                "destination_type": channel["destination_type"],
                "matched_aliases": [channel["preferred_label"]],
            }
            for channel in self.delivery_channels
            if channel["channel_id"] in channel_ids
        ]
        candidates = [
            candidate
            for candidate in concept.get("eer", {}).get("candidates", [])
            if candidate.get("register_status") != "unknown_code"
        ]
        eer_options = [
            summary
            for candidate in candidates
            for summary in [self._eer_from_code(
                candidate["code"], [],
                condition=candidate.get("mapping_condition"),
            )]
            if summary is not None
        ]
        if not streams and not channels and not eer_options:
            return None
        warning = (
            "Il materiale richiede gestione separata: non conferirlo nelle raccolte "
            "generiche e verifica le condizioni del gestore."
            if hazard_restricted else
            "La classificazione del rifiuto e definita, ma la fonte locale non "
            "pubblica una regola sufficiente per indicare contenitore, sacchetto "
            "o servizio. Verifica le istruzioni del gestore prima del conferimento."
        )
        return {
            "destination_type": "portable_route",
            "local_route_status": "not_published",
            "stream_id": streams[0]["stream_id"] if len(streams) == 1 else None,
            "stream": streams[0]["preferred_label"] if len(streams) == 1 else None,
            "stream_alternatives": streams if len(streams) > 1 else [],
            "source_destination": None,
            "channel_relation": "alternatives" if len(channels) > 1 else "single",
            "delivery_channels": channels,
            "container": None,
            "presentation": None,
            "eer": eer_options[0] if len(eer_options) == 1 else None,
            "eer_alternatives": eer_options if len(eer_options) > 1 else [],
            "facility": None,
            "facility_alternatives": [],
            "channel_services": [],
            "unresolved_channels": [
                {
                    "channel_id": channel["channel_id"],
                    "preferred_label": channel["preferred_label"],
                    "status": "local_service_not_verified",
                    "reason": "Nessun servizio locale compatibile e pubblicato.",
                    "source_destination": None,
                }
                for channel in channels
            ],
            "environmental_note": concept.get("general_details", {}).get(
                "environmental_note"
            ),
            "warnings": [warning],
            **self._hazard_metadata(concept),
        }

    def _portable_route_sources(self, concept: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = concept.get("eer", {}).get("candidates", [])
        candidate_urls = {
            url for candidate in candidates for url in candidate.get("source_urls", [])
        }
        return [
            *concept.get("family_sources", []),
            *concept.get("hazard_sources", []),
            *(
                concept.get("evidence", [])
                if self._hazard_requires_separate_handling(concept) else []
            ),
            *[
                source
                for candidate in candidates
                for source in candidate.get("mapping_sources", [])
            ],
            *[
                evidence for evidence in concept.get("evidence", [])
                if evidence.get("source_url") in candidate_urls
            ],
        ]

    def _facility_fallback_uncached(
        self,
        concept: dict[str, Any],
        *,
        municipality_istat: str,
        user_type: str,
        latitude: float | None,
        longitude: float | None,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        eer = self._eer_summary(concept)
        candidate_by_code = {
            candidate["code"]: candidate
            for candidate in concept.get("eer", {}).get("candidates", [])
            if candidate.get("register_status") != "unknown_code"
        }
        facilities, sources = self._resolve_facilities(
            concept,
            "Centro di raccolta",
            municipality_istat=municipality_istat,
            user_type=user_type,
            latitude=latitude,
            longitude=longitude,
            allow_term_match=True,
        )
        if eer is not None:
            verified_by_eer = [
                facility for facility in facilities
                if facility["acceptance"]["status"] == "verified_eer"
            ]
            verified_by_description = [
                facility for facility in facilities
                if facility["acceptance"]["status"] == "verified_description"
            ]
            verified = verified_by_eer or verified_by_description
            resolution_basis = (
                "exact_eer" if verified_by_eer
                else "curated_eer_with_facility_description"
            )
        elif candidate_by_code:
            verified = [
                facility for facility in facilities
                if facility["acceptance"]["status"] == "verified_eer"
            ]
            accepted_codes = {
                code for facility in verified
                for code in facility["acceptance"]["eer_codes"]
                if code in candidate_by_code
            }
            if len(accepted_codes) != 1:
                return self._special_channel_fallback(
                    concept, eer, sources,
                    municipality_istat=municipality_istat,
                    user_type=user_type,
                    latitude=latitude,
                    longitude=longitude,
                )
            code = next(iter(accepted_codes))
            candidate = candidate_by_code[code]
            eer = self._eer_from_code(
                code, verified, condition=candidate.get("mapping_condition"),
            )
            if eer is None:
                return None, sources
            verified = [
                facility for facility in verified
                if code in facility["acceptance"]["eer_codes"]
            ]
            sources.extend(candidate.get("mapping_sources", []))
            resolution_basis = "locally_accepted_eer"
        else:
            verified = [
                facility for facility in facilities
                if facility["acceptance"]["status"] == "verified_description"
                and len(facility["acceptance"]["eer_codes"]) == 1
            ]
            codes = {
                code for facility in verified
                for code in facility["acceptance"]["eer_codes"]
            }
            if len(codes) != 1:
                return self._special_channel_fallback(
                    concept, eer, sources,
                    municipality_istat=municipality_istat,
                    user_type=user_type,
                    latitude=latitude,
                    longitude=longitude,
                )
            eer = self._eer_from_code(next(iter(codes)), verified)
            if eer is None:
                return None, sources
            resolution_basis = "facility_description"
        if (
            eer is not None
            and self._hazard_requires_separate_handling(concept)
            and not eer.get("hazardous")
        ):
            return self._special_channel_fallback(
                concept, None, sources,
                municipality_istat=municipality_istat,
                user_type=user_type,
                latitude=latitude,
                longitude=longitude,
            )
        if not verified:
            return self._special_channel_fallback(
                concept, eer, sources,
                municipality_istat=municipality_istat,
                user_type=user_type,
                latitude=latitude,
                longitude=longitude,
            )
        selectable = [
            facility for facility in verified
            if facility["operational_status"] not in {"closed", "temporarily_closed"}
        ]
        primary = None
        if len(selectable) == 1 or (selectable and latitude is not None):
            primary = selectable[0]
        elif selectable:
            local = [facility for facility in selectable if facility["_local"]]
            if len(local) == 1:
                primary = local[0]
        if resolution_basis == "exact_eer":
            warnings = [
                "La fonte locale non pubblica questo oggetto nel rifiutario: "
                f"il centro \u00e8 stato individuato tramite l'accettazione esatta del codice EER {eer['code']}."
            ]
        elif resolution_basis == "locally_accepted_eer":
            warnings = [
                "L'oggetto puo avere piu classificazioni EER secondo la sua origine: "
                f"il centro locale pubblica l'accettazione del codice {eer['code']}"
                + (f" ({eer['condition']})." if eer.get("condition") else ".")
            ]
        elif resolution_basis == "facility_description":
            warnings = [
                "La fonte locale non pubblica un rifiutario: il collegamento deriva "
                f"dalla descrizione del materiale associata dal centro al codice EER {eer['code']}."
            ]
        else:
            warnings = [
                "Il centro pubblica l'accettazione del materiale ma non il relativo "
                f"codice EER: la classificazione {eer['code']} deriva dal vocabolario "
                "revisionato e non viene attribuita alla fonte locale."
            ]
        if not selectable:
            warnings.append(
                "I centri che pubblicano questo codice risultano chiusi o temporaneamente chiusi."
            )
        elif primary is None:
            warnings.append(
                "Sono disponibili piu centri compatibili: usa la posizione per ordinare quelli piu vicini."
            )
        if self._hazard_requires_separate_handling(concept):
            warnings.insert(
                0,
                "Il materiale richiede gestione separata: non conferirlo nelle "
                "raccolte generiche.",
            )
        for facility in verified:
            facility.pop("_local", None)
        destination_labels = candidate_by_code.get(eer["code"], {}).get(
            "mapping_delivery_channels", [],
        ) or ["Centro di raccolta"]
        source_destination = ", ".join(destination_labels)
        channels = self._channel_matches(source_destination)
        channel_services, unresolved_channels, service_sources = (
            self._resolve_channel_services(
                channels,
                concept,
                source_destination,
                municipality_istat=municipality_istat,
                zone_id=None,
                user_type=user_type,
                latitude=latitude,
                longitude=longitude,
            )
        )
        sources.extend(service_sources)
        eer_alternatives = []
        for code, candidate in sorted(candidate_by_code.items()):
            if code == eer["code"]:
                continue
            alternative = self._eer_from_code(
                code, [], condition=candidate.get("mapping_condition"),
            )
            if alternative is not None:
                eer_alternatives.append(alternative)
        return {
            "destination_type": (
                channels[0]["destination_type"] if len(channels) == 1
                else "special_case"
            ),
            "stream_id": None,
            "stream": None,
            "source_destination": source_destination,
            "channel_relation": "alternatives" if len(channels) > 1 else "single",
            "delivery_channels": channels,
            "container": None,
            "presentation": None,
            "eer": eer,
            "eer_alternatives": eer_alternatives,
            "facility": primary,
            "facility_alternatives": [
                facility for facility in verified if facility is not primary
            ],
            "channel_services": channel_services,
            "unresolved_channels": unresolved_channels,
            "environmental_note": concept.get("general_details", {}).get(
                "environmental_note"
            ),
            "warnings": warnings,
            **self._hazard_metadata(concept),
        }, sources

    def _special_channel_fallback(
        self,
        concept: dict[str, Any],
        eer: dict[str, Any] | None,
        sources: list[dict[str, Any]],
        *,
        municipality_istat: str,
        user_type: str,
        latitude: float | None,
        longitude: float | None,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        channel_ids = set(concept.get("family_delivery_channel_ids", []))
        channels = [
            {
                "channel_id": channel["channel_id"],
                "preferred_label": channel["preferred_label"],
                "destination_type": channel["destination_type"],
                "matched_aliases": [channel["preferred_label"]],
            }
            for channel in self.delivery_channels
            if channel["channel_id"] in channel_ids
            and channel["destination_type"] == "special_case"
        ]
        if not channels:
            return None, sources
        if eer is None:
            candidates = [
                candidate
                for candidate in concept.get("eer", {}).get("candidates", [])
                if candidate.get("register_status") != "unknown_code"
            ]
            if len(candidates) == 1:
                eer = self._eer_from_code(
                    candidates[0]["code"], [],
                    condition=candidates[0].get("mapping_condition"),
                )
        source_destination = ", ".join(
            channel["preferred_label"] for channel in channels
        )
        channel_services, unresolved_channels, service_sources = (
            self._resolve_channel_services(
                channels,
                concept,
                source_destination,
                municipality_istat=municipality_istat,
                zone_id=None,
                user_type=user_type,
                latitude=latitude,
                longitude=longitude,
            )
        )
        warnings = [
            "Nessun centro accessibile pubblica l'accettazione di questo codice EER. "
            "Segui il canale speciale indicato e verifica preventivamente le condizioni."
        ]
        if self._hazard_requires_separate_handling(concept):
            warnings.insert(
                0,
                "Il materiale richiede gestione separata: non conferirlo nelle "
                "raccolte generiche.",
            )
        return {
            "destination_type": "special_case",
            "stream_id": None,
            "stream": None,
            "source_destination": source_destination,
            "channel_relation": "alternatives" if len(channels) > 1 else "single",
            "delivery_channels": channels,
            "container": None,
            "presentation": None,
            "eer": eer,
            "eer_alternatives": [],
            "facility": None,
            "facility_alternatives": [],
            "channel_services": channel_services,
            "unresolved_channels": unresolved_channels,
            "environmental_note": concept.get("general_details", {}).get(
                "environmental_note"
            ),
            "warnings": warnings,
            **self._hazard_metadata(concept),
        }, [
            *sources,
            *concept.get("family_sources", []),
            *concept.get("hazard_sources", []),
            *service_sources,
        ]

    def _eer_from_code(
        self, code: str, facilities: list[dict[str, Any]], *, condition: str | None = None,
    ) -> dict[str, Any] | None:
        entry = self._eer_entry(code)
        if entry is None:
            return None
        labels = sorted({
            label for facility in facilities
            for label in facility["acceptance"]["labels"]
        })
        return {
            "code": code,
            "official_label": entry.get("title_expanded") or entry.get("title"),
            "hazardous": bool(entry.get("hazardous")),
            "facility_operational_label": labels[0] if labels else None,
            "condition": condition,
        }

    def _eer_entry(self, code: str) -> dict[str, Any] | None:
        if code not in self._eer_entry_cache:
            self._eer_entry_cache[code] = read_entity_data(
                self.connection, "eer_entry", f"eer:{code}",
                include_sources=False,
            )
        return self._eer_entry_cache[code]

    def _candidate_is_hazardous(self, candidate: dict[str, Any]) -> bool:
        entry = self._eer_entry(candidate["code"])
        if entry is not None and entry.get("hazardous") is not None:
            return bool(entry["hazardous"])
        if candidate.get("official_hazardous") is not None:
            return bool(candidate["official_hazardous"])
        return bool(candidate.get("hazardous"))

    def _resolve_facilities(
        self,
        concept: dict[str, Any],
        source_destination: str,
        *,
        municipality_istat: str,
        user_type: str,
        latitude: float | None,
        longitude: float | None,
        allow_term_match: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        access_key = (municipality_istat, user_type)
        if access_key not in self._facility_access_cache:
            access_by_facility: dict[str, list[dict[str, Any]]] = {}
            for row in self.connection.execute(
                """SELECT entity_id, facility_ref FROM entities
                WHERE entity_type = 'facility_access' AND municipality_ref = ?
                ORDER BY facility_ref, entity_id""",
                (f"istat:{municipality_istat}",),
            ):
                access = read_entity_data(
                    self.connection, "facility_access", row["entity_id"],
                )
                payload = (access or {}).get("payload") or {}
                if (
                    access
                    and payload.get("allowed") is True
                    and payload.get("user_type") in {"all", user_type}
                ):
                    access_by_facility.setdefault(
                        row["facility_ref"], [],
                    ).append(access)
            self._facility_access_cache[access_key] = access_by_facility
        access_by_facility = self._facility_access_cache[access_key]

        candidates = []
        sources = []
        for facility_id, accesses in access_by_facility.items():
            if facility_id not in self._facility_entity_cache:
                self._facility_entity_cache[facility_id] = read_entity_data(
                    self.connection, "facility", facility_id,
                )
            facility = self._facility_entity_cache[facility_id]
            if facility is None:
                continue
            payload = facility.get("payload") or {}
            acceptance, acceptance_sources = self._facility_acceptance(
                facility_id, concept, source_destination, user_type,
                allow_term_match=allow_term_match,
            )
            periods, period_sources = self._facility_opening_periods(facility_id)
            access_payloads = [access.get("payload") or {} for access in accesses]
            raw_location = payload.get("location") or {}
            location = (
                {
                    "latitude": raw_location["latitude"],
                    "longitude": raw_location["longitude"],
                    "method": raw_location.get("method") or "unknown",
                    "accuracy_m": raw_location.get("accuracy_m"),
                }
                if raw_location.get("latitude") is not None
                and raw_location.get("longitude") is not None
                else None
            )
            distance = None
            if latitude is not None and location:
                distance = _distance_km(
                    latitude, longitude,
                    location.get("latitude"), location.get("longitude"),
                )
            booking_values = {
                item.get("booking_required") for item in access_payloads
                if item.get("booking_required") is not None
            }
            booking_required = (
                True if True in booking_values else False if booking_values == {False} else None
            )
            information_urls = sorted({
                url for item in access_payloads for url in item.get("information_urls", [])
            })
            access_summary = next((
                item.get("requirements_raw") for item in access_payloads
                if item.get("requirements_raw")
            ), None)
            raw_status = payload.get("operational_status") or "unknown"
            operational_status = "open" if raw_status == "active" else raw_status
            if operational_status not in {
                "open", "closed", "temporarily_closed", "unknown",
            }:
                operational_status = "unknown"
            candidate = {
                "id": facility_id,
                "name": payload.get("name") or facility_id,
                "address": payload.get("address_raw"),
                "location": location,
                "distance_km": round(distance, 2) if distance is not None else None,
                "operational_status": operational_status,
                "status_raw": payload.get("status_raw") or (
                    raw_status if raw_status != operational_status else None
                ),
                "access_summary": access_summary,
                "booking_required": booking_required,
                "phone": next((
                    item.get("contact_phone") for item in access_payloads
                    if item.get("contact_phone")
                ), payload.get("phone")),
                "email": next((
                    item.get("contact_email") for item in access_payloads
                    if item.get("contact_email")
                ), payload.get("email")),
                "information_urls": information_urls,
                "opening_periods": periods,
                "acceptance": acceptance,
                "_local": payload.get("municipality_ref") == f"istat:{municipality_istat}",
            }
            candidates.append(candidate)
            sources.extend(facility.get("sources", []))
            sources.extend(source for access in accesses for source in access.get("sources", []))
            sources.extend(acceptance_sources)
            sources.extend(period_sources)

        acceptance_rank = {
            "verified_eer": 0,
            "verified_description": 1,
            "acceptance_not_published": 2,
            "not_listed": 3,
        }
        status_rank = {"open": 0, "unknown": 1, "temporarily_closed": 2, "closed": 3}
        candidates.sort(key=lambda item: (
            acceptance_rank[item["acceptance"]["status"]],
            status_rank.get(item["operational_status"], 1),
            item["distance_km"] if item["distance_km"] is not None else float("inf"),
            not item["_local"],
            item["name"].casefold(),
        ))
        return candidates, sources

    def _facility_acceptance(
        self,
        facility_id: str,
        concept: dict[str, Any],
        source_destination: str,
        user_type: str,
        *,
        allow_term_match: bool = False,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        cache_key = (facility_id, user_type)
        if cache_key not in self._facility_acceptance_items_cache:
            accepted = []
            sources = []
            for row in self.connection.execute(
                """SELECT entity_id FROM entities
                WHERE entity_type = 'facility_acceptance' AND facility_ref = ?
                ORDER BY entity_id""",
                (facility_id,),
            ):
                item = read_entity_data(
                    self.connection, "facility_acceptance", row["entity_id"],
                )
                payload = (item or {}).get("payload") or {}
                if item and payload.get("user_type") in {
                    None, "all", "unspecified", user_type,
                }:
                    accepted.append(item)
                    sources.extend(item.get("sources", []))
            self._facility_acceptance_items_cache[cache_key] = accepted, sources
        accepted, sources = self._facility_acceptance_items_cache[cache_key]
        if not accepted:
            return {
                "status": "acceptance_not_published",
                "basis": None,
                "eer_codes": [],
                "labels": [],
                "conditions": [],
            }, sources

        concept_codes = {
            candidate["code"] for candidate in concept.get("eer", {}).get("candidates", [])
        }
        concept_terms = {
            normalize_term(term) for term in [
                concept.get("preferred_label", ""), *concept.get("terms", []),
                *concept.get("family_acceptance_terms", []),
            ] if normalize_term(term)
        }
        normalized_destination = normalize_term(source_destination)
        matches = []
        basis = None
        for item in accepted:
            payload = item["payload"]
            code = payload.get("eer_code_normalized")
            description = normalize_term(payload.get("description_raw") or "")
            item_basis = None
            if code and code in concept_codes:
                item_basis = "eer"
            elif description and (
                description in concept_terms
                or any(
                    min(len(description), len(term)) >= 5
                    and (description in term or term in description)
                    for term in concept_terms
                )
                or f" {description} " in f" {normalized_destination} "
                or allow_term_match and _description_matches_terms(
                    description, concept_terms,
                )
            ):
                item_basis = "description"
            if item_basis:
                matches.append(item)
                basis = "eer" if item_basis == "eer" else basis or "description"
        if not matches:
            return {
                "status": "not_listed",
                "basis": None,
                "eer_codes": [],
                "labels": [],
                "conditions": [],
            }, sources
        return {
            "status": "verified_eer" if basis == "eer" else "verified_description",
            "basis": basis,
            "eer_codes": sorted({
                item["payload"].get("eer_code_normalized") for item in matches
                if item["payload"].get("eer_code_normalized")
            }),
            "labels": sorted({item["payload"]["description_raw"] for item in matches}),
            "conditions": sorted({
                value for item in matches
                for value in (
                    item["payload"].get("quantity_limit_raw"),
                    item["payload"].get("notes_raw"),
                ) if value
            }),
        }, sources

    def _facility_opening_periods(
        self, facility_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if facility_id in self._facility_opening_cache:
            return self._facility_opening_cache[facility_id]
        periods = []
        sources = []
        for row in self.connection.execute(
            """SELECT entity_id FROM entities
            WHERE entity_type = 'opening_period' AND facility_ref = ?
            ORDER BY entity_id""",
            (facility_id,),
        ):
            item = read_entity_data(self.connection, "opening_period", row["entity_id"])
            if item:
                payload = item.get("payload") or {}
                periods.append({
                    "period_label": payload.get("period_label"),
                    "start_month_day": payload.get("start_month_day"),
                    "end_month_day": payload.get("end_month_day"),
                    "weekly_intervals": payload.get("weekly_intervals", []),
                    "exceptions": payload.get("exceptions_raw"),
                })
                sources.extend(item.get("sources", []))
        self._facility_opening_cache[facility_id] = periods, sources
        return periods, sources

    def _resolve_channel_services(
        self,
        channels: list[dict[str, Any]],
        concept: dict[str, Any],
        source_destination: str,
        *,
        municipality_istat: str,
        zone_id: str | None,
        user_type: str,
        latitude: float | None,
        longitude: float | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        services = []
        unresolved = []
        sources = []
        for channel in channels:
            channel_id = channel["channel_id"]
            if channel_id == "channel:collection-centre":
                continue
            if channel_id == "channel:home-pickup":
                found, found_sources = self._pickup_services(
                    channel, concept, source_destination,
                    municipality_istat=municipality_istat,
                    zone_id=zone_id,
                    user_type=user_type,
                )
            elif channel_id in {
                "channel:mobile-collection", "channel:collection-point",
            }:
                found, found_sources = self._collection_point_services(
                    channel, concept, source_destination,
                    municipality_istat=municipality_istat,
                    zone_id=zone_id,
                    latitude=latitude,
                    longitude=longitude,
                )
            else:
                unresolved.append({
                    "channel_id": channel_id,
                    "preferred_label": channel["preferred_label"],
                    "status": "source_only",
                    "reason": "La fonte indica il canale ma non pubblica un'entita operativa strutturata.",
                    "source_destination": source_destination,
                })
                continue
            services.extend(found)
            sources.extend(found_sources)
            if not found:
                unresolved.append({
                    "channel_id": channel_id,
                    "preferred_label": channel["preferred_label"],
                    "status": "not_published",
                    "reason": "Nessun servizio territoriale compatibile con il canale e pubblicato nei dati correnti.",
                    "source_destination": source_destination,
                })
            elif not any(
                service["compatibility"] == "verified_description" for service in found
            ):
                only_unpublished = all(
                    service["compatibility"] == "acceptance_not_published"
                    for service in found
                )
                unresolved.append({
                    "channel_id": channel_id,
                    "preferred_label": channel["preferred_label"],
                    "status": (
                        "acceptance_not_published" if only_unpublished
                        else "compatibility_not_verified"
                    ),
                    "reason": (
                        "Il servizio e pubblicato senza un elenco dei rifiuti accettati."
                        if only_unpublished
                        else "Il servizio e pubblicato ma non e collegabile al rifiuto con i dati correnti."
                    ),
                    "source_destination": source_destination,
                })
        services.sort(key=lambda item: (
            {"verified_description": 0, "acceptance_not_published": 1, "not_verified": 2}[
                item["compatibility"]
            ],
            item["distance_km"] if item["distance_km"] is not None else float("inf"),
            (item["name"] or item["address"] or item["id"]).casefold(),
        ))
        return services, unresolved, sources

    def _pickup_services(
        self,
        channel: dict[str, Any],
        concept: dict[str, Any],
        source_destination: str,
        *,
        municipality_istat: str,
        zone_id: str | None,
        user_type: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        services = []
        sources = []
        for row in self.connection.execute(
            """SELECT entity_id FROM entities
            WHERE entity_type = 'pickup_service' AND municipality_ref = ?
            ORDER BY entity_id""",
            (f"istat:{municipality_istat}",),
        ):
            item = read_entity_data(self.connection, "pickup_service", row["entity_id"])
            payload = (item or {}).get("payload") or {}
            if not item or payload.get("user_type") not in {"all", user_type}:
                continue
            if zone_id and payload.get("zone_ref") not in {None, zone_id}:
                continue
            accepted = [payload.get("accepted_waste_raw")] if payload.get("accepted_waste_raw") else []
            compatibility = self._service_compatibility(
                concept,
                source_destination,
                accepted,
                payload.get("placement_instructions_raw"),
            )
            services.append({
                "id": row["entity_id"],
                "channel_id": channel["channel_id"],
                "service_type": "pickup",
                "zone_id": payload.get("zone_ref"),
                "name": channel["preferred_label"],
                "address": None,
                "location": None,
                "distance_km": None,
                "point_type": None,
                "accepted_waste": accepted,
                "compatibility": compatibility,
                "schedule_raw": None,
                "access_summary": None,
                "access_credential": None,
                "information_urls": [
                    method["value"] for method in payload.get("booking_methods", [])
                    if method.get("method") == "web"
                ],
                "booking_required": payload.get("booking_required"),
                "booking_methods": payload.get("booking_methods", []),
                "max_items": payload.get("max_items"),
                "quantity_limit": payload.get("quantity_limit_raw"),
                "instructions": payload.get("placement_instructions_raw"),
            })
            sources.extend(item.get("sources", []))
        return services, sources

    def _collection_point_services(
        self,
        channel: dict[str, Any],
        concept: dict[str, Any],
        source_destination: str,
        *,
        municipality_istat: str,
        zone_id: str | None,
        latitude: float | None,
        longitude: float | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        services = []
        sources = []
        wants_mobile = channel["channel_id"] == "channel:mobile-collection"
        for row in self.connection.execute(
            """SELECT entity_id FROM entities
            WHERE entity_type = 'collection_point' AND municipality_ref = ?
            ORDER BY entity_id""",
            (f"istat:{municipality_istat}",),
        ):
            item = read_entity_data(self.connection, "collection_point", row["entity_id"])
            payload = (item or {}).get("payload") or {}
            if not item or (payload.get("point_type") == "mobile") != wants_mobile:
                continue
            if zone_id and payload.get("zone_ref") not in {None, zone_id}:
                continue
            raw_location = payload.get("location") or {}
            location = (
                {
                    "latitude": raw_location["latitude"],
                    "longitude": raw_location["longitude"],
                    "method": raw_location.get("method") or "unknown",
                    "accuracy_m": raw_location.get("accuracy_m"),
                }
                if raw_location.get("latitude") is not None
                and raw_location.get("longitude") is not None
                else None
            )
            distance = None
            if latitude is not None and location:
                distance = _distance_km(
                    latitude, longitude,
                    location["latitude"], location["longitude"],
                )
            accepted = payload.get("accepted_streams", [])
            compatibility = self._service_compatibility(
                concept, source_destination, accepted, payload.get("access_notes_raw"),
            )
            if any("materiali indicati nella scheda" in normalize_term(value) for value in accepted):
                compatibility = "acceptance_not_published"
            services.append({
                "id": row["entity_id"],
                "channel_id": channel["channel_id"],
                "service_type": "collection_point",
                "zone_id": payload.get("zone_ref"),
                "name": payload.get("name"),
                "address": payload.get("address_raw"),
                "location": location,
                "distance_km": round(distance, 2) if distance is not None else None,
                "point_type": payload.get("point_type"),
                "accepted_waste": accepted,
                "compatibility": compatibility,
                "schedule_raw": payload.get("opening_hours_raw"),
                "access_summary": payload.get("access_notes_raw"),
                "access_credential": payload.get("access_credential"),
                "information_urls": payload.get("information_urls", []),
                "booking_required": None,
                "booking_methods": [],
                "max_items": None,
                "quantity_limit": None,
                "instructions": None,
            })
            sources.extend(item.get("sources", []))
        return services, sources

    @staticmethod
    def _service_compatibility(
        concept: dict[str, Any],
        source_destination: str,
        accepted_values: list[str],
        details: str | None,
    ) -> str:
        if not accepted_values:
            return "acceptance_not_published"
        accepted_text = normalize_term(" ".join(accepted_values))
        detail_text = normalize_term(details or "")
        terms = {
            normalize_term(term) for term in [
                concept.get("preferred_label", ""), *concept.get("terms", []),
            ] if len(normalize_term(term)) >= 5
        }
        if any(
            f" {term} " in f" {accepted_text} {detail_text} " for term in terms
        ):
            return "verified_description"
        generic_words = {
            "centro", "conferimento", "domicilio", "domiciliare", "ecocentro",
            "ecofurgone", "ecomobile", "ecologica", "raccolta", "ritiro",
            "servizio", "stazione", "appuntamento",
        }
        destination_words = {
            word for word in normalize_term(source_destination).split()
            if len(word) >= 5 and word not in generic_words
        }
        accepted_words = set(accepted_text.split())
        if destination_words & accepted_words:
            return "verified_description"
        return "not_verified"

    def _set_provenance(self, answer: dict[str, Any], sources: list[dict[str, Any]]) -> None:
        summarized = []
        seen = set()
        for source in sources:
            item = _source_summary(source)
            if item and (item["url"], item["retrieved_at"]) not in seen:
                summarized.append(item)
                seen.add((item["url"], item["retrieved_at"]))
        answer["provenance"]["sources"] = summarized
        answer["provenance"]["verified_at"] = max(
            (item["retrieved_at"] for item in summarized), default=None,
        )
