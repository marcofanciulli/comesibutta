from __future__ import annotations

from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import sqlite3
from typing import Any
from urllib.parse import parse_qs, urlparse

from .app_query import DisposalQueryService, _distance_km, open_query_database
from .missing_queries import MissingQueryStore
from .municipality_boundaries import geometry_contains
from .sync import read_entity_data


class DisposalApi:
    def __init__(
        self, database: Path, feedback_database: Path | None = None,
    ) -> None:
        self.database = database
        self.missing_queries = (
            MissingQueryStore(feedback_database) if feedback_database else None
        )

    def municipalities(self) -> dict[str, Any]:
        connection = open_query_database(self.database)
        try:
            items = []
            for row in connection.execute(
                """SELECT entity_id FROM entities
                WHERE entity_type = 'municipality' ORDER BY entity_id"""
            ):
                entity = read_entity_data(
                    connection, "municipality", row["entity_id"], include_sources=False,
                )
                payload = (entity or {}).get("payload") or entity or {}
                istat_code = payload.get("istat_code") or row["entity_id"].removeprefix("istat:")
                name = payload.get("name") or payload.get("municipality_name")
                if not name or len(istat_code) != 6:
                    continue
                items.append({
                    "istat_code": istat_code,
                    "name": name,
                    "province_code": (
                        payload.get("province_code")
                        or payload.get("province_abbreviation")
                    ),
                    "ato": payload.get("ato_name") or payload.get("ato_ref"),
                    "operator": (
                        payload.get("operator_name")
                        or payload.get("local_operator_name")
                    ),
                })
            items.sort(key=lambda item: (item["name"].casefold(), item["istat_code"]))
            revision = int(dict(connection.execute(
                "SELECT key, value FROM metadata"
            )).get("revision", 0))
            return {"municipalities": items, "dataset_revision": revision}
        finally:
            connection.close()

    def search(self, text: str, municipality: str, limit: int = 8) -> dict[str, Any]:
        if not text.strip():
            return {"results": []}
        if (
            not isinstance(municipality, str)
            or len(municipality) != 6
            or not municipality.isdigit()
        ):
            raise ValueError("Municipality ISTAT code must contain six digits")
        connection = open_query_database(self.database)
        try:
            return {
                "results": DisposalQueryService(connection).search(
                    text, municipality_istat=municipality, limit=max(1, min(limit, 20)),
                )
            }
        finally:
            connection.close()

    @staticmethod
    def _source_urls(entity: dict[str, Any] | None) -> list[str]:
        return sorted({
            source.get("url") or source.get("source_url")
            for source in (entity or {}).get("sources", [])
            if source.get("url") or source.get("source_url")
        })

    @staticmethod
    def _operational_text(value: Any, *, limit: int = 700) -> str | None:
        if not isinstance(value, str):
            return None
        compact = " ".join(value.split())
        return compact if compact and len(compact) <= limit else None

    @staticmethod
    def _request_context(
        municipality: str,
        zone_id: str | None,
        user_type: str,
        latitude: float | None,
        longitude: float | None,
    ) -> None:
        if (
            not isinstance(municipality, str)
            or len(municipality) != 6
            or not municipality.isdigit()
        ):
            raise ValueError("Municipality ISTAT code must contain six digits")
        if user_type not in {"domestic", "non_domestic"}:
            raise ValueError("User type must be domestic or non_domestic")
        if zone_id is not None and not isinstance(zone_id, str):
            raise ValueError("Zone ID must be a string")
        if (latitude is None) != (longitude is None):
            raise ValueError("Latitude and longitude must be provided together")
        if latitude is not None and (
            isinstance(latitude, bool)
            or not isinstance(latitude, (int, float))
            or not -90 <= latitude <= 90
        ):
            raise ValueError("Latitude must be between -90 and 90")
        if longitude is not None and (
            isinstance(longitude, bool)
            or not isinstance(longitude, (int, float))
            or not -180 <= longitude <= 180
        ):
            raise ValueError("Longitude must be between -180 and 180")

    def territory(
        self,
        municipality: str,
        *,
        zone_id: str | None = None,
        user_type: str = "domestic",
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> dict[str, Any]:
        self._request_context(
            municipality, zone_id, user_type, latitude, longitude,
        )
        municipality_ref = f"istat:{municipality}"
        connection = open_query_database(self.database)
        try:
            municipality_entity = read_entity_data(
                connection, "municipality", municipality_ref, include_sources=False,
            )
            if municipality_entity is None:
                raise ValueError("Municipality is not present in the dataset")
            municipality_payload = (
                municipality_entity.get("payload") or municipality_entity
            )
            service = DisposalQueryService(connection)

            zones = []
            zone_names: dict[str, str] = {}
            for row in connection.execute(
                """SELECT entity_id FROM entities
                WHERE entity_type = 'service_zone' AND municipality_ref = ?
                ORDER BY entity_id""",
                (municipality_ref,),
            ):
                entity = read_entity_data(
                    connection, "service_zone", row["entity_id"],
                    include_sources=False,
                ) or {}
                payload = entity.get("payload") or {}
                name = payload.get("name") or row["entity_id"]
                zone_names[row["entity_id"]] = name
                zones.append({
                    "id": row["entity_id"],
                    "name": name,
                    "scope_type": payload.get("scope_type"),
                    "included_places": self._operational_text(
                        payload.get("included_places_raw"), limit=500,
                    ),
                    "excluded_places": self._operational_text(
                        payload.get("excluded_places_raw"), limit=500,
                    ),
                })
            if zone_id and zone_id not in zone_names:
                raise ValueError("Zone does not belong to the selected municipality")

            rules = []
            for row in connection.execute(
                """SELECT entity_id FROM entities
                WHERE entity_type = 'collection_rule' AND municipality_ref = ?
                ORDER BY zone_ref, stream_name, entity_id""",
                (municipality_ref,),
            ):
                entity = read_entity_data(
                    connection, "collection_rule", row["entity_id"],
                ) or {}
                payload = entity.get("payload") or {}
                if payload.get("user_type") not in {
                    None, "all", "unspecified", user_type,
                }:
                    continue
                rule_zone = payload.get("zone_ref")
                if zone_id and rule_zone not in {None, zone_id}:
                    continue
                presentation = payload.get("presentation") or {}
                rules.append({
                    "id": row["entity_id"],
                    "zone_id": rule_zone,
                    "zone_name": zone_names.get(rule_zone),
                    "stream": payload.get("stream_name"),
                    "collection_method": payload.get("collection_method"),
                    "container_type": payload.get("container_type"),
                    "container_color": payload.get("container_color"),
                    "access_credential": payload.get("access_credential"),
                    "presentation_mode": presentation.get("mode"),
                    "instructions": self._operational_text(
                        presentation.get("instructions_raw"), limit=600,
                    ),
                    "schedule": self._operational_text(
                        payload.get("schedule_raw"), limit=500,
                    ),
                    "included_materials": self._operational_text(
                        payload.get("included_materials_raw"), limit=600,
                    ),
                    "source_urls": self._source_urls(entity),
                })

            accesses_by_facility: dict[str, list[dict[str, Any]]] = {}
            for row in connection.execute(
                """SELECT entity_id, facility_ref FROM entities
                WHERE entity_type = 'facility_access' AND municipality_ref = ?
                ORDER BY facility_ref, entity_id""",
                (municipality_ref,),
            ):
                entity = read_entity_data(
                    connection, "facility_access", row["entity_id"],
                ) or {}
                payload = entity.get("payload") or {}
                if (
                    payload.get("allowed") is True
                    and payload.get("user_type") in {"all", user_type}
                ):
                    accesses_by_facility.setdefault(
                        row["facility_ref"], [],
                    ).append(entity)

            facilities = []
            for facility_id, accesses in accesses_by_facility.items():
                entity = read_entity_data(connection, "facility", facility_id) or {}
                payload = entity.get("payload") or {}
                access_payloads = [item.get("payload") or {} for item in accesses]
                location_raw = payload.get("location") or {}
                location = None
                distance = None
                if (
                    location_raw.get("latitude") is not None
                    and location_raw.get("longitude") is not None
                ):
                    location = {
                        "latitude": location_raw["latitude"],
                        "longitude": location_raw["longitude"],
                        "method": location_raw.get("method"),
                        "accuracy_m": location_raw.get("accuracy_m"),
                    }
                    distance = _distance_km(
                        latitude, longitude,
                        location["latitude"], location["longitude"],
                    )
                periods, period_sources = service._facility_opening_periods(
                    facility_id,
                )
                accepted = []
                acceptance_sources = []
                seen_acceptance = set()
                for acceptance_row in connection.execute(
                    """SELECT entity_id FROM entities
                    WHERE entity_type = 'facility_acceptance' AND facility_ref = ?
                    ORDER BY entity_id""",
                    (facility_id,),
                ):
                    acceptance = read_entity_data(
                        connection, "facility_acceptance",
                        acceptance_row["entity_id"],
                    ) or {}
                    item = acceptance.get("payload") or {}
                    if item.get("user_type") not in {
                        None, "all", "unspecified", user_type,
                    }:
                        continue
                    code = item.get("eer_code_normalized")
                    label = item.get("description_raw")
                    key = (code, label, item.get("operational_group"))
                    if key in seen_acceptance:
                        continue
                    seen_acceptance.add(key)
                    eer = (
                        read_entity_data(
                            connection, "eer_entry", f"eer:{code}",
                            include_sources=False,
                        ) if code else None
                    ) or {}
                    accepted.append({
                        "eer_code": code,
                        "label": label,
                        "official_label": eer.get("title_expanded") or eer.get("title"),
                        "hazardous": (
                            eer.get("hazardous")
                            if eer.get("hazardous") is not None
                            else item.get("hazardous")
                        ),
                        "operational_group": item.get("operational_group"),
                        "quantity_limit": self._operational_text(
                            item.get("quantity_limit_raw"), limit=300,
                        ),
                        "notes": self._operational_text(
                            item.get("notes_raw"), limit=300,
                        ),
                    })
                    acceptance_sources.extend(self._source_urls(acceptance))
                accepted.sort(key=lambda item: (
                    item.get("label") or item.get("official_label") or "",
                    item.get("eer_code") or "",
                ))
                booking_values = {
                    item.get("booking_required") for item in access_payloads
                    if item.get("booking_required") is not None
                }
                facilities.append({
                    "id": facility_id,
                    "name": payload.get("name") or facility_id,
                    "facility_type": payload.get("facility_type"),
                    "address": payload.get("address_raw"),
                    "location": location,
                    "distance_km": round(distance, 2) if distance is not None else None,
                    "operational_status": payload.get("operational_status") or "unknown",
                    "status_raw": self._operational_text(
                        payload.get("status_raw"), limit=400,
                    ),
                    "access_summary": next((
                        self._operational_text(item.get("requirements_raw"), limit=600)
                        for item in access_payloads if item.get("requirements_raw")
                    ), None),
                    "booking_required": (
                        True if True in booking_values
                        else False if booking_values == {False} else None
                    ),
                    "phone": next((
                        item.get("contact_phone") for item in access_payloads
                        if item.get("contact_phone")
                    ), payload.get("phone")),
                    "email": next((
                        item.get("contact_email") for item in access_payloads
                        if item.get("contact_email")
                    ), payload.get("email")),
                    "information_urls": sorted({
                        url for item in access_payloads
                        for url in item.get("information_urls", [])
                    }),
                    "opening_periods": periods,
                    "accepted_waste": accepted,
                    "acceptance_status": (
                        "published" if accepted else "not_published"
                    ),
                    "source_urls": sorted({
                        *self._source_urls(entity),
                        *(url for access in accesses for url in self._source_urls(access)),
                        *acceptance_sources,
                        *(
                            source.get("url") or source.get("source_url")
                            for source in period_sources
                            if source.get("url") or source.get("source_url")
                        ),
                    }),
                })
            status_rank = {
                "open": 0, "active": 0, "unknown": 1,
                "temporarily_closed": 2, "closed": 3,
            }
            facilities.sort(key=lambda item: (
                status_rank.get(item["operational_status"], 1),
                item["distance_km"] if item["distance_km"] is not None else float("inf"),
                item["name"].casefold(),
            ))

            points = []
            for row in connection.execute(
                """SELECT entity_id FROM entities
                WHERE entity_type = 'collection_point' AND municipality_ref = ?
                ORDER BY entity_id""",
                (municipality_ref,),
            ):
                entity = read_entity_data(
                    connection, "collection_point", row["entity_id"],
                ) or {}
                payload = entity.get("payload") or {}
                point_zone = payload.get("zone_ref")
                if zone_id and point_zone not in {None, zone_id}:
                    continue
                location_raw = payload.get("location") or {}
                location = None
                distance = None
                if (
                    location_raw.get("latitude") is not None
                    and location_raw.get("longitude") is not None
                ):
                    location = {
                        "latitude": location_raw["latitude"],
                        "longitude": location_raw["longitude"],
                    }
                    distance = _distance_km(
                        latitude, longitude,
                        location["latitude"], location["longitude"],
                    )
                points.append({
                    "id": row["entity_id"],
                    "name": payload.get("name"),
                    "point_type": payload.get("point_type"),
                    "zone_id": point_zone,
                    "zone_name": zone_names.get(point_zone),
                    "address": payload.get("address_raw"),
                    "location": location,
                    "distance_km": round(distance, 2) if distance is not None else None,
                    "accepted_waste": payload.get("accepted_streams", []),
                    "schedule": self._operational_text(
                        payload.get("opening_hours_raw"), limit=600,
                    ),
                    "access_summary": self._operational_text(
                        payload.get("access_notes_raw"), limit=600,
                    ),
                    "access_credential": payload.get("access_credential"),
                    "information_urls": payload.get("information_urls", []),
                    "source_urls": self._source_urls(entity),
                })
            points.sort(key=lambda item: (
                item["distance_km"] if item["distance_km"] is not None else float("inf"),
                (item["name"] or item["address"] or item["id"]).casefold(),
            ))

            pickups = []
            for row in connection.execute(
                """SELECT entity_id FROM entities
                WHERE entity_type = 'pickup_service' AND municipality_ref = ?
                ORDER BY entity_id""",
                (municipality_ref,),
            ):
                entity = read_entity_data(
                    connection, "pickup_service", row["entity_id"],
                ) or {}
                payload = entity.get("payload") or {}
                if payload.get("user_type") not in {"all", user_type}:
                    continue
                pickup_zone = payload.get("zone_ref")
                if zone_id and pickup_zone not in {None, zone_id}:
                    continue
                instructions_raw = payload.get("placement_instructions_raw")
                pickups.append({
                    "id": row["entity_id"],
                    "zone_id": pickup_zone,
                    "zone_name": zone_names.get(pickup_zone),
                    "accepted_waste": payload.get("accepted_waste_raw"),
                    "booking_required": payload.get("booking_required"),
                    "booking_methods": [
                        {
                            **method,
                            "hours_raw": self._operational_text(
                                method.get("hours_raw"), limit=300,
                            ),
                        }
                        for method in payload.get("booking_methods", [])
                        if isinstance(method, dict)
                    ],
                    "max_items": payload.get("max_items"),
                    "quantity_limit": self._operational_text(
                        payload.get("quantity_limit_raw"), limit=400,
                    ),
                    "instructions": self._operational_text(
                        instructions_raw, limit=700,
                    ),
                    "instructions_status": (
                        "source_only"
                        if isinstance(instructions_raw, str)
                        and len(" ".join(instructions_raw.split())) > 700
                        else "published"
                    ),
                    "source_urls": self._source_urls(entity),
                })

            revision = int(dict(connection.execute(
                "SELECT key, value FROM metadata"
            )).get("revision", 0))
            return {
                "municipality": {
                    "istat_code": municipality,
                    "name": municipality_payload.get("name"),
                    "province_code": municipality_payload.get("province_code"),
                    "ato": municipality_payload.get("ato_ref"),
                    "operator": (
                        municipality_payload.get("operator_name")
                        or municipality_payload.get("local_operator_name")
                    ),
                },
                "selected_zone_id": zone_id,
                "zones": zones,
                "rules": rules,
                "facilities": facilities,
                "collection_points": points,
                "pickup_services": pickups,
                "summary": {
                    "rules": len(rules),
                    "facilities": len(facilities),
                    "collection_points": len(points),
                    "pickup_services": len(pickups),
                },
                "dataset_revision": revision,
                "location_used": latitude is not None,
            }
        finally:
            connection.close()

    def locate(self, request: dict[str, Any]) -> dict[str, Any]:
        latitude = request.get("latitude")
        longitude = request.get("longitude")
        accuracy = request.get("accuracy")
        if (
            isinstance(latitude, bool) or not isinstance(latitude, (int, float))
            or not -90 <= latitude <= 90
        ):
            raise ValueError("Latitude must be a number between -90 and 90")
        if (
            isinstance(longitude, bool) or not isinstance(longitude, (int, float))
            or not -180 <= longitude <= 180
        ):
            raise ValueError("Longitude must be a number between -180 and 180")
        if accuracy is not None and (
            isinstance(accuracy, bool)
            or not isinstance(accuracy, (int, float))
            or accuracy < 0
        ):
            raise ValueError("Accuracy must be a non-negative number")
        connection = open_query_database(self.database)
        try:
            matches = []
            for row in connection.execute(
                """SELECT entity_id FROM entities
                WHERE entity_type = 'municipality_boundary' ORDER BY entity_id"""
            ):
                boundary = read_entity_data(
                    connection, "municipality_boundary", row["entity_id"],
                    include_sources=False,
                ) or {}
                payload = boundary.get("payload") or {}
                bbox = payload.get("bbox") or []
                if len(bbox) != 4 or not (
                    bbox[0] <= longitude <= bbox[2]
                    and bbox[1] <= latitude <= bbox[3]
                ):
                    continue
                if not geometry_contains(
                    payload.get("geometry_geojson") or {}, longitude, latitude,
                ):
                    continue
                municipality_ref = payload.get("municipality_ref") or ""
                code = municipality_ref.removeprefix("istat:")
                municipality = read_entity_data(
                    connection, "municipality", municipality_ref,
                    include_sources=False,
                ) or {}
                municipality_payload = municipality.get("payload") or municipality
                matches.append({
                    "istat_code": code,
                    "name": municipality_payload.get("name") or payload.get("name"),
                    "province_code": municipality_payload.get("province_code"),
                    "ato": municipality_payload.get("ato_ref"),
                    "operator": (
                        municipality_payload.get("local_operator_name")
                        or municipality_payload.get("operator_name")
                    ),
                })
            revision = int(dict(connection.execute(
                "SELECT key, value FROM metadata"
            )).get("revision", 0))
            return {
                "status": (
                    "resolved" if len(matches) == 1
                    else "boundary_ambiguous" if matches
                    else "outside_supported_area"
                ),
                "municipalities": matches,
                "accuracy_m": accuracy,
                "dataset_revision": revision,
                "position_stored": False,
            }
        finally:
            connection.close()

    def answer(self, request: dict[str, Any]) -> dict[str, Any]:
        text = request.get("text")
        municipality = request.get("municipality")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Waste text is required")
        if not isinstance(municipality, str):
            raise ValueError("Municipality is required")
        requested_date = request.get("as_of")
        as_of = date.fromisoformat(requested_date) if requested_date else None
        connection = open_query_database(self.database)
        try:
            answer = DisposalQueryService(connection).answer(
                text,
                municipality,
                concept_id=request.get("concept_id"),
                zone_id=request.get("zone_id"),
                user_type=request.get("user_type", "domestic"),
                as_of=as_of,
                latitude=request.get("latitude"),
                longitude=request.get("longitude"),
            )
            if answer["status"] == "not_found" and self.missing_queries:
                reason = (
                    "known_without_route"
                    if (answer.get("query") or {}).get("matched_concept_id")
                    else "unknown_term"
                )
                try:
                    feedback = self.missing_queries.record(
                        text,
                        municipality_istat=municipality,
                        zone_id=request.get("zone_id"),
                        user_type=request.get("user_type", "domestic"),
                        dataset_revision=(answer.get("provenance") or {}).get(
                            "dataset_revision"
                        ),
                        reason=reason,
                    )
                except sqlite3.DatabaseError:
                    feedback = {"recorded": False, "reason": "storage_unavailable"}
                answer["feedback"] = {
                    "recorded": bool(feedback.get("recorded")),
                    "reason": (
                        reason if feedback.get("recorded")
                        else feedback.get("reason")
                    ),
                }
            return answer
        finally:
            connection.close()


def _handler(api: DisposalApi, static_root: Path) -> type[BaseHTTPRequestHandler]:
    root = static_root.resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "ComeSiButta/0.1"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/health":
                    self._json({"status": "ok"})
                    return
                if parsed.path == "/api/municipalities":
                    self._json(api.municipalities())
                    return
                if parsed.path == "/api/search":
                    query = parse_qs(parsed.query)
                    self._json(api.search(
                        query.get("q", [""])[0],
                        query.get("municipality", [""])[0],
                        int(query.get("limit", ["8"])[0]),
                    ))
                    return
                if parsed.path.startswith("/api/"):
                    self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                    return
                self._static(parsed.path)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
                self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            except (FileNotFoundError, sqlite3.DatabaseError):
                self._json({"error": "Dataset database not found"}, HTTPStatus.SERVICE_UNAVAILABLE)

        def do_POST(self) -> None:  # noqa: N802
            try:
                path = urlparse(self.path).path
                if path not in {"/api/answer", "/api/locate", "/api/territory"}:
                    self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 64 * 1024:
                    raise ValueError("Invalid request size")
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError("The request body must be an object")
                if path == "/api/locate":
                    response = api.locate(request)
                elif path == "/api/territory":
                    response = api.territory(
                        request.get("municipality"),
                        zone_id=request.get("zone_id"),
                        user_type=request.get("user_type", "domestic"),
                        latitude=request.get("latitude"),
                        longitude=request.get("longitude"),
                    )
                else:
                    response = api.answer(request)
                self._json(response)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
                self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            except (FileNotFoundError, sqlite3.DatabaseError):
                self._json({"error": "Dataset database not found"}, HTTPStatus.SERVICE_UNAVAILABLE)

        def _static(self, request_path: str) -> None:
            relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
            path = (root / relative).resolve()
            if root not in path.parents and path != root:
                self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return
            if not path.is_file():
                path = root / "index.html"
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            data = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            print(f"{self.address_string()} - {format % args}")

    return Handler


def run_server(
    database: Path,
    static_root: Path,
    host: str,
    port: int,
    feedback_database: Path | None = None,
) -> None:
    server = ThreadingHTTPServer(
        (host, port),
        _handler(DisposalApi(database, feedback_database), static_root),
    )
    print(f"ComeSiButta available at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
