from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dovelobutto.app_query import (
    DisposalQueryService,
    _description_matches_terms,
    open_query_database,
)
from dovelobutto.web_api import DisposalApi
from dovelobutto.query_coverage import audit_query_coverage
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


def _facility(
    facility_id: str,
    name: str,
    latitude: float,
    longitude: float,
    *,
    status: str = "open",
) -> CanonicalEntity:
    return CanonicalEntity("facility", facility_id, {
        "natural_key": facility_id,
        "payload": {
            "name": name,
            "municipality_ref": "istat:053014",
            "facility_type": "collection_centre",
            "address_raw": f"Via {name} 1",
            "location": {
                "latitude": latitude,
                "longitude": longitude,
                "method": "publisher_gis",
                "accuracy_m": None,
            },
            "phone": "800000000",
            "email": "centro@example.test",
            "operational_status": status,
            "status_raw": "Chiuso per lavori" if status == "temporarily_closed" else None,
        },
        "sources": [{
            "url": f"https://example.test/{facility_id}",
            "publisher": "Gestore di prova",
            "retrieved_at": "2026-08-07T20:00:00+02:00",
        }],
    })


def _facility_access(facility_id: str) -> CanonicalEntity:
    entity_id = f"{facility_id}:access"
    return CanonicalEntity("facility_access", entity_id, {
        "natural_key": entity_id,
        "payload": {
            "facility_ref": facility_id,
            "municipality_ref": "istat:053014",
            "user_type": "domestic",
            "allowed": True,
            "requirements_raw": "Mostrare la tessera sanitaria",
            "booking_required": False,
            "information_urls": [f"https://example.test/{facility_id}/accesso"],
            "contact_phone": None,
            "contact_email": None,
        },
        "sources": [{
            "url": f"https://example.test/{facility_id}/accesso",
            "publisher": "Gestore di prova",
            "retrieved_at": "2026-08-07T20:00:00+02:00",
        }],
    }, (("facility", facility_id),))


def _facility_acceptance(
    facility_id: str,
    description: str,
    *,
    eer_code: str | None = None,
) -> CanonicalEntity:
    entity_id = f"{facility_id}:acceptance:{description.casefold()}"
    return CanonicalEntity("facility_acceptance", entity_id, {
        "natural_key": entity_id,
        "payload": {
            "facility_ref": facility_id,
            "eer_code_raw": eer_code,
            "eer_code_normalized": eer_code,
            "eer_code_status": "exact" if eer_code else "unmapped_description",
            "reconciliation_basis": None,
            "hazardous": None,
            "description_raw": description,
            "operational_group": None,
            "user_type": "unspecified",
            "quantity_limit_raw": "Massimo due pezzi",
            "notes_raw": None,
        },
        "sources": [{
            "url": f"https://example.test/{facility_id}/materiali",
            "publisher": "Gestore di prova",
            "retrieved_at": "2026-08-07T20:00:00+02:00",
        }],
    }, (("facility", facility_id),))


def _opening_period(facility_id: str) -> CanonicalEntity:
    entity_id = f"{facility_id}:opening"
    return CanonicalEntity("opening_period", entity_id, {
        "natural_key": entity_id,
        "payload": {
            "facility_ref": facility_id,
            "period_label": "Orario annuale",
            "start_month_day": None,
            "end_month_day": None,
            "weekly_intervals": [{"weekday": 1, "opens": "08:00", "closes": "12:00"}],
            "exceptions_raw": "Chiuso nei festivi",
        },
        "sources": [{
            "url": f"https://example.test/{facility_id}/orari",
            "publisher": "Gestore di prova",
            "retrieved_at": "2026-08-07T20:00:00+02:00",
        }],
    }, (("facility", facility_id),))


def _pickup_service() -> CanonicalEntity:
    return CanonicalEntity("pickup_service", "pickup:ingombranti", {
        "natural_key": "pickup:ingombranti",
        "payload": {
            "municipality_ref": "istat:053014",
            "zone_ref": None,
            "user_type": "domestic",
            "accepted_waste_raw": "Rifiuti ingombranti",
            "booking_methods": [{
                "method": "phone", "value": "800000000", "hours_raw": "8:00-18:00",
            }],
            "max_items": 3,
            "quantity_limit_raw": "Tre pezzi per ritiro",
            "placement_instructions_raw": "Esporre nel giorno concordato",
            "booking_required": True,
        },
        "sources": [{
            "url": "https://example.test/ritiro",
            "publisher": "Gestore di prova",
            "retrieved_at": "2026-08-07T20:00:00+02:00",
        }],
    })


def _collection_point(
    point_id: str, name: str, latitude: float, longitude: float,
) -> CanonicalEntity:
    return CanonicalEntity("collection_point", point_id, {
        "natural_key": point_id,
        "payload": {
            "municipality_ref": "istat:053014",
            "zone_ref": None,
            "name": name,
            "point_type": "mobile",
            "accepted_streams": ["Materiali indicati nella scheda del gestore"],
            "address_raw": f"Piazza {name}",
            "location": {
                "latitude": latitude,
                "longitude": longitude,
                "method": "publisher_gis",
                "accuracy_m": None,
            },
            "access_notes_raw": "Postazione mobile",
            "access_credential": None,
            "opening_hours_raw": "Lunedi 08:00-12:00",
        },
        "sources": [{
            "url": f"https://example.test/{point_id}",
            "publisher": "Gestore di prova",
            "retrieved_at": "2026-08-07T20:00:00+02:00",
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

    def test_close_territorial_match_precedes_unavailable_exact_term(self) -> None:
        self.connection.close()
        writer = open_database(self.database, role="client")
        current = read_database_entities(writer)
        changed = dict(current)
        unavailable = _concept("waste:guscio", "Guscio dei molluschi", [])
        available = _concept(
            "waste:gusci", "Gusci di molluschi", ["Indifferenziato"],
        )
        changed[(unavailable.entity_type, unavailable.entity_id)] = unavailable
        changed[(available.entity_type, available.entity_id)] = available
        apply_package(writer, build_update_package(current, changed, 1, 2, GENERATED_AT))
        writer.close()
        self.connection = open_query_database(self.database)
        self.service = DisposalQueryService(self.connection)
        results = self.service.search(
            "Guscio dei molluschi", municipality_istat="053014",
        )
        self.assertEqual("waste:gusci", results[0]["concept_id"])

    def test_description_match_requires_the_complete_material_phrase(self) -> None:
        self.assertTrue(_description_matches_terms(
            "pneumatici fuori uso", {"pneumatico"},
        ))
        self.assertTrue(_description_matches_terms(
            "toner per stampa esauriti", {"toner"},
        ))
        self.assertFalse(_description_matches_terms(
            "legno diverso da quello contenente sostanze pericolose",
            {"mobile in legno"},
        ))

    def test_web_api_lists_municipalities_and_answers_queries(self) -> None:
        api = DisposalApi(self.database)
        municipalities = api.municipalities()
        self.assertEqual("Manciano", municipalities["municipalities"][0]["name"])
        self.assertEqual("053014", municipalities["municipalities"][0]["istat_code"])
        self.assertEqual(1, municipalities["dataset_revision"])
        results = api.search("botiglia di vtro", "053014")
        self.assertEqual("waste:bottiglia-di-vetro", results["results"][0]["concept_id"])
        answer = api.answer({
            "text": "bottiglia di vetro",
            "municipality": "053014",
            "as_of": "2026-08-07",
        })
        self.assertEqual("resolved", answer["status"])
        self.assertEqual("Vetro", answer["result"]["stream"])

    def test_web_api_rejects_incomplete_requests(self) -> None:
        api = DisposalApi(self.database)
        with self.assertRaisesRegex(ValueError, "Waste text is required"):
            api.answer({"text": "", "municipality": "053014"})
        with self.assertRaisesRegex(ValueError, "Municipality is required"):
            api.answer({"text": "vetro"})

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

    def test_another_territorys_classification_does_not_become_local(self) -> None:
        self.connection.close()
        writer = open_database(self.database, role="client")
        current = read_database_entities(writer)
        changed = dict(current)
        rope = _concept("waste:corda", "Corda", ["Indifferenziato"])
        rope.data["local_destinations"][0]["municipality_istats"] = ["048017"]
        rope.data["coverage"]["municipalities"] = ["048017"]
        rope.data["evidence"][0]["municipality_istats"] = ["048017"]
        changed[(rope.entity_type, rope.entity_id)] = rope
        apply_package(writer, build_update_package(current, changed, 1, 2, GENERATED_AT))
        writer.close()
        self.connection = open_query_database(self.database)
        self.service = DisposalQueryService(self.connection)

        answer = self.service.answer("corda", "053014")

        self.assertEqual("not_found", answer["status"])
        self.assertIsNone(answer["result"])
        self.assertEqual([], answer["provenance"]["sources"])

    def test_selected_concept_does_not_depend_on_fuzzy_search(self) -> None:
        with patch.object(
            self.service, "search", side_effect=AssertionError("search must not run"),
        ):
            answer = self.service.answer(
                "testo irrilevante",
                "053014",
                concept_id="waste:bottiglia-di-vetro",
            )
        self.assertEqual("resolved", answer["status"])
        self.assertEqual("Vetro", answer["result"]["stream"])

    def test_coverage_audit_counts_every_territorial_concept_case(self) -> None:
        report = audit_query_coverage(self.connection, generated_at=GENERATED_AT)
        self.assertEqual("pass", report["summary"]["status"])
        self.assertEqual(0, report["summary"]["failures"])
        self.assertEqual(2, report["summary"]["territorial_concept_zone_cases"])
        self.assertEqual(2, report["summary"]["total_guaranteed_cases"])
        self.assertEqual(2, report["summary"]["runtime_answer_checks"])
        self.assertEqual({"resolved": 2}, report["summary"]["runtime_answer_statuses"])

    def test_coverage_audit_rejects_unknown_territorial_municipality(self) -> None:
        self.connection.close()
        writer = open_database(self.database, role="client")
        current = read_database_entities(writer)
        changed = dict(current)
        invalid = _concept("waste:invalid", "Rifiuto invalido", ["Vetro"])
        invalid.data["local_destinations"][0]["municipality_istats"] = ["999999"]
        changed[(invalid.entity_type, invalid.entity_id)] = invalid
        apply_package(writer, build_update_package(current, changed, 1, 2, GENERATED_AT))
        writer.close()
        self.connection = open_query_database(self.database)
        report = audit_query_coverage(self.connection, generated_at=GENERATED_AT)
        self.assertEqual("fail", report["summary"]["status"])
        self.assertIn(
            "concept_unknown_municipality",
            {item["code"] for item in report["failures"]},
        )

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
        self.assertIn("struttura accessibile", " ".join(answer["result"]["warnings"]))

    def test_reviewed_object_eer_mapping_verifies_centre_acceptance(self) -> None:
        self.connection.close()
        writer = open_database(self.database, role="client")
        current = read_database_entities(writer)
        changed = dict(current)
        toaster = _concept(
            "waste:tostapane", "Tostapane", ["Centro di raccolta"],
        )
        additions = [
            toaster,
            CanonicalEntity("eer_entry", "eer:200136", {
                "entry_id": "eer:200136",
                "code": "200136",
                "title": "apparecchiature elettriche ed elettroniche fuori uso non pericolose",
                "hazardous": False,
            }),
            CanonicalEntity("waste_eer_mapping", "eer-map:small-raee", {
                "mapping_id": "eer-map:small-raee",
                "preferred_label": "RAEE non pericolosi",
                "eer_code": "200136",
                "concept_ids": ["waste:tostapane"],
                "condition": "se non contiene componenti pericolosi",
                "review_status": "approved",
                "rationale": "Corrispondenza revisionata",
                "source_urls": ["https://example.test/raee"],
            }),
            CanonicalEntity("delivery_channel", "channel:collection-centre", {
                "channel_id": "channel:collection-centre",
                "preferred_label": "Centro di raccolta",
                "destination_type": "facility",
                "aliases": ["Centro di raccolta"],
            }),
            _facility("facility:one", "Centro", 42.6, 11.5),
            _facility_access("facility:one"),
            _facility_acceptance(
                "facility:one", "RAEE non pericolosi", eer_code="200136",
            ),
        ]
        for entity in additions:
            changed[(entity.entity_type, entity.entity_id)] = entity
        apply_package(writer, build_update_package(current, changed, 1, 2, GENERATED_AT))
        writer.close()
        self.connection = open_query_database(self.database)
        self.service = DisposalQueryService(self.connection)
        answer = self.service.answer("tostapane", "053014")
        self.assertEqual("resolved", answer["status"])
        self.assertEqual("200136", answer["result"]["eer"]["code"])
        self.assertEqual("verified_eer", answer["result"]["facility"]["acceptance"]["status"])
        self.assertIn("componenti pericolosi", " ".join(answer["result"]["warnings"]))

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

    def test_accessible_facilities_require_gps_before_breaking_an_equal_tie(self) -> None:
        self.connection.close()
        writer = open_database(self.database, role="client")
        current = read_database_entities(writer)
        changed = dict(current)
        armadio = _concept(
            "waste:armadio", "Armadio", ["Ecocentro, Ritiro ingombranti"],
        )
        changed[(armadio.entity_type, armadio.entity_id)] = armadio
        for channel_id, label, destination_type, aliases in (
            (
                "channel:collection-centre", "Centro di raccolta", "facility",
                ["Centro di raccolta", "Ecocentro"],
            ),
            (
                "channel:home-pickup", "Ritiro a domicilio", "pickup",
                ["Ritiro ingombranti"],
            ),
        ):
            changed[("delivery_channel", channel_id)] = CanonicalEntity(
                "delivery_channel", channel_id, {
                    "channel_id": channel_id,
                    "preferred_label": label,
                    "destination_type": destination_type,
                    "aliases": aliases,
                },
            )
        specifications = (
            ("facility:near", "Centro vicino", 43.0000, 11.0000, "open"),
            ("facility:far", "Centro lontano", 43.2000, 11.2000, "open"),
            ("facility:closed", "Centro chiuso", 43.0001, 11.0001, "temporarily_closed"),
        )
        for facility_id, name, latitude, longitude, status in specifications:
            for entity in (
                _facility(facility_id, name, latitude, longitude, status=status),
                _facility_access(facility_id),
                _facility_acceptance(facility_id, "Ingombranti"),
                _opening_period(facility_id),
            ):
                changed[(entity.entity_type, entity.entity_id)] = entity
        apply_package(writer, build_update_package(current, changed, 1, 2, GENERATED_AT))
        writer.close()
        self.connection = open_query_database(self.database)
        self.service = DisposalQueryService(self.connection)

        without_gps = self.service.answer("armadio", "053014")
        self.assertIsNone(without_gps["result"]["facility"])
        self.assertEqual(3, len(without_gps["result"]["facility_alternatives"]))
        self.assertIn("piu centri compatibili", " ".join(without_gps["result"]["warnings"]))

        with_gps = self.service.answer(
            "armadio", "053014", latitude=43.0, longitude=11.0,
        )
        facility = with_gps["result"]["facility"]
        self.assertEqual("facility:near", facility["id"])
        self.assertEqual(0.0, facility["distance_km"])
        self.assertEqual("verified_description", facility["acceptance"]["status"])
        self.assertEqual(["Ingombranti"], facility["acceptance"]["labels"])
        self.assertEqual("Massimo due pezzi", facility["acceptance"]["conditions"][0])
        self.assertEqual("08:00", facility["opening_periods"][0]["weekly_intervals"][0]["opens"])
        self.assertEqual({"latitude": 43.0, "longitude": 11.0}, with_gps["context"]["location"])
        closed = next(
            item for item in with_gps["result"]["facility_alternatives"]
            if item["id"] == "facility:closed"
        )
        self.assertEqual("temporarily_closed", closed["operational_status"])
        self.assertGreaterEqual(len(with_gps["provenance"]["sources"]), 5)

    def test_facility_acceptance_prefers_an_exact_eer_code(self) -> None:
        self.connection.close()
        writer = open_database(self.database, role="client")
        current = read_database_entities(writer)
        changed = dict(current)
        fridge = _concept("waste:frigorifero", "Frigorifero", ["Ecocentro"])
        fridge.data["eer"] = {
            "status": "source_consensus",
            "candidates": [{
                "code": "200123",
                "source_labels": ["Apparecchiature contenenti CFC"],
                "official_title": "Apparecchiature fuori uso contenenti CFC",
                "official_hazardous": True,
            }],
        }
        changed[(fridge.entity_type, fridge.entity_id)] = fridge
        changed[("delivery_channel", "channel:collection-centre")] = CanonicalEntity(
            "delivery_channel", "channel:collection-centre", {
                "channel_id": "channel:collection-centre",
                "preferred_label": "Centro di raccolta",
                "destination_type": "facility",
                "aliases": ["Ecocentro"],
            },
        )
        for entity in (
            _facility("facility:fridge", "Centro RAEE", 43.0, 11.0),
            _facility_access("facility:fridge"),
            _facility_acceptance(
                "facility:fridge", "Apparecchiature con CFC", eer_code="200123",
            ),
        ):
            changed[(entity.entity_type, entity.entity_id)] = entity
        apply_package(writer, build_update_package(current, changed, 1, 2, GENERATED_AT))
        writer.close()
        self.connection = open_query_database(self.database)
        self.service = DisposalQueryService(self.connection)
        answer = self.service.answer("frigorifero", "053014")
        self.assertEqual("facility:fridge", answer["result"]["facility"]["id"])
        self.assertEqual("verified_eer", answer["result"]["facility"]["acceptance"]["status"])
        self.assertEqual(["200123"], answer["result"]["facility"]["acceptance"]["eer_codes"])

    def test_eer_resolves_a_centre_when_local_lookup_is_missing(self) -> None:
        self.connection.close()
        writer = open_database(self.database, role="client")
        current = read_database_entities(writer)
        changed = dict(current)
        fridge = _concept("waste:frigorifero", "Frigorifero", [])
        fridge.data["eer"] = {
            "status": "source_consensus",
            "candidates": [{
                "code": "200123",
                "source_labels": ["Apparecchiature contenenti CFC"],
                "official_title": "Apparecchiature fuori uso contenenti CFC",
                "official_hazardous": True,
                "register_status": "active_in_target",
            }],
        }
        changed[(fridge.entity_type, fridge.entity_id)] = fridge
        changed[("delivery_channel", "channel:collection-centre")] = CanonicalEntity(
            "delivery_channel", "channel:collection-centre", {
                "channel_id": "channel:collection-centre",
                "preferred_label": "Centro di raccolta",
                "destination_type": "facility",
                "aliases": ["Centro di raccolta", "Ecocentro"],
            },
        )
        for entity in (
            _facility("facility:fridge", "Centro RAEE", 43.0, 11.0),
            _facility_access("facility:fridge"),
            _facility_acceptance(
                "facility:fridge", "Apparecchiature con CFC", eer_code="200123",
            ),
        ):
            changed[(entity.entity_type, entity.entity_id)] = entity
        apply_package(writer, build_update_package(current, changed, 1, 2, GENERATED_AT))
        writer.close()
        self.connection = open_query_database(self.database)
        self.service = DisposalQueryService(self.connection)

        answer = self.service.answer("frigorifero", "053014")

        self.assertEqual("resolved", answer["status"])
        self.assertEqual("facility", answer["result"]["destination_type"])
        self.assertEqual("200123", answer["result"]["eer"]["code"])
        self.assertEqual("facility:fridge", answer["result"]["facility"]["id"])
        self.assertIn(
            "accettazione esatta del codice EER 200123",
            " ".join(answer["result"]["warnings"]),
        )

    def test_centre_description_can_supply_one_unambiguous_eer(self) -> None:
        self.connection.close()
        writer = open_database(self.database, role="client")
        current = read_database_entities(writer)
        changed = dict(current)
        toner = _concept("waste:toner", "Toner", [])
        changed[(toner.entity_type, toner.entity_id)] = toner
        changed[("eer_entry", "eer:080318")] = CanonicalEntity(
            "eer_entry", "eer:080318", {
                "entry_id": "eer:080318",
                "code": "080318",
                "title": "toner per stampa esauriti",
                "title_expanded": "toner per stampa esauriti, diversi da quelli pericolosi",
                "hazardous": False,
                "chapter_ref": "eer-chapter:08",
                "subchapter_ref": "eer-subchapter:0803",
                "references": [],
                "source_celex": "02000D0532-20231206",
            },
        )
        changed[("delivery_channel", "channel:collection-centre")] = CanonicalEntity(
            "delivery_channel", "channel:collection-centre", {
                "channel_id": "channel:collection-centre",
                "preferred_label": "Centro di raccolta",
                "destination_type": "facility",
                "aliases": ["Centro di raccolta"],
            },
        )
        for entity in (
            _facility("facility:toner", "Centro toner", 43.0, 11.0),
            _facility_access("facility:toner"),
            _facility_acceptance(
                "facility:toner", "Toner per stampa esauriti", eer_code="080318",
            ),
        ):
            changed[(entity.entity_type, entity.entity_id)] = entity
        apply_package(writer, build_update_package(current, changed, 1, 2, GENERATED_AT))
        writer.close()
        self.connection = open_query_database(self.database)
        self.service = DisposalQueryService(self.connection)

        answer = self.service.answer("toner", "053014")

        self.assertEqual("resolved", answer["status"])
        self.assertEqual("080318", answer["result"]["eer"]["code"])
        self.assertEqual(
            "verified_description",
            answer["result"]["facility"]["acceptance"]["status"],
        )
        self.assertIn(
            "descrizione del materiale",
            " ".join(answer["result"]["warnings"]),
        )

    def test_pickup_channel_exposes_booking_and_limits(self) -> None:
        self.connection.close()
        writer = open_database(self.database, role="client")
        current = read_database_entities(writer)
        changed = dict(current)
        armadio = _concept("waste:armadio", "Armadio", ["Ritiro ingombranti"])
        changed[(armadio.entity_type, armadio.entity_id)] = armadio
        changed[("delivery_channel", "channel:home-pickup")] = CanonicalEntity(
            "delivery_channel", "channel:home-pickup", {
                "channel_id": "channel:home-pickup",
                "preferred_label": "Ritiro a domicilio",
                "destination_type": "pickup",
                "aliases": ["Ritiro ingombranti"],
            },
        )
        pickup = _pickup_service()
        changed[(pickup.entity_type, pickup.entity_id)] = pickup
        apply_package(writer, build_update_package(current, changed, 1, 2, GENERATED_AT))
        writer.close()
        self.connection = open_query_database(self.database)
        self.service = DisposalQueryService(self.connection)
        answer = self.service.answer("armadio", "053014")
        service = answer["result"]["channel_services"][0]
        self.assertEqual("pickup", service["service_type"])
        self.assertEqual("verified_description", service["compatibility"])
        self.assertTrue(service["booking_required"])
        self.assertEqual("phone", service["booking_methods"][0]["method"])
        self.assertEqual(3, service["max_items"])
        self.assertEqual("Tre pezzi per ritiro", service["quantity_limit"])
        self.assertEqual([], answer["result"]["unresolved_channels"])

    def test_mobile_points_are_sorted_by_gps_without_inventing_acceptance(self) -> None:
        self.connection.close()
        writer = open_database(self.database, role="client")
        current = read_database_entities(writer)
        changed = dict(current)
        accessory = _concept(
            "waste:accessori-cellulari", "Accessori cellulari", ["Ecofurgone"],
        )
        changed[(accessory.entity_type, accessory.entity_id)] = accessory
        changed[("delivery_channel", "channel:mobile-collection")] = CanonicalEntity(
            "delivery_channel", "channel:mobile-collection", {
                "channel_id": "channel:mobile-collection",
                "preferred_label": "Servizio mobile",
                "destination_type": "collection_point",
                "aliases": ["Ecofurgone"],
            },
        )
        for point in (
            _collection_point("point:far", "Lontana", 43.2, 11.2),
            _collection_point("point:near", "Vicina", 43.0, 11.0),
        ):
            changed[(point.entity_type, point.entity_id)] = point
        apply_package(writer, build_update_package(current, changed, 1, 2, GENERATED_AT))
        writer.close()
        self.connection = open_query_database(self.database)
        self.service = DisposalQueryService(self.connection)
        answer = self.service.answer(
            "accessori cellulari", "053014", latitude=43.0, longitude=11.0,
        )
        services = answer["result"]["channel_services"]
        self.assertEqual(["point:near", "point:far"], [item["id"] for item in services])
        self.assertEqual(0.0, services[0]["distance_km"])
        self.assertEqual("acceptance_not_published", services[0]["compatibility"])
        self.assertEqual("Lunedi 08:00-12:00", services[0]["schedule_raw"])
        self.assertEqual(
            "acceptance_not_published",
            answer["result"]["unresolved_channels"][0]["status"],
        )
        self.assertIn("elenco dei rifiuti accettati", " ".join(answer["result"]["warnings"]))

    def test_source_only_channel_remains_explicitly_unresolved(self) -> None:
        self.connection.close()
        writer = open_database(self.database, role="client")
        current = read_database_entities(writer)
        changed = dict(current)
        phone = _concept(
            "waste:telefono-usato", "Telefono usato", ["Riuso cambia il finale"],
        )
        changed[(phone.entity_type, phone.entity_id)] = phone
        changed[("delivery_channel", "channel:reuse-service")] = CanonicalEntity(
            "delivery_channel", "channel:reuse-service", {
                "channel_id": "channel:reuse-service",
                "preferred_label": "Servizio di riuso",
                "destination_type": "special_case",
                "aliases": ["Riuso cambia il finale"],
            },
        )
        apply_package(writer, build_update_package(current, changed, 1, 2, GENERATED_AT))
        writer.close()
        self.connection = open_query_database(self.database)
        self.service = DisposalQueryService(self.connection)
        answer = self.service.answer("telefono usato", "053014")
        self.assertEqual([], answer["result"]["channel_services"])
        unresolved = answer["result"]["unresolved_channels"][0]
        self.assertEqual("channel:reuse-service", unresolved["channel_id"])
        self.assertEqual("source_only", unresolved["status"])
        self.assertEqual("Riuso cambia il finale", unresolved["source_destination"])

    def test_location_coordinates_must_be_complete_and_valid(self) -> None:
        with self.assertRaisesRegex(ValueError, "provided together"):
            self.service.answer("bottiglia", "053014", latitude=43.0)
        with self.assertRaisesRegex(ValueError, "Latitude"):
            self.service.answer(
                "bottiglia", "053014", latitude=100.0, longitude=11.0,
            )


if __name__ == "__main__":
    unittest.main()
