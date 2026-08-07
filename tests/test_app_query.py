from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dovelobutto.app_query import DisposalQueryService, open_query_database
from dovelobutto.sync import (
    CanonicalEntity,
    apply_package,
    build_update_package,
    open_database,
    read_database_entities,
)


GENERATED_AT = datetime.fromisoformat("2026-08-07T22:00:00+02:00")


def _concept(
    concept_id: str,
    label: str,
    destinations: list[str],
) -> CanonicalEntity:
    return CanonicalEntity("waste_concept", concept_id, {
        "concept_id": concept_id,
        "preferred_label": label,
        "normalized_term": label.casefold(),
        "terms": [label],
        "language": "it",
        "eer": {"status": "not_available", "candidates": []},
        "source_categories": [],
        "local_destinations": [
            {
                "label": destination,
                "municipality_istats": ["053014"],
                "source_urls": ["https://example.test/rifiutario"],
            }
            for destination in destinations
        ],
        "coverage": {
            "municipalities": ["053014"],
            "publishers": ["Gestore di prova"],
            "source_assertions": 1,
        },
        "general_details": {
            "material": None,
            "conditions": [],
            "environmental_note": None,
            "review_status": "automatic_source_identity",
        },
        "evidence": [{
            "source_url": "https://example.test/rifiutario",
            "publisher": "Gestore di prova",
            "retrieved_at": "2026-08-07T20:00:00+02:00",
            "municipality_istats": ["053014"],
            "destination_raw": destinations[0] if destinations else None,
            "instructions_raw": None,
            "quote": label,
        }],
    })


def _rule(
    rule_id: str,
    stream: str,
    *,
    zone: str | None = None,
    color: str = "verde",
    user_type: str = "domestic",
) -> CanonicalEntity:
    payload = {
        "municipality_ref": "istat:053014",
        "zone_ref": zone,
        "stream_name": stream,
        "user_type": user_type,
        "collection_method": "street",
        "container_type": "contenitore",
        "container_color": color,
        "access_credential": None,
        "presentation": {"mode": "loose", "instructions_raw": "Conferire sfuso"},
    }
    return CanonicalEntity("collection_rule", rule_id, {
        "natural_key": rule_id,
        "payload": payload,
        "sources": [{
            "url": "https://example.test/regole",
            "publisher": "Gestore di prova",
            "retrieved_at": "2026-08-07T21:00:00+02:00",
            "evidence": {"quote": stream},
        }],
    })


def _entities() -> dict[tuple[str, str], CanonicalEntity]:
    values = [
        CanonicalEntity(
            "municipality", "istat:053014",
            {"payload": {"name": "Manciano", "istat_code": "053014"}},
        ),
        _concept("waste:bottiglia-di-vetro", "Bottiglia di vetro", ["Vetro"]),
        _concept("waste:carta-da-regalo", "Carta da regalo", ["Carta e cartone"]),
        _rule("rule:vetro", "Vetro"),
    ]
    return {(item.entity_type, item.entity_id): item for item in values}


class DisposalQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.database = Path(self.temporary.name) / "client.sqlite"
        connection = open_database(self.database, role="client")
        apply_package(connection, build_update_package({}, _entities(), None, 1, GENERATED_AT))
        connection.close()
        self.connection = open_query_database(self.database)
        self.service = DisposalQueryService(self.connection)

    def tearDown(self) -> None:
        self.connection.close()
        self.temporary.cleanup()

    def test_fuzzy_search_recovers_a_typo(self) -> None:
        results = self.service.search("botiglia di vtro", municipality_istat="053014")
        self.assertEqual("waste:bottiglia-di-vetro", results[0]["concept_id"])
        self.assertTrue(results[0]["available_in_municipality"])

    def test_answer_combines_destination_container_and_provenance(self) -> None:
        answer = self.service.answer(
            "bottiglia di vetro", "053014", as_of=date(2026, 8, 7),
        )
        self.assertEqual("resolved", answer["status"])
        self.assertEqual("Vetro", answer["result"]["stream"])
        self.assertEqual("verde", answer["result"]["container"]["color"])
        self.assertEqual("loose", answer["result"]["presentation"]["mode"])
        self.assertEqual(2, len(answer["provenance"]["sources"]))
        self.assertEqual(1, answer["provenance"]["dataset_revision"])

    def test_unknown_term_does_not_invent_a_destination(self) -> None:
        answer = self.service.answer("teletrasportatore", "053014")
        self.assertEqual("not_found", answer["status"])
        self.assertIsNone(answer["result"])
        self.assertEqual([], answer["provenance"]["sources"])
        invalid_choice = self.service.answer(
            "bottiglia di vetro", "053014", concept_id="waste:inesistente",
        )
        self.assertEqual("not_found", invalid_choice["status"])

    def test_uncertain_similarity_requires_confirmation(self) -> None:
        answer = self.service.answer("carta colorata", "053014")
        self.assertEqual("needs_question", answer["status"])
        self.assertIsNone(answer["result"])
        chosen = self.service.answer(
            "carta colorata",
            "053014",
            concept_id="waste:carta-da-regalo",
        )
        self.assertEqual("resolved", chosen["status"])
        self.assertEqual("Carta e cartone", chosen["result"]["stream"])

    def test_conflicting_local_destinations_remain_visible(self) -> None:
        current = read_database_entities(self.connection)
        changed = dict(current)
        conflict = _concept("waste:bicchiere", "Bicchiere", ["Vetro", "Indifferenziato"])
        changed[(conflict.entity_type, conflict.entity_id)] = conflict
        self.connection.close()
        writer = open_database(self.database, role="client")
        apply_package(writer, build_update_package(current, changed, 1, 2, GENERATED_AT))
        writer.close()
        self.connection = open_query_database(self.database)
        self.service = DisposalQueryService(self.connection)
        answer = self.service.answer("bicchiere", "053014")
        self.assertEqual("conflict", answer["status"])
        self.assertEqual(2, len(answer["question"]["options"]))

    def test_zone_question_is_asked_only_when_rules_differ(self) -> None:
        self.connection.close()
        writer = open_database(self.database, role="client")
        current = read_database_entities(writer)
        changed = dict(current)
        changed[("collection_rule", "rule:carta:a")] = _rule(
            "rule:carta:a", "Carta e cartone", zone="zone:a", color="blu",
        )
        changed[("collection_rule", "rule:carta:b")] = _rule(
            "rule:carta:b", "Carta e cartone", zone="zone:b", color="giallo",
        )
        for zone_id, name in (("zone:a", "Centro"), ("zone:b", "Frazioni")):
            changed[("service_zone", zone_id)] = CanonicalEntity(
                "service_zone", zone_id,
                {"payload": {"municipality_ref": "istat:053014", "name": name}},
            )
        apply_package(writer, build_update_package(current, changed, 1, 2, GENERATED_AT))
        writer.close()
        self.connection = open_query_database(self.database)
        self.service = DisposalQueryService(self.connection)
        answer = self.service.answer("carta da regalo", "053014")
        self.assertEqual("needs_question", answer["status"])
        self.assertEqual(["Centro", "Frazioni"], [
            option["label"] for option in answer["question"]["options"]
        ])

    def test_delta_replaces_search_terms_atomically(self) -> None:
        self.connection.close()
        writer = open_database(self.database, role="client")
        current = read_database_entities(writer)
        changed = dict(current)
        changed[("waste_concept", "waste:bottiglia-di-vetro")] = _concept(
            "waste:bottiglia-di-vetro", "Flacone di vetro", ["Vetro"],
        )
        apply_package(writer, build_update_package(current, changed, 1, 2, GENERATED_AT))
        terms = [row[0] for row in writer.execute(
            "SELECT term FROM waste_search_terms ORDER BY term"
        )]
        self.assertIn("Flacone di vetro", terms)
        self.assertNotIn("Bottiglia di vetro", terms)
        writer.close()
        self.connection = open_query_database(self.database)

    def test_deleting_a_concept_removes_its_search_terms(self) -> None:
        self.connection.close()
        writer = open_database(self.database, role="client")
        current = read_database_entities(writer)
        changed = dict(current)
        changed.pop(("waste_concept", "waste:bottiglia-di-vetro"))
        apply_package(writer, build_update_package(current, changed, 1, 2, GENERATED_AT))
        self.assertEqual(0, writer.execute(
            """SELECT COUNT(*) FROM waste_search_terms term
            JOIN entities entity ON entity.entity_key = term.entity_key
            WHERE entity.entity_id = 'waste:bottiglia-di-vetro'"""
        ).fetchone()[0])
        writer.close()
        self.connection = open_query_database(self.database)

    def test_reviewed_aliases_and_streams_compose_one_local_answer(self) -> None:
        self.connection.close()
        writer = open_database(self.database, role="client")
        current = read_database_entities(writer)
        changed = dict(current)
        first = _concept(
            "waste:tetrapak-latte", "Tetrapak confezione latte",
            ["Imballaggi e contenitori"],
        )
        second = _concept(
            "waste:cartone-latte", "Cartone del latte (Tetra Pak)", ["Multimateriale"],
        )
        changed[(first.entity_type, first.entity_id)] = first
        changed[(second.entity_type, second.entity_id)] = second
        changed[("waste_alias_group", "waste-alias:beverage-carton")] = CanonicalEntity(
            "waste_alias_group", "waste-alias:beverage-carton", {
                "group_id": "waste-alias:beverage-carton",
                "preferred_label": "Cartone per bevande (Tetra Pak)",
                "search_terms": ["Confezione del latte", "Cartone del latte"],
                "member_concept_ids": [first.entity_id, second.entity_id],
                "review_status": "approved",
                "rationale": "Varianti controllate",
            }, (
                ("waste_concept", first.entity_id),
                ("waste_concept", second.entity_id),
            ),
        )
        changed[("collection_stream", "stream:mixed-packaging")] = CanonicalEntity(
            "collection_stream", "stream:mixed-packaging", {
                "stream_id": "stream:mixed-packaging",
                "preferred_label": "Multimateriale",
                "aliases": ["Imballaggi e contenitori", "Multimateriale"],
            },
        )
        changed[("collection_rule", "rule:multimateriale")] = _rule(
            "rule:multimateriale", "Multimateriale", color="giallo", user_type="all",
        )
        apply_package(writer, build_update_package(current, changed, 1, 2, GENERATED_AT))
        writer.close()
        self.connection = open_query_database(self.database)
        self.service = DisposalQueryService(self.connection)
        answer = self.service.answer("confezzione del latte", "053014")
        self.assertEqual("resolved", answer["status"])
        self.assertEqual("waste-alias:beverage-carton", answer["query"]["matched_concept_id"])
        self.assertEqual("stream:mixed-packaging", answer["result"]["stream_id"])
        self.assertEqual("giallo", answer["result"]["container"]["color"])
        self.assertNotEqual("conflict", answer["status"])

    def test_compound_destination_returns_all_delivery_channels(self) -> None:
        self.connection.close()
        writer = open_database(self.database, role="client")
        current = read_database_entities(writer)
        changed = dict(current)
        armadio = _concept(
            "waste:armadio", "Armadio", ["Ecocentro - ritiro ingombranti"],
        )
        changed[(armadio.entity_type, armadio.entity_id)] = armadio
        changed[("collection_rule", "rule:ingombranti")] = _rule(
            "rule:ingombranti", "Ritiro ingombranti",
        )
        channel_specs = [
            (
                "channel:collection-centre", "Centro di raccolta", "facility",
                ["Centro di raccolta", "Ecocentro"],
            ),
            (
                "channel:home-pickup", "Ritiro a domicilio", "pickup",
                ["Ritiro ingombranti", "Ritiro a domicilio"],
            ),
        ]
        for channel_id, label, destination_type, aliases in channel_specs:
            changed[("delivery_channel", channel_id)] = CanonicalEntity(
                "delivery_channel", channel_id, {
                    "channel_id": channel_id,
                    "preferred_label": label,
                    "destination_type": destination_type,
                    "aliases": aliases,
                },
            )
        apply_package(writer, build_update_package(current, changed, 1, 2, GENERATED_AT))
        writer.close()
        self.connection = open_query_database(self.database)
        self.service = DisposalQueryService(self.connection)
        answer = self.service.answer("armadio", "053014")
        self.assertEqual("resolved", answer["status"])
        self.assertEqual("special_case", answer["result"]["destination_type"])
        self.assertEqual("alternatives", answer["result"]["channel_relation"])
        self.assertIsNone(answer["result"]["stream"])
        self.assertEqual("Ecocentro - ritiro ingombranti", answer["result"]["source_destination"])
        self.assertEqual(
            ["channel:collection-centre", "channel:home-pickup"],
            [item["channel_id"] for item in answer["result"]["delivery_channels"]],
        )
        self.assertIn("centro utilizzabile", " ".join(answer["result"]["warnings"]))

    def test_equivalent_single_channel_aliases_do_not_create_a_conflict(self) -> None:
        self.connection.close()
        writer = open_database(self.database, role="client")
        current = read_database_entities(writer)
        changed = dict(current)
        armadio = _concept(
            "waste:armadio", "Armadio", ["Ecocentro", "Centro di raccolta"],
        )
        changed[(armadio.entity_type, armadio.entity_id)] = armadio
        changed[("delivery_channel", "channel:collection-centre")] = CanonicalEntity(
            "delivery_channel", "channel:collection-centre", {
                "channel_id": "channel:collection-centre",
                "preferred_label": "Centro di raccolta",
                "destination_type": "facility",
                "aliases": ["Centro di raccolta", "Ecocentro"],
            },
        )
        apply_package(writer, build_update_package(current, changed, 1, 2, GENERATED_AT))
        writer.close()
        self.connection = open_query_database(self.database)
        self.service = DisposalQueryService(self.connection)
        answer = self.service.answer("armadio", "053014")
        self.assertEqual("resolved", answer["status"])
        self.assertEqual("single", answer["result"]["channel_relation"])
        self.assertEqual("facility", answer["result"]["destination_type"])


if __name__ == "__main__":
    unittest.main()
