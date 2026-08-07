from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from typing import Any, Iterable
from urllib.parse import urljoin


DATASET_ID = "comesibutta-toscana"
SCHEMA_VERSION = 1
STORAGE_VERSION = 4
TERRITORIAL_TEMPLATE_TYPES = frozenset({"collection_rule", "service_zone", "waste_lookup"})


@dataclass(frozen=True)
class CanonicalEntity:
    entity_type: str
    entity_id: str
    data: dict[str, Any]
    dependencies: tuple[tuple[str, str], ...] = ()
    entity_revision: int | None = None

    @property
    def content_sha256(self) -> str:
        return _sha256_json({"data": self.data, "dependencies": self.dependencies})


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _gzip_json(value: Any) -> bytes:
    return gzip.compress(_json_bytes(value), compresslevel=9, mtime=0)


def _gunzip_json(value: bytes) -> Any:
    return json.loads(gzip.decompress(value))


def _read_jsonl(paths: Iterable[Path]) -> list[dict[str, Any]]:
    records = []
    for path in sorted(set(paths)):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def _record_core(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "natural_key": record["natural_key"],
        "payload": record["payload"],
        "validity": record.get("validity"),
        "confidence": record.get("confidence"),
    }


def _source_identity(source: dict[str, Any]) -> str:
    evidence = source.get("evidence") or {}
    return _sha256_json({
        "url": source.get("url"),
        "selector": evidence.get("selector"),
        "page": evidence.get("page"),
        "quote": evidence.get("quote"),
    })[:12]


def _merge_acquisition_records(records: list[dict[str, Any]]) -> list[CanonicalEntity]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault((record["record_type"], record["natural_key"]), []).append(record)
    entities = []
    for (entity_type, natural_key), variants in sorted(grouped.items()):
        by_core: dict[str, list[dict[str, Any]]] = {}
        for record in variants:
            by_core.setdefault(_sha256_json(_record_core(record)), []).append(record)
        for core_hash, observations in sorted(by_core.items()):
            suffix = "" if len(by_core) == 1 else f":variant:{core_hash[:12]}"
            sources = []
            seen_sources = set()
            for observation in sorted(observations, key=lambda item: (
                item["source"].get("url", ""), _source_identity(item["source"]), item.get("observed_at", ""),
            )):
                source_key = _sha256_json(observation["source"])
                if source_key not in seen_sources:
                    sources.append(observation["source"])
                    seen_sources.add(source_key)
            latest = max(observations, key=lambda item: item.get("observed_at", ""))
            data = {
                **_record_core(latest),
                "observed_at": max(item.get("observed_at", "") for item in observations),
                "sources": sources,
            }
            entities.append(CanonicalEntity(entity_type, natural_key + suffix, data))
    return entities


def _reference_candidates(entity: CanonicalEntity) -> set[tuple[str, str]]:
    payload = entity.data.get("payload") or {}
    references = set()
    mapping = {
        "municipality_ref": "municipality",
        "zone_ref": "service_zone",
        "facility_ref": "facility",
    }
    for field, entity_type in mapping.items():
        value = payload.get(field)
        if value:
            references.add((entity_type, str(value)))
    eer_code = payload.get("eer_code_normalized")
    if eer_code:
        references.add(("eer_entry", f"eer:{eer_code}"))
    if entity.entity_type == "waste_concept":
        for candidate in (entity.data.get("eer") or {}).get("candidates", []):
            if candidate.get("code"):
                references.add(("eer_entry", f"eer:{candidate['code']}"))
    return references


def load_canonical_entities(
    input_dirs: list[Path], registry_paths: list[Path],
    catalog_path: Path | None = None, eer_register_path: Path | None = None,
    packaging_material_register_path: Path | None = None,
) -> dict[tuple[str, str], CanonicalEntity]:
    acquisition_paths = [
        path for directory in input_dirs
        for path in directory.glob("*-acquisition.jsonl")
    ]
    records = _read_jsonl([*acquisition_paths, *registry_paths])
    entities = _merge_acquisition_records(records)
    if eer_register_path:
        register = json.loads(eer_register_path.read_text(encoding="utf-8"))
        entities.extend(
            CanonicalEntity("eer_entry", entry["entry_id"], entry)
            for entry in register.get("entries", [])
        )
    if catalog_path:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        entities.extend(
            CanonicalEntity("waste_concept", concept["concept_id"], concept)
            for concept in catalog.get("concepts", [])
        )
    if packaging_material_register_path:
        packaging_register = json.loads(
            packaging_material_register_path.read_text(encoding="utf-8")
        )
        entities.extend(
            CanonicalEntity("packaging_material_mark", entry["mark_id"], entry)
            for entry in packaging_register.get("entries", [])
        )
    indexed = {(entity.entity_type, entity.entity_id): entity for entity in entities}
    if len(indexed) != len(entities):
        raise ValueError("Canonical auxiliary entities contain duplicate identifiers")
    result = {}
    for key, entity in indexed.items():
        dependencies = tuple(sorted(
            dependency for dependency in _reference_candidates(entity)
            if dependency in indexed and dependency != key
        ))
        result[key] = CanonicalEntity(
            entity.entity_type, entity.entity_id, entity.data, dependencies, entity.entity_revision,
        )
    return result


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entities (
    entity_key INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_revision INTEGER NOT NULL,
    content_sha256 TEXT NOT NULL,
    data_json BLOB,
    template_key INTEGER,
    territory_fields INTEGER NOT NULL DEFAULT 0,
    municipality_ref TEXT,
    zone_ref TEXT,
    observed_at TEXT,
    valid_from TEXT,
    valid_to TEXT,
    confidence TEXT,
    search_text TEXT,
    destination_raw TEXT,
    stream_name TEXT,
    facility_ref TEXT,
    UNIQUE (entity_type, entity_id),
    FOREIGN KEY (template_key) REFERENCES entity_templates(template_key)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    CHECK ((data_json IS NULL) != (template_key IS NULL))
);
CREATE INDEX IF NOT EXISTS entities_type_municipality
    ON entities(entity_type, municipality_ref);
CREATE INDEX IF NOT EXISTS entities_type_facility
    ON entities(entity_type, facility_ref);
CREATE TABLE IF NOT EXISTS entity_templates (
    template_key INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    template_sha256 TEXT NOT NULL,
    data_json BLOB NOT NULL,
    UNIQUE (entity_type, template_sha256)
);
CREATE TABLE IF NOT EXISTS source_documents (
    source_key INTEGER PRIMARY KEY,
    source_sha256 TEXT NOT NULL UNIQUE,
    document_json BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS source_evidence (
    evidence_key INTEGER PRIMARY KEY,
    evidence_sha256 TEXT NOT NULL UNIQUE,
    source_key INTEGER NOT NULL,
    evidence_json BLOB NOT NULL,
    FOREIGN KEY (source_key) REFERENCES source_documents(source_key)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX IF NOT EXISTS source_evidence_document
    ON source_evidence(source_key);
CREATE TABLE IF NOT EXISTS entity_sources (
    entity_key INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    evidence_key INTEGER NOT NULL,
    PRIMARY KEY (entity_key, ordinal),
    FOREIGN KEY (entity_key) REFERENCES entities(entity_key)
        ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (evidence_key) REFERENCES source_evidence(evidence_key)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX IF NOT EXISTS entity_sources_evidence
    ON entity_sources(evidence_key);
CREATE TABLE IF NOT EXISTS entity_dependencies (
    entity_key INTEGER NOT NULL,
    dependency_key INTEGER NOT NULL,
    PRIMARY KEY (entity_key, dependency_key),
    FOREIGN KEY (entity_key) REFERENCES entities(entity_key)
        ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (dependency_key) REFERENCES entities(entity_key)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX IF NOT EXISTS dependencies_target
    ON entity_dependencies(dependency_key);
CREATE TABLE IF NOT EXISTS changelog (
    revision INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    operation TEXT NOT NULL CHECK(operation IN ('upsert', 'delete')),
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    operation_json BLOB NOT NULL,
    changed_at TEXT NOT NULL,
    PRIMARY KEY (revision, sequence)
);
CREATE TABLE IF NOT EXISTS tombstones (
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    deleted_revision INTEGER NOT NULL,
    deleted_at TEXT NOT NULL,
    reason TEXT,
    PRIMARY KEY (entity_type, entity_id)
);
CREATE TABLE IF NOT EXISTS package_applications (
    package_id TEXT PRIMARY KEY,
    from_revision INTEGER,
    to_revision INTEGER NOT NULL,
    package_sha256 TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""


def open_database(
    path: Path, dataset_id: str = DATASET_ID, schema_version: int = SCHEMA_VERSION,
    role: str = "server",
) -> sqlite3.Connection:
    if role not in {"server", "client"}:
        raise ValueError("SQLite role must be server or client")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    has_metadata = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'"
    ).fetchone()
    if has_metadata:
        existing = dict(connection.execute("SELECT key, value FROM metadata"))
        if int(existing.get("storage_version", 0)) != STORAGE_VERSION:
            connection.close()
            raise ValueError("SQLite storage version mismatch; rebuild the database from a snapshot")
    connection.executescript(SCHEMA_SQL)
    metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    if not metadata:
        connection.executemany("INSERT INTO metadata(key, value) VALUES (?, ?)", (
            ("dataset_id", dataset_id), ("schema_version", str(schema_version)),
            ("storage_version", str(STORAGE_VERSION)), ("revision", "0"), ("role", role),
        ))
        connection.commit()
    elif (
        metadata.get("dataset_id") != dataset_id
        or int(metadata.get("schema_version", 0)) != schema_version
        or metadata.get("role", "server") != role
    ):
        connection.close()
        raise ValueError("SQLite dataset, schema version or role mismatch")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def read_database_entities(connection: sqlite3.Connection) -> dict[tuple[str, str], CanonicalEntity]:
    dependencies: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for row in connection.execute(
        """SELECT source.entity_type, source.entity_id,
            target.entity_type AS dependency_type, target.entity_id AS dependency_id
        FROM entity_dependencies dependency
        JOIN entities source ON source.entity_key = dependency.entity_key
        JOIN entities target ON target.entity_key = dependency.dependency_key
        ORDER BY source.entity_type, source.entity_id, target.entity_type, target.entity_id"""
    ):
        dependencies.setdefault((row["entity_type"], row["entity_id"]), []).append(
            (row["dependency_type"], row["dependency_id"])
        )
    sources: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in connection.execute(
        """SELECT entity.entity_type, entity.entity_id, sd.document_json, se.evidence_json
        FROM entity_sources es
        JOIN entities entity ON entity.entity_key = es.entity_key
        JOIN source_evidence se ON se.evidence_key = es.evidence_key
        JOIN source_documents sd ON sd.source_key = se.source_key
        ORDER BY entity.entity_type, entity.entity_id, es.ordinal"""
    ):
        document = _gunzip_json(row["document_json"])
        evidence_wrapper = _gunzip_json(row["evidence_json"])
        if evidence_wrapper["present"]:
            document["evidence"] = evidence_wrapper["value"]
        sources.setdefault((row["entity_type"], row["entity_id"]), []).append(document)
    templates = {
        row["template_key"]: _gunzip_json(row["data_json"])
        for row in connection.execute("SELECT template_key, data_json FROM entity_templates")
    }
    result = {}
    for row in connection.execute("SELECT * FROM entities ORDER BY entity_type, entity_id"):
        key = (row["entity_type"], row["entity_id"])
        if row["template_key"] is None:
            data = _gunzip_json(row["data_json"])
        else:
            data = _restore_territorial_entity(row, templates[row["template_key"]])
        if key in sources:
            data["sources"] = sources[key]
        result[key] = CanonicalEntity(
            *key, data, tuple(dependencies.get(key, [])), row["entity_revision"],
        )
    return result


def build_update_package(
    current: dict[tuple[str, str], CanonicalEntity],
    desired: dict[tuple[str, str], CanonicalEntity],
    from_revision: int | None,
    to_revision: int,
    generated_at: datetime,
) -> dict[str, Any]:
    if to_revision < 1 or from_revision is not None and to_revision <= from_revision:
        raise ValueError("Revision must increase")
    kind = "snapshot" if from_revision is None else "delta"
    operations = []
    for key in sorted(desired):
        entity = desired[key]
        previous = current.get(key)
        if kind == "delta" and previous and previous.content_sha256 == entity.content_sha256:
            continue
        operations.append({
            "operation": "upsert", "entity_type": entity.entity_type, "entity_id": entity.entity_id,
            "entity_revision": to_revision,
            "dependencies": [
                {"entity_type": dependency_type, "entity_id": dependency_id}
                for dependency_type, dependency_id in entity.dependencies
            ],
            "data": entity.data,
        })
    if kind == "delta":
        for key in sorted(set(current) - set(desired), reverse=True):
            entity = current[key]
            operations.append({
                "operation": "delete", "entity_type": entity.entity_type, "entity_id": entity.entity_id,
                "entity_revision": to_revision, "dependencies": [],
                "deleted_at": generated_at.isoformat(), "reason": "absent_from_published_state",
            })
    for sequence, operation in enumerate(operations, 1):
        operation["sequence"] = sequence
    return {
        "format_version": 1, "dataset_id": DATASET_ID, "schema_version": SCHEMA_VERSION,
        "package_id": f"{kind}:{from_revision or 0}:{to_revision}", "kind": kind,
        "generated_at": generated_at.isoformat(), "from_revision": from_revision,
        "to_revision": to_revision, "operations": operations,
    }


def _validate_package(package: dict[str, Any]) -> None:
    required = {
        "format_version", "dataset_id", "schema_version", "package_id", "kind",
        "generated_at", "from_revision", "to_revision", "operations",
    }
    if not required <= package.keys():
        raise ValueError(f"Package fields missing: {sorted(required - package.keys())}")
    if package["format_version"] != 1 or package["dataset_id"] != DATASET_ID or package["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported package contract")
    if package["kind"] == "snapshot" and package["from_revision"] is not None:
        raise ValueError("Snapshot must not have a starting revision")
    if package["kind"] == "delta" and not isinstance(package["from_revision"], int):
        raise ValueError("Delta requires a starting revision")
    sequences = [operation.get("sequence") for operation in package["operations"]]
    if sequences != list(range(1, len(sequences) + 1)):
        raise ValueError("Package operation sequence is not contiguous")


def _indexed_fields(data: dict[str, Any]) -> tuple[Any, ...]:
    payload = data.get("payload") or data
    validity = data.get("validity") or {}
    searchable = []
    for field in ("term", "name", "description_raw", "stream_name", "preferred_label"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip() and value.casefold() not in searchable:
            searchable.append(value.casefold())
    return (
        payload.get("municipality_ref"), payload.get("zone_ref"), data.get("observed_at"), validity.get("valid_from"),
        validity.get("valid_to"), data.get("confidence"), " | ".join(searchable) or None,
        payload.get("destination_raw"), payload.get("stream_name"), payload.get("facility_ref"),
    )


def _split_sources(data: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[str, str, bytes, bytes]]]:
    body = dict(data)
    raw_sources = body.get("sources")
    if not raw_sources:
        return body, []
    body.pop("sources")
    sources = []
    for source in raw_sources:
        document = {key: value for key, value in source.items() if key != "evidence"}
        evidence = {"present": "evidence" in source, "value": source.get("evidence")}
        source_id = _sha256_json(document)
        evidence_id = _sha256_json(source)
        sources.append((source_id, evidence_id, _gzip_json(document), _gzip_json(evidence)))
    return body, sources


def _split_territorial_entity(
    entity_type: str, entity_id: str, data: dict[str, Any],
) -> tuple[dict[str, Any] | None, int]:
    natural_key = entity_id.split(":variant:", 1)[0]
    if entity_type not in TERRITORIAL_TEMPLATE_TYPES or data.get("natural_key") != natural_key:
        return None, 0
    template = dict(data)
    template.pop("natural_key")
    payload = dict(template.get("payload") or {})
    territory_fields = 1
    if "municipality_ref" in payload:
        territory_fields |= 2
        payload.pop("municipality_ref")
    if "zone_ref" in payload:
        territory_fields |= 4
        payload.pop("zone_ref")
    template["payload"] = payload
    return template, territory_fields


def _restore_territorial_entity(row: sqlite3.Row, template: dict[str, Any]) -> dict[str, Any]:
    data = dict(template)
    payload = dict(data.get("payload") or {})
    fields = row["territory_fields"]
    if fields & 2:
        payload["municipality_ref"] = row["municipality_ref"]
    if fields & 4:
        payload["zone_ref"] = row["zone_ref"]
    data["payload"] = payload
    if fields & 1:
        data["natural_key"] = row["entity_id"].split(":variant:", 1)[0]
    return data


def apply_package(
    connection: sqlite3.Connection, package: dict[str, Any], package_sha256: str | None = None,
) -> bool:
    _validate_package(package)
    package_hash = package_sha256 or hashlib.sha256(_json_bytes(package)).hexdigest()
    metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    current_revision = int(metadata["revision"])
    previous_application = connection.execute(
        "SELECT package_sha256, to_revision FROM package_applications WHERE package_id = ?",
        (package["package_id"],),
    ).fetchone()
    if previous_application:
        if previous_application["package_sha256"] != package_hash or previous_application["to_revision"] != package["to_revision"]:
            raise ValueError("Package ID was already applied with different content")
        return False
    if package["kind"] == "snapshot":
        if current_revision not in {0, package["to_revision"]}:
            raise ValueError("Snapshot can only initialize an empty database")
    elif package["from_revision"] != current_revision:
        raise ValueError(f"Delta starts at {package['from_revision']}, client is at {current_revision}")
    try:
        connection.execute("BEGIN IMMEDIATE")
        if not package["operations"] and package["kind"] == "delta":
            connection.execute(
                "UPDATE metadata SET value = ? WHERE key = 'revision'", (str(package["to_revision"]),),
            )
            connection.execute(
                "INSERT INTO package_applications VALUES (?, ?, ?, ?, ?)",
                (
                    package["package_id"], package["from_revision"], package["to_revision"],
                    package_hash, package["generated_at"],
                ),
            )
            connection.commit()
            return True
        if package["kind"] == "snapshot":
            connection.execute("DELETE FROM entity_dependencies")
            connection.execute("DELETE FROM entities")
            connection.execute("DELETE FROM tombstones")
            connection.execute("DELETE FROM source_evidence")
            connection.execute("DELETE FROM source_documents")
            connection.execute("DELETE FROM entity_templates")
        source_keys = {
            row["source_sha256"]: row["source_key"]
            for row in connection.execute("SELECT source_key, source_sha256 FROM source_documents")
        }
        evidence_keys = {
            row["evidence_sha256"]: row["evidence_key"]
            for row in connection.execute("SELECT evidence_key, evidence_sha256 FROM source_evidence")
        }
        template_keys = {
            (row["entity_type"], row["template_sha256"]): row["template_key"]
            for row in connection.execute(
                "SELECT template_key, entity_type, template_sha256 FROM entity_templates"
            )
        }
        entity_keys: dict[tuple[str, str], int] = {}
        stale_evidence_keys: set[int] = set()
        stale_source_keys: set[int] = set()
        stale_template_keys: set[int] = set()
        for operation in package["operations"]:
            public_key = (operation["entity_type"], operation["entity_id"])
            existing = connection.execute(
                """SELECT entity_key, template_key FROM entities
                WHERE entity_type = ? AND entity_id = ?""", public_key,
            ).fetchone()
            if existing:
                entity_keys[public_key] = existing["entity_key"]
                if existing["template_key"] is not None:
                    stale_template_keys.add(existing["template_key"])
                for reference in connection.execute(
                    """SELECT link.evidence_key, evidence.source_key
                    FROM entity_sources link
                    JOIN source_evidence evidence ON evidence.evidence_key = link.evidence_key
                    WHERE link.entity_key = ?""", (existing["entity_key"],),
                ):
                    stale_evidence_keys.add(reference["evidence_key"])
                    stale_source_keys.add(reference["source_key"])
            if operation["operation"] == "upsert":
                data, sources = _split_sources(operation["data"])
                template, territory_fields = _split_territorial_entity(*public_key, data)
                template_key = None
                data_json = None
                if template is None:
                    data_json = _gzip_json(data)
                else:
                    template_sha256 = _sha256_json(template)
                    template_identity = (operation["entity_type"], template_sha256)
                    template_key = template_keys.get(template_identity)
                    if template_key is None:
                        cursor = connection.execute(
                            """INSERT INTO entity_templates(
                                entity_type, template_sha256, data_json
                            ) VALUES (?, ?, ?)""",
                            (operation["entity_type"], template_sha256, _gzip_json(template)),
                        )
                        template_key = cursor.lastrowid
                        template_keys[template_identity] = template_key
                dependencies = tuple(
                    (item["entity_type"], item["entity_id"])
                    for item in operation["dependencies"]
                )
                content_hash = _sha256_json({"data": operation["data"], "dependencies": dependencies})
                connection.execute(
                    """INSERT INTO entities(
                        entity_type, entity_id, entity_revision, content_sha256,
                        data_json, template_key, territory_fields,
                        municipality_ref, zone_ref, observed_at, valid_from, valid_to, confidence,
                        search_text, destination_raw, stream_name, facility_ref
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                        entity_revision=excluded.entity_revision,
                        content_sha256=excluded.content_sha256, data_json=excluded.data_json,
                        template_key=excluded.template_key, territory_fields=excluded.territory_fields,
                        municipality_ref=excluded.municipality_ref, zone_ref=excluded.zone_ref,
                        observed_at=excluded.observed_at,
                        valid_from=excluded.valid_from, valid_to=excluded.valid_to,
                        confidence=excluded.confidence, search_text=excluded.search_text,
                        destination_raw=excluded.destination_raw, stream_name=excluded.stream_name,
                        facility_ref=excluded.facility_ref""",
                    (
                        *public_key, operation["entity_revision"], content_hash,
                        data_json, template_key, territory_fields, *_indexed_fields(operation["data"]),
                    ),
                )
                entity_key = connection.execute(
                    "SELECT entity_key FROM entities WHERE entity_type = ? AND entity_id = ?", public_key,
                ).fetchone()[0]
                entity_keys[public_key] = entity_key
                connection.execute(
                    "DELETE FROM entity_sources WHERE entity_key = ?", (entity_key,),
                )
                for ordinal, (source_id, evidence_id, document_json, evidence_json) in enumerate(sources):
                    source_key = source_keys.get(source_id)
                    if source_key is None:
                        cursor = connection.execute(
                            "INSERT INTO source_documents(source_sha256, document_json) VALUES (?, ?)",
                            (source_id, document_json),
                        )
                        source_key = cursor.lastrowid
                        source_keys[source_id] = source_key
                    evidence_key = evidence_keys.get(evidence_id)
                    if evidence_key is None:
                        cursor = connection.execute(
                            """INSERT INTO source_evidence(
                                evidence_sha256, source_key, evidence_json
                            ) VALUES (?, ?, ?)""",
                            (evidence_id, source_key, evidence_json),
                        )
                        evidence_key = cursor.lastrowid
                        evidence_keys[evidence_id] = evidence_key
                    connection.execute(
                        "INSERT INTO entity_sources VALUES (?, ?, ?)",
                        (entity_key, ordinal, evidence_key),
                    )
                connection.execute(
                    "DELETE FROM tombstones WHERE entity_type = ? AND entity_id = ?", public_key,
                )
            elif operation["operation"] != "delete":
                raise ValueError(f"Unknown operation {operation['operation']}")

        if package["kind"] == "snapshot":
            entity_keys = {
                (row["entity_type"], row["entity_id"]): row["entity_key"]
                for row in connection.execute("SELECT entity_key, entity_type, entity_id FROM entities")
            }
        for operation in package["operations"]:
            if operation["operation"] != "upsert":
                continue
            public_key = (operation["entity_type"], operation["entity_id"])
            entity_key = entity_keys[public_key]
            connection.execute("DELETE FROM entity_dependencies WHERE entity_key = ?", (entity_key,))
            dependencies = [
                (item["entity_type"], item["entity_id"])
                for item in operation["dependencies"]
            ]
            try:
                dependency_keys = []
                for dependency in dependencies:
                    dependency_key = entity_keys.get(dependency)
                    if dependency_key is None:
                        row = connection.execute(
                            """SELECT entity_key FROM entities
                            WHERE entity_type = ? AND entity_id = ?""", dependency,
                        ).fetchone()
                        if row is None:
                            raise KeyError(dependency)
                        dependency_key = row["entity_key"]
                        entity_keys[dependency] = dependency_key
                    dependency_keys.append((entity_key, dependency_key))
                connection.executemany("INSERT INTO entity_dependencies VALUES (?, ?)", dependency_keys)
            except KeyError as error:
                raise ValueError(f"Missing entity dependency {error.args[0]}") from error

        deleted_keys = [
            entity_keys.get((operation["entity_type"], operation["entity_id"]))
            for operation in package["operations"] if operation["operation"] == "delete"
        ]
        connection.executemany(
            "DELETE FROM entity_dependencies WHERE entity_key = ?",
            ((entity_key,) for entity_key in deleted_keys if entity_key is not None),
        )
        for operation in package["operations"]:
            public_key = (operation["entity_type"], operation["entity_id"])
            if operation["operation"] == "delete":
                connection.execute("DELETE FROM entities WHERE entity_type = ? AND entity_id = ?", public_key)
                connection.execute(
                    """INSERT INTO tombstones(entity_type, entity_id, deleted_revision, deleted_at, reason)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                        deleted_revision=excluded.deleted_revision, deleted_at=excluded.deleted_at,
                        reason=excluded.reason""",
                    (*public_key, operation["entity_revision"], operation["deleted_at"], operation.get("reason")),
                )

        for operation in package["operations"]:
            public_key = (operation["entity_type"], operation["entity_id"])
            if metadata.get("role", "server") == "server":
                connection.execute(
                    "INSERT INTO changelog VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        package["to_revision"], operation["sequence"], operation["operation"],
                        *public_key, gzip.compress(_json_bytes(operation), compresslevel=6, mtime=0),
                        package["generated_at"],
                    ),
                )
        connection.executemany(
            """DELETE FROM source_evidence WHERE evidence_key = ? AND NOT EXISTS (
                SELECT 1 FROM entity_sources WHERE entity_sources.evidence_key = source_evidence.evidence_key
            )""",
            ((key,) for key in stale_evidence_keys),
        )
        connection.executemany(
            """DELETE FROM source_documents WHERE source_key = ? AND NOT EXISTS (
                SELECT 1 FROM source_evidence WHERE source_evidence.source_key = source_documents.source_key
            )""",
            ((key,) for key in stale_source_keys),
        )
        connection.executemany(
            """DELETE FROM entity_templates WHERE template_key = ? AND NOT EXISTS (
                SELECT 1 FROM entities WHERE entities.template_key = entity_templates.template_key
            )""",
            ((key,) for key in stale_template_keys),
        )
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise ValueError(f"Foreign key validation failed: {len(violations)} violation(s)")
        connection.execute("UPDATE metadata SET value = ? WHERE key = 'revision'", (str(package["to_revision"]),))
        connection.execute(
            "INSERT INTO package_applications VALUES (?, ?, ?, ?, ?)",
            (
                package["package_id"], package["from_revision"], package["to_revision"],
                package_hash, package["generated_at"],
            ),
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise


def sign_artifact(path: Path, private_key: Path) -> str:
    with tempfile.NamedTemporaryFile() as signature_file:
        subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(private_key), "-in", str(path), "-out", signature_file.name],
            check=True, capture_output=True,
        )
        return base64.b64encode(Path(signature_file.name).read_bytes()).decode("ascii")


def verify_artifact(path: Path, public_key: Path, signature: str) -> None:
    signature_bytes = base64.b64decode(signature, validate=True)
    with tempfile.NamedTemporaryFile() as signature_file:
        Path(signature_file.name).write_bytes(signature_bytes)
        result = subprocess.run(
            ["openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", str(public_key), "-in", str(path), "-sigfile", signature_file.name],
            capture_output=True,
        )
    if result.returncode != 0:
        raise ValueError("Ed25519 artifact signature is invalid")


def _sign_manifest(manifest: dict[str, Any], private_key: Path, key_id: str) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile() as unsigned_file:
        Path(unsigned_file.name).write_bytes(_json_bytes(manifest))
        signature = sign_artifact(Path(unsigned_file.name), private_key)
    return {
        **manifest,
        "signature": {"algorithm": "Ed25519", "key_id": key_id, "value": signature},
    }


def verify_manifest(manifest: dict[str, Any], public_key: Path) -> None:
    signature = manifest.get("signature")
    if not signature or signature.get("algorithm") != "Ed25519":
        raise ValueError("Manifest has no supported signature")
    unsigned = {key: value for key, value in manifest.items() if key != "signature"}
    with tempfile.NamedTemporaryFile() as unsigned_file:
        Path(unsigned_file.name).write_bytes(_json_bytes(unsigned))
        verify_artifact(Path(unsigned_file.name), public_key, signature["value"])


def write_artifact(
    package: dict[str, Any], destination: Path, private_key: Path, key_id: str,
    base_url: str,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(_gzip_json(package))
    temporary.replace(destination)
    body = destination.read_bytes()
    return {
        "package_id": package["package_id"], "kind": package["kind"],
        "from_revision": package["from_revision"], "to_revision": package["to_revision"],
        "url": urljoin(base_url.rstrip("/") + "/", destination.name),
        "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "compression": "gzip",
        "signature": {"algorithm": "Ed25519", "key_id": key_id, "value": sign_artifact(destination, private_key)},
    }


def read_artifact(path: Path, artifact: dict[str, Any], public_key: Path | None = None) -> dict[str, Any]:
    body = path.read_bytes()
    if len(body) != artifact["bytes"] or hashlib.sha256(body).hexdigest() != artifact["sha256"]:
        raise ValueError("Artifact size or SHA-256 does not match the manifest")
    if public_key:
        verify_artifact(path, public_key, artifact["signature"]["value"])
    if artifact["compression"] != "gzip":
        raise ValueError("Only gzip artifacts are supported by this implementation")
    return json.loads(gzip.decompress(body))


def publish_release(
    desired: dict[tuple[str, str], CanonicalEntity], database_path: Path,
    artifact_dir: Path, manifest_path: Path, revision: int, generated_at: datetime,
    private_key: Path, key_id: str, base_url: str,
) -> dict[str, Any]:
    connection = open_database(database_path, role="server")
    try:
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        current_revision = int(metadata["revision"])
        pending_path = manifest_path.with_suffix(manifest_path.suffix + ".pending")
        if pending_path.exists():
            pending = json.loads(pending_path.read_text(encoding="utf-8"))
            if current_revision == pending["latest_revision"]:
                if revision != current_revision:
                    raise ValueError(
                        f"Pending revision {current_revision} must be finalized before revision {revision}"
                    )
                pending_path.replace(manifest_path)
                recovered_delta = next(
                    (item for item in reversed(pending["packages"]) if item["to_revision"] == revision),
                    None,
                )
                return {
                    "revision": revision, "previous_revision": recovered_delta["from_revision"] if recovered_delta else 0,
                    "entities": len(desired), "snapshot_operations": len(desired),
                    "delta_operations": None, "snapshot": pending["latest_snapshot"],
                    "delta": recovered_delta, "recovered_pending_publication": True,
                }
            if current_revision < pending["latest_revision"]:
                pending_path.unlink()
            else:
                raise ValueError("Pending manifest is older than the canonical database")
        current = read_database_entities(connection)
        if revision <= current_revision:
            raise ValueError(f"Revision {revision} does not advance current revision {current_revision}")
        delta = None if current_revision == 0 else build_update_package(current, desired, current_revision, revision, generated_at)
        snapshot = build_update_package({}, desired, None, revision, generated_at)
        snapshot["package_id"] = f"snapshot:{revision}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        snapshot_artifact = write_artifact(
            snapshot, artifact_dir / f"snapshot-{revision}.json.gz", private_key, key_id, base_url,
        )
        delta_artifact = None
        if delta is not None:
            delta["package_id"] = f"delta:{current_revision}:{revision}"
            delta_artifact = write_artifact(
                delta, artifact_dir / f"delta-{current_revision}-{revision}.json.gz",
                private_key, key_id, base_url,
            )
        previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
        packages = list(previous.get("packages", [])) if previous else []
        if delta_artifact:
            packages.append(delta_artifact)
        unsigned_manifest = {
            "format_version": 1, "dataset_id": DATASET_ID, "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at.isoformat(), "latest_revision": revision,
            "minimum_incremental_revision": previous["minimum_incremental_revision"] if previous else revision,
            "minimum_client_version": previous.get("minimum_client_version") if previous else "1.0.0",
            "latest_snapshot": snapshot_artifact, "packages": packages,
        }
        manifest = _sign_manifest(unsigned_manifest, private_key, key_id)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        pending_path.write_bytes(_json_bytes(manifest))
        package_to_apply = snapshot if delta is None else delta
        artifact_to_apply = snapshot_artifact if delta_artifact is None else delta_artifact
        apply_package(connection, package_to_apply, artifact_to_apply["sha256"])
        pending_path.replace(manifest_path)
        return {
            "revision": revision, "previous_revision": current_revision,
            "entities": len(desired), "snapshot_operations": len(snapshot["operations"]),
            "delta_operations": len(delta["operations"]) if delta else None,
            "snapshot": snapshot_artifact, "delta": delta_artifact,
        }
    finally:
        connection.close()


def apply_manifest_package(
    database_path: Path, manifest_path: Path, package_id: str,
    artifact_root: Path, public_key: Path | None,
) -> bool:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if public_key:
        verify_manifest(manifest, public_key)
    artifacts = [manifest["latest_snapshot"], *manifest["packages"]]
    artifact = next((item for item in artifacts if item["package_id"] == package_id), None)
    if artifact is None:
        raise ValueError(f"Package {package_id} is not present in the manifest")
    artifact_path = artifact_root / Path(artifact["url"]).name
    package = read_artifact(artifact_path, artifact, public_key)
    connection = open_database(database_path, role="client")
    try:
        return apply_package(connection, package, artifact["sha256"])
    finally:
        connection.close()


def plan_update(manifest: dict[str, Any], current_revision: int) -> list[dict[str, Any]]:
    latest = manifest["latest_revision"]
    if current_revision == latest:
        return []
    snapshot = manifest["latest_snapshot"]
    if current_revision == 0 or current_revision < manifest["minimum_incremental_revision"]:
        return [snapshot]
    edges: dict[int, list[dict[str, Any]]] = {}
    for artifact in manifest["packages"]:
        if artifact["kind"] == "delta":
            edges.setdefault(artifact["from_revision"], []).append(artifact)
    distances = {current_revision: 0}
    paths: dict[int, list[dict[str, Any]]] = {current_revision: []}
    pending = {current_revision}
    while pending:
        revision = min(pending, key=lambda item: distances[item])
        pending.remove(revision)
        for artifact in edges.get(revision, []):
            target = artifact["to_revision"]
            distance = distances[revision] + artifact["bytes"]
            if target not in distances or distance < distances[target]:
                distances[target] = distance
                paths[target] = [*paths[revision], artifact]
                pending.add(target)
    delta_path = paths.get(latest)
    if delta_path is None or sum(item["bytes"] for item in delta_path) >= snapshot["bytes"]:
        return [snapshot]
    return delta_path


def _database_revision(path: Path) -> int:
    if not path.exists():
        return 0
    connection = open_database(path, role="client")
    try:
        return int(connection.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0])
    finally:
        connection.close()


def apply_update_plan(
    database_path: Path, manifest_path: Path, artifact_root: Path, public_key: Path,
) -> list[str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verify_manifest(manifest, public_key)
    current_revision = _database_revision(database_path)
    artifacts = plan_update(manifest, current_revision)
    if not artifacts:
        return []
    if artifacts[0]["kind"] == "snapshot":
        temporary = database_path.with_suffix(database_path.suffix + ".next")
        if temporary.exists():
            temporary.unlink()
        apply_manifest_package(
            temporary, manifest_path, artifacts[0]["package_id"], artifact_root, public_key,
        )
        if _database_revision(temporary) != manifest["latest_revision"]:
            temporary.unlink(missing_ok=True)
            raise ValueError("Snapshot did not produce the manifest revision")
        database_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, database_path)
        return [artifacts[0]["package_id"]]
    applied = []
    for artifact in artifacts:
        apply_manifest_package(
            database_path, manifest_path, artifact["package_id"], artifact_root, public_key,
        )
        applied.append(artifact["package_id"])
    if _database_revision(database_path) != manifest["latest_revision"]:
        raise ValueError("Delta path did not produce the manifest revision")
    return applied
