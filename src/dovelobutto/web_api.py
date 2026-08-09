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

from .app_query import DisposalQueryService, open_query_database
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
        if len(municipality) != 6 or not municipality.isdigit():
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
                self._static(parsed.path)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
                self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            except (FileNotFoundError, sqlite3.DatabaseError):
                self._json({"error": "Dataset database not found"}, HTTPStatus.SERVICE_UNAVAILABLE)

        def do_POST(self) -> None:  # noqa: N802
            try:
                path = urlparse(self.path).path
                if path not in {"/api/answer", "/api/locate"}:
                    self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 64 * 1024:
                    raise ValueError("Invalid request size")
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError("The request body must be an object")
                self._json(
                    api.locate(request) if path == "/api/locate"
                    else api.answer(request)
                )
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
