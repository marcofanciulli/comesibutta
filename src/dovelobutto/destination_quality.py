from __future__ import annotations

from collections import defaultdict
from typing import Any

from .app_query import DisposalQueryService


class DestinationQualityAudit:
    """Aggregate destination quality without treating unpublished facts as errors."""

    def __init__(
        self,
        service: DisposalQueryService,
        municipalities: dict[str, dict[str, Any]],
    ) -> None:
        self.service = service
        self.municipalities = municipalities
        self.category_cases: dict[str, int] = defaultdict(int)
        self.category_pairs: dict[str, set[tuple[str, str]]] = defaultdict(set)
        self.territory_cases: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self.territory_pairs: dict[str, dict[str, set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        self.examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.blocking_issues: list[dict[str, Any]] = []
        self._verified_facilities: dict[
            tuple[str, str, str], list[dict[str, Any]]
        ] = {}

    def _record(
        self,
        category: str,
        *,
        concept_id: str,
        label: str | None,
        municipality: str,
        zone_id: str | None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        pair = (concept_id, municipality)
        self.category_cases[category] += 1
        self.category_pairs[category].add(pair)
        self.territory_cases[municipality][category] += 1
        self.territory_pairs[municipality][category].add(concept_id)
        if len(self.examples[category]) < 12:
            example = {
                "concept_id": concept_id,
                "label": label,
                "municipality_istat": municipality,
                "zone_id": zone_id,
            }
            if detail:
                example.update(detail)
            if example not in self.examples[category]:
                self.examples[category].append(example)

    def _verified_centre_candidates(
        self,
        concept: dict[str, Any],
        concept_id: str,
        municipality: str,
        user_type: str,
    ) -> list[dict[str, Any]]:
        key = (concept_id, municipality, user_type)
        if key not in self._verified_facilities:
            facilities, _ = self.service._resolve_facilities(
                concept,
                "Centro di raccolta",
                municipality_istat=municipality,
                user_type=user_type,
                latitude=None,
                longitude=None,
                allow_term_match=True,
            )
            self._verified_facilities[key] = [
                facility for facility in facilities
                if facility["acceptance"]["status"]
                in {"verified_eer", "verified_description"}
            ]
        return self._verified_facilities[key]

    def observe(
        self,
        answer: dict[str, Any],
        *,
        concept: dict[str, Any] | None,
        concept_id: str,
        label: str | None,
        municipality: str,
        zone_id: str | None,
        user_type: str = "domestic",
    ) -> None:
        if answer.get("status") != "resolved" or not concept:
            return
        result = answer.get("result") or {}
        facilities = [
            item for item in [
                result.get("facility"), *(result.get("facility_alternatives") or []),
            ]
            if item
        ]
        services = result.get("channel_services") or []
        unresolved_channels = result.get("unresolved_channels") or []
        channel_ids = {
            item.get("channel_id") for item in result.get("delivery_channels") or []
        }
        has_local_rule = bool(
            result.get("stream_id")
            and result.get("destination_type") != "portable_route"
        )
        has_local_service = bool(facilities or services)

        if facilities:
            self._record(
                "verified_local_facility",
                concept_id=concept_id, label=label, municipality=municipality,
                zone_id=zone_id,
            )
        if services:
            self._record(
                "verified_local_channel_service",
                concept_id=concept_id, label=label, municipality=municipality,
                zone_id=zone_id,
            )
        if result.get("destination_type") == "portable_route":
            self._record(
                "portable_without_local_detail",
                concept_id=concept_id, label=label, municipality=municipality,
                zone_id=zone_id,
            )
        if unresolved_channels:
            self._record(
                "declared_channel_without_structured_service",
                concept_id=concept_id, label=label, municipality=municipality,
                zone_id=zone_id,
                detail={
                    "channels": sorted({
                        item.get("channel_id") for item in unresolved_channels
                        if item.get("channel_id")
                    }),
                },
            )
        if channel_ids == {"channel:specialist-operator"} and not has_local_service:
            self._record(
                "specialist_operator_only",
                concept_id=concept_id, label=label, municipality=municipality,
                zone_id=zone_id,
            )
        if (
            result.get("eer")
            and not has_local_service
            and not has_local_rule
        ):
            self._record(
                "eer_without_local_service",
                concept_id=concept_id, label=label, municipality=municipality,
                zone_id=zone_id,
                detail={"eer_code": result["eer"].get("code")},
            )
        if (
            "channel:collection-centre" in channel_ids
            and not facilities
        ):
            self._record(
                "collection_centre_not_verified_locally",
                concept_id=concept_id, label=label, municipality=municipality,
                zone_id=zone_id,
            )

        should_probe_centre = not facilities and (
            "channel:collection-centre" in channel_ids
            or channel_ids == {"channel:specialist-operator"}
        )
        if not should_probe_centre:
            return
        verified = self._verified_centre_candidates(
            concept, concept_id, municipality, user_type,
        )
        if not verified:
            return
        issue = {
            "code": "verified_facility_omitted",
            "concept_id": concept_id,
            "label": label,
            "municipality_istat": municipality,
            "zone_id": zone_id,
            "facility_ids": [item["id"] for item in verified],
            "acceptance_statuses": sorted({
                item["acceptance"]["status"] for item in verified
            }),
        }
        self._record(
            "verified_facility_omitted",
            concept_id=concept_id, label=label, municipality=municipality,
            zone_id=zone_id,
            detail={"facility_ids": issue["facility_ids"]},
        )
        if issue not in self.blocking_issues:
            self.blocking_issues.append(issue)

    def report(self) -> dict[str, Any]:
        categories = {
            category: {
                "answer_cases": cases,
                "concept_municipality_pairs": len(self.category_pairs[category]),
                "examples": self.examples[category],
            }
            for category, cases in sorted(self.category_cases.items())
        }
        territories = []
        for municipality, category_cases in sorted(self.territory_cases.items()):
            metadata = self.municipalities.get(municipality, {})
            territories.append({
                "municipality_istat": municipality,
                "municipality": metadata.get("name"),
                "province_code": metadata.get("province_code"),
                "ato_ref": metadata.get("ato_ref"),
                "categories": {
                    category: {
                        "answer_cases": cases,
                        "concepts": len(
                            self.territory_pairs[municipality][category]
                        ),
                    }
                    for category, cases in sorted(category_cases.items())
                },
            })
        return {
            "summary": {
                "status": "pass" if not self.blocking_issues else "fail",
                "release_ready": not self.blocking_issues,
                "blocking_issues": len(
                    self.category_pairs.get("verified_facility_omitted", set())
                ),
                "territories": len(territories),
                "categories": {
                    category: {
                        "answer_cases": values["answer_cases"],
                        "concept_municipality_pairs": values[
                            "concept_municipality_pairs"
                        ],
                    }
                    for category, values in categories.items()
                },
            },
            "method": {
                "blocking": (
                    "A release is blocked only when an accessible centre has a "
                    "verified EER or description match and the answer omits it."
                ),
                "source_gaps": (
                    "Unpublished local services, generic specialist routes, and EER "
                    "codes without a structured local service are counted for review "
                    "but are not converted into invented destinations."
                ),
            },
            "categories": categories,
            "territories": territories,
            "blocking_issues": self.blocking_issues,
        }
