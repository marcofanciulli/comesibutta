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
from .sync import read_entity_data


class DisposalApi:
    def __init__(self, database: Path) -> None:
        self.database = database

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
            return DisposalQueryService(connection).answer(
                text,
                municipality,
                concept_id=request.get("concept_id"),
                zone_id=request.get("zone_id"),
                user_type=request.get("user_type", "domestic"),
                as_of=as_of,
                latitude=request.get("latitude"),
                longitude=request.get("longitude"),
            )
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
                if urlparse(self.path).path != "/api/answer":
                    self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 64 * 1024:
                    raise ValueError("Invalid request size")
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError("The request body must be an object")
                self._json(api.answer(request))
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


def run_server(database: Path, static_root: Path, host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), _handler(DisposalApi(database), static_root))
    print(f"ComeSiButta available at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
