from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3
import subprocess
from tempfile import TemporaryDirectory
import unittest

from dovelobutto.sync import (
    CanonicalEntity,
    apply_manifest_package,
    apply_package,
    apply_update_plan,
    build_update_package,
    load_canonical_entities,
    open_database,
    publish_release,
    plan_update,
    read_database_entities,
)


GENERATED_AT = datetime.fromisoformat("2026-08-07T15:00:00+02:00")


def _entities(opening_hours: str = "08:00-12:00", include_point: bool = True) -> dict[tuple[str, str], CanonicalEntity]:
    values = [
        CanonicalEntity("municipality", "istat:053014", {"payload": {"name": "Manciano", "istat_code": "053014"}}),
        CanonicalEntity(
            "facility", "facility:test:manciano", {"payload": {
                "name": "Centro di prova", "municipality_ref": "istat:053014",
            }}, (("municipality", "istat:053014"),),
        ),
        CanonicalEntity(
            "opening_period", "opening:test:manciano", {"payload": {
                "facility_ref": "facility:test:manciano", "hours": opening_hours,
            }}, (("facility", "facility:test:manciano"),),
        ),
    ]
    if include_point:
        values.append(CanonicalEntity(
            "collection_point", "point:test:manciano", {"payload": {
                "municipality_ref": "istat:053014", "name": "Punto di prova",
            }}, (("municipality", "istat:053014"),),
        ))
    return {(entity.entity_type, entity.entity_id): entity for entity in values}


class SyncTests(unittest.TestCase):
    def test_snapshot_and_delta_are_atomic_and_idempotent(self) -> None:
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "client.sqlite"
            connection = open_database(database)
            snapshot = build_update_package({}, _entities(), None, 202608070001, GENERATED_AT)
            self.assertTrue(apply_package(connection, snapshot))
            self.assertFalse(apply_package(connection, snapshot))
            current = read_database_entities(connection)
            desired = _entities("09:00-13:00", include_point=False)
            delta = build_update_package(current, desired, 202608070001, 202608070002, GENERATED_AT)
            self.assertEqual(["upsert", "delete"], [item["operation"] for item in delta["operations"]])
            self.assertTrue(apply_package(connection, delta))
            self.assertEqual("202608070002", connection.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0])
            self.assertEqual(
                "09:00-13:00",
                read_database_entities(connection)[("opening_period", "opening:test:manciano")].data["payload"]["hours"],
            )
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM tombstones WHERE entity_type='collection_point'").fetchone()[0])
            connection.close()

    def test_storage_deduplicates_sources_and_reconstructs_entities(self) -> None:
        with TemporaryDirectory() as temporary:
            connection = open_database(Path(temporary) / "client.sqlite", role="client")
            common_source = {"url": "https://example.test/page", "title": "Guida"}
            entities = {}
            for number, quote in enumerate(("Carta", "Vetro"), 1):
                entity = CanonicalEntity(
                    "collection_rule", f"rule:{number}",
                    {"payload": {"municipality_ref": "istat:053014", "term": quote}, "sources": [
                        {**common_source, "evidence": {"selector": "table", "quote": quote}},
                    ]},
                )
                entities[(entity.entity_type, entity.entity_id)] = entity
            empty_sources = CanonicalEntity(
                "collection_rule", "rule:empty-sources", {"payload": {"term": "Altro"}, "sources": []},
            )
            entities[(empty_sources.entity_type, empty_sources.entity_id)] = empty_sources
            apply_package(connection, build_update_package({}, entities, None, 1, GENERATED_AT))
            reconstructed = read_database_entities(connection)
            self.assertEqual(entities, {
                key: CanonicalEntity(value.entity_type, value.entity_id, value.data, value.dependencies)
                for key, value in reconstructed.items()
            })
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0])
            self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM source_evidence").fetchone()[0])
            self.assertEqual("blob", connection.execute("SELECT typeof(data_json) FROM entities LIMIT 1").fetchone()[0])
            self.assertEqual("carta", connection.execute(
                "SELECT search_text FROM entities WHERE entity_id='rule:1'"
            ).fetchone()[0])
            connection.close()

    def test_storage_deduplicates_territorial_templates(self) -> None:
        with TemporaryDirectory() as temporary:
            connection = open_database(Path(temporary) / "client.sqlite", role="client")
            entities = {}
            for suffix, municipality in (("a", "istat:001"), ("b", "istat:002")):
                entity = CanonicalEntity(
                    "waste_lookup", f"lookup:{suffix}", {
                        "natural_key": f"lookup:{suffix}",
                        "payload": {
                            "municipality_ref": municipality,
                            "zone_ref": f"zone:{suffix}",
                            "term": "Bottiglia di vetro",
                            "destination_raw": "Vetro",
                        },
                        "confidence": "high",
                    },
                )
                entities[(entity.entity_type, entity.entity_id)] = entity
            apply_package(connection, build_update_package({}, entities, None, 1, GENERATED_AT))
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM entity_templates").fetchone()[0])
            self.assertEqual(2, connection.execute(
                "SELECT COUNT(*) FROM entities WHERE template_key IS NOT NULL AND data_json IS NULL"
            ).fetchone()[0])
            reconstructed = read_database_entities(connection)
            self.assertEqual(entities, {
                key: CanonicalEntity(value.entity_type, value.entity_id, value.data, value.dependencies)
                for key, value in reconstructed.items()
            })

            desired = dict(entities)
            first = desired[("waste_lookup", "lookup:a")]
            changed_data = json.loads(json.dumps(first.data))
            changed_data["payload"]["destination_raw"] = "Multimateriale"
            desired[("waste_lookup", "lookup:a")] = CanonicalEntity(
                first.entity_type, first.entity_id, changed_data,
            )
            apply_package(connection, build_update_package(reconstructed, desired, 1, 2, GENERATED_AT))
            self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM entity_templates").fetchone()[0])

            current = read_database_entities(connection)
            desired.pop(("waste_lookup", "lookup:b"))
            apply_package(connection, build_update_package(current, desired, 2, 3, GENERATED_AT))
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM entity_templates").fetchone()[0])
            self.assertEqual(desired[("waste_lookup", "lookup:a")].data, read_database_entities(
                connection
            )[("waste_lookup", "lookup:a")].data)
            connection.close()

    def test_invalid_dependency_rolls_back_every_operation(self) -> None:
        with TemporaryDirectory() as temporary:
            connection = open_database(Path(temporary) / "client.sqlite")
            snapshot = build_update_package({}, _entities(), None, 1, GENERATED_AT)
            apply_package(connection, snapshot)
            broken = {
                "format_version": 1, "dataset_id": "comesibutta-toscana", "schema_version": 1,
                "package_id": "delta:1:2", "kind": "delta", "generated_at": GENERATED_AT.isoformat(),
                "from_revision": 1, "to_revision": 2,
                "operations": [{
                    "sequence": 1, "operation": "upsert", "entity_type": "opening_period",
                    "entity_id": "opening:broken", "entity_revision": 2,
                    "dependencies": [{"entity_type": "facility", "entity_id": "facility:missing"}],
                    "data": {"payload": {"facility_ref": "facility:missing"}},
                }],
            }
            with self.assertRaises((ValueError, sqlite3.IntegrityError)):
                apply_package(connection, broken)
            self.assertEqual("1", connection.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0])
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM entities WHERE entity_id='opening:broken'").fetchone()[0])
            connection.close()

    def test_rejects_delta_for_a_different_client_revision(self) -> None:
        with TemporaryDirectory() as temporary:
            connection = open_database(Path(temporary) / "client.sqlite")
            delta = build_update_package({}, _entities(), 9, 10, GENERATED_AT)
            with self.assertRaisesRegex(ValueError, "client is at 0"):
                apply_package(connection, delta)
            connection.close()

    def test_empty_delta_advances_revision_without_changing_entities(self) -> None:
        with TemporaryDirectory() as temporary:
            connection = open_database(Path(temporary) / "client.sqlite", role="client")
            entities = _entities()
            apply_package(connection, build_update_package({}, entities, None, 1, GENERATED_AT))
            current = read_database_entities(connection)
            delta = build_update_package(current, current, 1, 2, GENERATED_AT)
            self.assertEqual([], delta["operations"])
            self.assertTrue(apply_package(connection, delta))
            self.assertEqual("2", connection.execute(
                "SELECT value FROM metadata WHERE key='revision'"
            ).fetchone()[0])
            self.assertEqual(current, read_database_entities(connection))
            connection.close()

    def test_old_storage_requires_snapshot_rebuild(self) -> None:
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "old.sqlite"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO metadata VALUES ('schema_version', '1')")
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(ValueError, "rebuild the database from a snapshot"):
                open_database(database)

    def test_cannot_delete_an_entity_that_remains_referenced(self) -> None:
        with TemporaryDirectory() as temporary:
            connection = open_database(Path(temporary) / "client.sqlite")
            apply_package(connection, build_update_package({}, _entities(), None, 1, GENERATED_AT))
            current = read_database_entities(connection)
            desired = dict(current)
            del desired[("facility", "facility:test:manciano")]
            delta = build_update_package(current, desired, 1, 2, GENERATED_AT)
            with self.assertRaises((ValueError, sqlite3.IntegrityError)):
                apply_package(connection, delta)
            self.assertEqual("1", connection.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0])
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM entities WHERE entity_type='facility'").fetchone()[0])
            connection.close()

    def test_signed_release_can_initialize_a_client(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            private_key = root / "private.pem"
            public_key = root / "public.pem"
            subprocess.run(["openssl", "genpkey", "-algorithm", "Ed25519", "-out", str(private_key)], check=True, capture_output=True)
            subprocess.run(["openssl", "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)], check=True, capture_output=True)
            manifest_path = root / "manifest.json"
            report = publish_release(
                _entities(), root / "server.sqlite", root / "artifacts", manifest_path,
                202608070001, GENERATED_AT, private_key, "test-key", "https://data.example.test/",
            )
            self.assertEqual(4, report["entities"])
            pending_path = manifest_path.with_suffix(".json.pending")
            manifest_path.replace(pending_path)
            recovered = publish_release(
                _entities(), root / "server.sqlite", root / "artifacts", manifest_path,
                202608070001, GENERATED_AT, private_key, "test-key", "https://data.example.test/",
            )
            self.assertTrue(recovered["recovered_pending_publication"])
            package_id = json.loads(manifest_path.read_text())["latest_snapshot"]["package_id"]
            self.assertTrue(apply_manifest_package(
                root / "client.sqlite", manifest_path, package_id, root / "artifacts", public_key,
            ))
            self.assertEqual([package_id], apply_update_plan(
                root / "planned-client.sqlite", manifest_path, root / "artifacts", public_key,
            ))
            client = open_database(root / "client.sqlite", role="client")
            self.assertEqual(4, client.execute("SELECT COUNT(*) FROM entities").fetchone()[0])
            self.assertEqual(0, client.execute("SELECT COUNT(*) FROM changelog").fetchone()[0])
            client.close()
            tampered = json.loads(manifest_path.read_text())
            tampered["generated_at"] = "2026-08-07T16:00:00+02:00"
            tampered_path = root / "tampered-manifest.json"
            tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "signature is invalid"):
                apply_manifest_package(
                    root / "other-client.sqlite", tampered_path, package_id,
                    root / "artifacts", public_key,
                )

    def test_loader_preserves_distinct_source_assertions_with_same_natural_key(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "input"
            inputs.mkdir()
            common = {
                "record_type": "collection_rule", "natural_key": "rule:test", "observed_at": GENERATED_AT.isoformat(),
                "validity": {"valid_from": None, "valid_to": None, "inferred": True}, "confidence": "high",
                "source": {"url": "https://example.test", "evidence": {"selector": "table", "page": None, "quote": "row"}},
            }
            records = [
                {**common, "payload": {"stream_name": "Carta", "container_color": "blu"}},
                {**common, "payload": {"stream_name": "Carta", "container_color": "bianco"}},
            ]
            (inputs / "test-acquisition.jsonl").write_text(
                "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8",
            )
            registry = root / "registry.jsonl"
            registry.write_text("", encoding="utf-8")
            entities = load_canonical_entities([inputs], [registry])
        self.assertEqual(2, len(entities))
        self.assertTrue(all(":variant:" in entity_id for _, entity_id in entities))

    def test_loader_links_collection_schedule_to_its_rule(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "input"
            inputs.mkdir()
            common = {
                "observed_at": GENERATED_AT.isoformat(),
                "validity": {"valid_from": None, "valid_to": None, "inferred": False},
                "confidence": "high",
                "source": {
                    "url": "https://example.test/calendar.pdf",
                    "evidence": {"selector": "calendar-grid", "page": None, "quote": "2026"},
                },
            }
            records = [
                {
                    **common, "record_type": "collection_rule", "natural_key": "rule:test",
                    "payload": {"stream_name": "Rifiuto residuo"},
                },
                {
                    **common, "record_type": "collection_schedule", "natural_key": "schedule:test",
                    "payload": {"collection_rule_ref": "rule:test", "events": []},
                },
            ]
            (inputs / "test-acquisition.jsonl").write_text(
                "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8",
            )
            registry = root / "registry.jsonl"
            registry.write_text("", encoding="utf-8")
            entities = load_canonical_entities([inputs], [registry])
        self.assertEqual(
            (("collection_rule", "rule:test"),),
            entities[("collection_schedule", "schedule:test")].dependencies,
        )

    def test_loader_links_collection_schedule_to_its_point(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "input"
            inputs.mkdir()
            common = {
                "observed_at": GENERATED_AT.isoformat(),
                "validity": {"valid_from": None, "valid_to": None, "inferred": False},
                "confidence": "high",
                "source": {
                    "url": "https://example.test/calendar.pdf",
                    "evidence": {"selector": "calendar-stop", "page": None, "quote": "2026"},
                },
            }
            records = [
                {
                    **common, "record_type": "collection_point", "natural_key": "point:test",
                    "payload": {"name": "Ecomobile"},
                },
                {
                    **common, "record_type": "collection_schedule", "natural_key": "schedule:test",
                    "payload": {"collection_point_ref": "point:test", "events": []},
                },
            ]
            (inputs / "test-acquisition.jsonl").write_text(
                "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8",
            )
            registry = root / "registry.jsonl"
            registry.write_text("", encoding="utf-8")
            entities = load_canonical_entities([inputs], [registry])
        self.assertEqual(
            (("collection_point", "point:test"),),
            entities[("collection_schedule", "schedule:test")].dependencies,
        )

    def test_planner_chooses_smallest_valid_path(self) -> None:
        def artifact(package_id: str, kind: str, start: int | None, end: int, size: int) -> dict:
            return {
                "package_id": package_id, "kind": kind, "from_revision": start,
                "to_revision": end, "url": package_id, "bytes": size,
                "sha256": "0" * 64, "compression": "gzip",
                "signature": {"algorithm": "Ed25519", "key_id": "test", "value": "test"},
            }
        snapshot = artifact("snapshot:3", "snapshot", None, 3, 100)
        first = artifact("delta:1:2", "delta", 1, 2, 10)
        second = artifact("delta:2:3", "delta", 2, 3, 20)
        direct = artifact("delta:1:3", "delta", 1, 3, 40)
        manifest = {
            "latest_revision": 3, "minimum_incremental_revision": 1,
            "latest_snapshot": snapshot, "packages": [first, second, direct],
        }
        self.assertEqual([first, second], plan_update(manifest, 1))
        self.assertEqual([snapshot], plan_update(manifest, 0))
        self.assertEqual([], plan_update(manifest, 3))


if __name__ == "__main__":
    unittest.main()
