from __future__ import annotations

from datetime import date
from difflib import SequenceMatcher
import json
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
import sqlite3
from typing import Any

from .catalog import normalize_term
from .curation import matching_delivery_channels
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
        self._concept_cache: dict[str, dict[str, Any] | None] = {}
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
                "register_status": "active_in_target" if entry else "unknown_code",
                "valid_to": None,
                "mapping_condition": mapping.get("condition"),
                "mapping_id": mapping["mapping_id"],
            }
            for concept_id in mapping.get("concept_ids", []):
                self.eer_mappings.setdefault(concept_id, []).append(candidate)

    def _with_curated_eer(self, concept: dict[str, Any]) -> dict[str, Any]:
        mappings = self.eer_mappings.get(concept["concept_id"], [])
        if not mappings:
            return concept
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
        return result

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
                -item["score"],
                not item.get("available_in_municipality", False),
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
        suggestions = self.search(text, municipality_istat=municipality_istat, limit=6)
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
                item for item in suggestions if item.get("available_in_municipality")
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
        destinations = []
        for destination in concept.get("local_destinations", []):
            if municipality_istat in destination["municipality_istats"]:
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
        self._set_provenance(base, evidence)
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
                    *concept.get("evidence", []), *fallback_sources,
                ])
            return base
        if len(destinations) > 1:
            base["status"] = "conflict"
            base["question"] = {
                "text": "Le fonti pubblicano piu destinazioni per questo rifiuto.",
                "options": [
                    {"id": normalize_term(item["label"]).replace(" ", "-"), "label": item["label"]}
                    for item in destinations
                ],
            }
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
    ) -> list[dict[str, Any]]:
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
        return sorted(candidates, key=lambda item: (
            -item["_score"],
            item["payload"].get("zone_ref") or "",
            item.get("natural_key", ""),
        ))

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
        return self.stream_aliases.get(normalize_term(value))

    def _channel_matches(self, value: str) -> list[dict[str, Any]]:
        return matching_delivery_channels(value, self.delivery_channels)

    def _canonical_destination_key(self, value: str) -> str:
        stream_id = self._canonical_stream(value)
        if stream_id:
            return stream_id
        channels = self._channel_matches(value)
        if len(channels) == 1 and any(
            normalize_term(value) == normalize_term(alias)
            for alias in channels[0]["matched_aliases"]
        ):
            return channels[0]["channel_id"]
        return normalize_term(value)

    def _concept_for_choice(self, choice_id: str) -> dict[str, Any] | None:
        if choice_id in self._concept_cache:
            return self._concept_cache[choice_id]
        group = self.alias_groups.get(choice_id)
        if group is None:
            concept = read_entity_data(
                self.connection, "waste_concept", choice_id, include_sources=False,
            )
            if concept:
                concept = self._with_curated_eer(concept)
            self._concept_cache[choice_id] = concept
            return concept
        members = []
        for concept_id in group["member_concept_ids"]:
            member = read_entity_data(
                self.connection, "waste_concept", concept_id, include_sources=False,
            )
            if member is not None:
                members.append(self._with_curated_eer(member))
        destinations: dict[str, dict[str, Any]] = {}
        evidence = []
        terms = set()
        eer_candidates: dict[str, dict[str, Any]] = {}
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
        }
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
        stream_id = self._canonical_stream(payload.get("stream_name") or destination)
        if channels:
            destination_type = (
                channels[0]["destination_type"] if len(channels) == 1 else "special_case"
            )
        else:
            destination_type = _destination_type(destination)
        stream = payload.get("stream_name")
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
                if rule else None
            ),
            "presentation": (
                {"mode": presentation.get("mode") or "unspecified", "instructions": instructions}
                if presentation else None
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
        }
        return result, [*facility_sources, *service_sources]

    @staticmethod
    def _eer_summary(concept: dict[str, Any]) -> dict[str, Any] | None:
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
            "hazardous": bool(
                candidate.get("official_hazardous") or candidate.get("hazardous")
            ),
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
        eer = self._eer_summary(concept)
        facilities, sources = self._resolve_facilities(
            concept,
            "Centro di raccolta",
            municipality_istat=municipality_istat,
            user_type=user_type,
            latitude=latitude,
            longitude=longitude,
            allow_term_match=eer is None,
        )
        if eer is not None:
            verified = [
                facility for facility in facilities
                if facility["acceptance"]["status"] == "verified_eer"
            ]
            resolution_basis = "exact_eer"
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
                return None, sources
            eer = self._eer_from_code(next(iter(codes)), verified)
            if eer is None:
                return None, sources
            resolution_basis = "facility_description"
        if not verified:
            return None, sources
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
        else:
            warnings = [
                "La fonte locale non pubblica un rifiutario: il collegamento deriva "
                f"dalla descrizione del materiale associata dal centro al codice EER {eer['code']}."
            ]
        if not selectable:
            warnings.append(
                "I centri che pubblicano questo codice risultano chiusi o temporaneamente chiusi."
            )
        elif primary is None:
            warnings.append(
                "Sono disponibili piu centri compatibili: usa la posizione per ordinare quelli piu vicini."
            )
        for facility in verified:
            facility.pop("_local", None)
        channels = self._channel_matches("Centro di raccolta")
        return {
            "destination_type": "facility",
            "stream_id": None,
            "stream": None,
            "source_destination": f"Centro di raccolta tramite codice EER {eer['code']}",
            "channel_relation": "single",
            "delivery_channels": channels,
            "container": None,
            "presentation": None,
            "eer": eer,
            "facility": primary,
            "facility_alternatives": [
                facility for facility in verified if facility is not primary
            ],
            "channel_services": [],
            "unresolved_channels": [],
            "environmental_note": concept.get("general_details", {}).get(
                "environmental_note"
            ),
            "warnings": warnings,
        }, sources

    def _eer_from_code(
        self, code: str, facilities: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        entry = read_entity_data(
            self.connection, "eer_entry", f"eer:{code}", include_sources=False,
        )
        if entry is None:
            return None
        labels = sorted({
            label for facility in facilities
            for label in facility["acceptance"]["labels"]
        })
        return {
            "code": code,
            "official_label": entry["title_expanded"] or entry["title"],
            "hazardous": bool(entry["hazardous"]),
            "facility_operational_label": labels[0] if labels else None,
        }

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
                access_by_facility.setdefault(row["facility_ref"], []).append(access)

        candidates = []
        sources = []
        for facility_id, accesses in access_by_facility.items():
            facility = read_entity_data(self.connection, "facility", facility_id)
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
