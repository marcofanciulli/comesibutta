from __future__ import annotations

from datetime import date
from difflib import SequenceMatcher
import json
from pathlib import Path
import sqlite3
from typing import Any

from .catalog import normalize_term
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
    token_fuzzy = sum(
        max(SequenceMatcher(None, token, other).ratio() for other in candidate_tokens)
        for token in query_tokens
    ) / len(query_tokens)
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
        ranked = sorted(
            best.values(),
            key=lambda item: (-item["score"], len(item["normalized_term"]), item["label"].casefold()),
        )
        if municipality_istat:
            for candidate in ranked[: max(limit * 4, 20)]:
                concept = read_entity_data(
                    self.connection, "waste_concept", candidate["concept_id"],
                    include_sources=False,
                )
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
    ) -> dict[str, Any]:
        if len(municipality_istat) != 6 or not municipality_istat.isdigit():
            raise ValueError("Municipality ISTAT code must contain six digits")
        if user_type not in {"domestic", "non_domestic"}:
            raise ValueError("User type must be domestic or non_domestic")
        as_of = as_of or date.today()
        suggestions = self.search(text, municipality_istat=municipality_istat, limit=6)
        if concept_id:
            selected_concept = read_entity_data(
                self.connection, "waste_concept", concept_id, include_sources=False,
            )
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
        concept = read_entity_data(
            self.connection, "waste_concept", selected["concept_id"],
            include_sources=False,
        )
        if concept is None:
            return base
        base["query"].update({
            "matched_concept_id": concept["concept_id"],
            "matched_label": concept["preferred_label"],
        })
        destinations = []
        for destination in concept.get("local_destinations", []):
            if municipality_istat in destination["municipality_istats"]:
                key = normalize_term(destination["label"])
                if key not in {normalize_term(item["label"]) for item in destinations}:
                    destinations.append(destination)
        evidence = [
            item for item in concept.get("evidence", [])
            if municipality_istat in item.get("municipality_istats", [])
        ]
        self._set_provenance(base, evidence)
        if not destinations:
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
        if rule:
            self._set_provenance(base, [*evidence, *rule.get("sources", [])])
        base["status"] = "resolved"
        base["result"] = self._result(concept, destination, rule)
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
            score = _similarity(normalize_term(destination), normalize_term(row["stream_name"] or ""))
            if score < 0.45:
                continue
            data = read_entity_data(self.connection, "collection_rule", row["entity_id"])
            if data is None:
                continue
            payload = data.get("payload") or {}
            if payload.get("user_type") not in {None, "unspecified", user_type}:
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

    @staticmethod
    def _result(
        concept: dict[str, Any],
        destination: str,
        rule: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = (rule or {}).get("payload") or {}
        presentation = payload.get("presentation") or None
        instructions = []
        if presentation and presentation.get("instructions_raw"):
            instructions.append(presentation["instructions_raw"])
        eer = None
        candidates = concept.get("eer", {}).get("candidates", [])
        if concept.get("eer", {}).get("status") == "source_consensus" and len(candidates) == 1:
            candidate = candidates[0]
            eer = {
                "code": candidate["code"],
                "official_label": candidate.get("official_title") or candidate["source_labels"][0],
                "hazardous": bool(candidate.get("official_hazardous") or candidate.get("hazardous")),
                "facility_operational_label": candidate["source_labels"][0] if candidate.get("source_labels") else None,
            }
        warnings = []
        if rule is None:
            warnings.append("La destinazione e pubblicata, ma non e collegata a una regola di preparazione locale.")
        if _destination_type(destination) == "facility":
            warnings.append("Il centro utilizzabile deve ancora essere risolto tra le strutture accessibili.")
        return {
            "destination_type": _destination_type(destination),
            "stream": payload.get("stream_name") or destination,
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
            "facility": None,
            "environmental_note": concept.get("general_details", {}).get("environmental_note"),
            "warnings": warnings,
        }

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
