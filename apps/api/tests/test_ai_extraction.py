import json
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.services import ai_extraction


class AiExtractionTests(TestCase):
    def test_disabled_ai_extraction_returns_original_result(self):
        extraction = {"supplier_name": "Unklar", "confidence": Decimal("0.42"), "warnings": []}

        with patch.object(
            ai_extraction,
            "get_settings",
            return_value=SimpleNamespace(ai_extraction_enabled=False, ai_extraction_api_key=None),
        ):
            result = ai_extraction.maybe_enhance_extraction_with_ai(
                document={"tenant_id": "demo-mandant", "original_filename": "test.pdf"},
                extraction=extraction,
                pdf_text="Rechnung",
            )

        self.assertIs(result, extraction)

    def test_ai_extraction_fills_missing_invoice_and_assignment_fields(self):
        extraction = {
            "supplier_name": "1RECHNUNGAR095410",
            "invoice_number": None,
            "invoice_date": "2026-05-31",
            "net_amount": Decimal("79.99"),
            "tax_amount": Decimal("15.20"),
            "gross_amount": Decimal("95.19"),
            "currency": "EUR",
            "confidence": Decimal("0.72"),
            "warnings": ["Nicht sicher erkannt: Rechnungsnummer."],
            "source": "pdf_text_rules",
            "assignment_type": "assignment_unresolved",
        }
        assignment = {
            "code": "Buwg4",
            "label": "Buwg4",
            "kind": "construction_project",
            "project_number": "25-00009",
            "address_line": "Bucheckerweg 4",
            "postal_code": "22175",
            "city": "Hamburg",
            "is_active": True,
            "aliases": ["Buchecker Weg 4"],
        }
        ai_payload = {
            "supplier_name": "Georg Klindworth oHG",
            "invoice_number": "866205-605",
            "customer_number": "0113042/504",
            "document_type": "incoming_invoice",
            "cost_category": "material",
            "assignment_code": "Buwg4",
            "project_number": "25-00009",
            "item_summary": "Hapatec Edelstahl gehärtet",
            "confidence": "0.94",
            "evidence": ["Kom: Buchecker Weg 4", "Nummer (BD): 866205-605"],
            "warnings": [],
        }

        settings = SimpleNamespace(
            ai_extraction_enabled=True,
            ai_extraction_api_key="secret",
            ai_extraction_model="test-model",
            ai_extraction_min_confidence=0.90,
        )
        with (
            patch.object(ai_extraction, "get_settings", return_value=settings),
            patch.object(ai_extraction, "list_assignment_units", return_value=[assignment]),
            patch.object(ai_extraction, "_call_ai_extractor", return_value=ai_payload),
        ):
            result = ai_extraction.maybe_enhance_extraction_with_ai(
                document={"tenant_id": "demo-mandant", "original_filename": "test.pdf"},
                extraction=extraction,
                pdf_text="Kom:Buchecker Weg 4 Nummer (BD): 866205-605",
            )

        self.assertEqual(result["supplier_name"], "Georg Klindworth oHG")
        self.assertEqual(result["invoice_number"], "866205-605")
        self.assertEqual(result["confidence"], Decimal("0.94"))
        self.assertEqual(result["raw_result"]["customer_number"], "0113042/504")
        self.assertEqual(result["raw_result"]["assignment_code"], "Buwg4")
        self.assertEqual(result["raw_result"]["project_number"], "25-00009")
        self.assertEqual(result["raw_result"]["assignment_kind"], "construction_project")
        self.assertEqual(result["raw_result"]["ai_extraction"]["status"], "applied")
        self.assertIn("invoice_number", result["raw_result"]["ai_extraction"]["accepted_fields"])

    def test_ai_provider_failure_keeps_rule_result_with_warning(self):
        extraction = {
            "supplier_name": "Unklar",
            "invoice_number": None,
            "confidence": Decimal("0.42"),
            "warnings": [],
            "source": "pdf_text_rules",
        }
        settings = SimpleNamespace(
            ai_extraction_enabled=True,
            ai_extraction_api_key="secret",
            ai_extraction_model="test-model",
            ai_extraction_min_confidence=0.90,
        )

        with (
            patch.object(ai_extraction, "get_settings", return_value=settings),
            patch.object(ai_extraction, "list_assignment_units", return_value=[]),
            patch.object(ai_extraction, "_call_ai_extractor", side_effect=RuntimeError("timeout")),
        ):
            result = ai_extraction.maybe_enhance_extraction_with_ai(
                document={"tenant_id": "demo-mandant", "original_filename": "test.pdf"},
                extraction=extraction,
                pdf_text="",
            )

        self.assertEqual(result["supplier_name"], "Unklar")
        self.assertIn("KI-Extraktion nicht verfügbar: timeout.", result["warnings"])
        self.assertEqual(result["raw_result"]["ai_extraction"]["status"], "failed")

    def test_force_runs_ai_even_for_high_confidence_extraction(self):
        extraction = {
            "supplier_name": "Theo Foerch GmbH & Co. KG",
            "invoice_number": "3161691971",
            "invoice_date": "2026-05-21",
            "gross_amount": Decimal("8.77"),
            "confidence": Decimal("0.99"),
            "warnings": [],
            "raw_result": {
                "supplier_name": "Theo Foerch GmbH & Co. KG",
                "invoice_number": "3161691971",
                "invoice_date": "2026-05-21",
                "gross_amount": Decimal("8.77"),
                "source": "pdf_text_rules",
                "assignment_type": "assigned",
            },
        }
        ai_payload = {
            "customer_number": "425590",
            "confidence": "0.93",
            "evidence": ["Kundennummer 425590"],
            "warnings": [],
        }
        settings = SimpleNamespace(
            ai_extraction_enabled=True,
            ai_extraction_api_key="secret",
            ai_extraction_model="test-model",
            ai_extraction_min_confidence=0.90,
        )

        with (
            patch.object(ai_extraction, "get_settings", return_value=settings),
            patch.object(ai_extraction, "list_assignment_units", return_value=[]),
            patch.object(ai_extraction, "_call_ai_extractor", return_value=ai_payload) as mocked_call,
        ):
            result = ai_extraction.maybe_enhance_extraction_with_ai(
                document={"tenant_id": "demo-mandant", "original_filename": "test.pdf"},
                extraction=extraction,
                pdf_text="Kundennummer 425590",
                force=True,
            )

        mocked_call.assert_called_once()
        self.assertEqual(result["raw_result"]["customer_number"], "425590")
        self.assertEqual(result["raw_result"]["ai_extraction"]["status"], "applied")

    def test_ai_extraction_uses_vision_model_when_images_are_supplied(self):
        extraction = {
            "supplier_name": "Tankstelle",
            "gross_amount": None,
            "confidence": Decimal("0.62"),
            "warnings": [],
            "raw_result": {"document_type": "fuel_receipt"},
        }
        ai_payload = {
            "gross_amount": "56.00",
            "net_amount": "47.06",
            "tax_amount": "8.94",
            "confidence": "0.95",
            "evidence": ["Summe 56,00 EUR"],
            "warnings": [],
        }
        settings = SimpleNamespace(
            ai_extraction_enabled=True,
            ai_extraction_api_key="secret",
            ai_extraction_model="text-model",
            ai_extraction_vision_model="vision-model",
            ai_extraction_min_confidence=0.90,
        )

        with (
            patch.object(ai_extraction, "get_settings", return_value=settings),
            patch.object(ai_extraction, "list_assignment_units", return_value=[]),
            patch.object(ai_extraction, "_call_ai_extractor", return_value=ai_payload) as mocked_call,
        ):
            result = ai_extraction.maybe_enhance_extraction_with_ai(
                document={"tenant_id": "demo-mandant", "original_filename": "tank.pdf"},
                extraction=extraction,
                pdf_text="OCR Text",
                pdf_images=["data:image/png;base64,AAA"],
                force=True,
            )

        self.assertEqual(mocked_call.call_args.kwargs["model"], "vision-model")
        self.assertEqual(mocked_call.call_args.kwargs["pdf_images"], ["data:image/png;base64,AAA"])
        self.assertEqual(result["gross_amount"], Decimal("56.00"))
        self.assertTrue(result["raw_result"]["ai_extraction"]["used_vision"])

    def test_ai_assignment_resolves_partial_project_reference_to_masterdata(self):
        extraction = {
            "supplier_name": "773934 606",
            "invoice_number": "773934 606",
            "invoice_date": "2026-06-12",
            "gross_amount": Decimal("361.19"),
            "confidence": Decimal("0.42"),
            "warnings": ["Zuordnung ungeklärt."],
            "source": "pdf_text_rules",
            "assignment_type": "assignment_unresolved",
        }
        assignment = {
            "code": "Neula51",
            "label": "Neusurenland 51",
            "kind": "construction_project",
            "project_number": "26-00003",
            "address_line": "Neusurenland 51",
            "postal_code": "22159",
            "city": "Hamburg",
            "client_name": "Ilja Badekow",
            "description": "Umbau, Anbau, Wärmepumpe, Sanitär",
            "is_active": True,
            "aliases": [],
        }
        ai_payload = {
            "supplier_name": "Hansa Holz GmbH",
            "invoice_number": "26/007898",
            "customer_number": "43535",
            "document_type": "incoming_invoice",
            "cost_category": "material",
            "assignment_code": "Neusurenland Bangkirai",
            "item_summary": "Bangkirai Konstruktionsholz",
            "confidence": "0.93",
            "evidence": ["BV: Neusurenland Bangkirai"],
            "warnings": [],
        }
        settings = SimpleNamespace(
            ai_extraction_enabled=True,
            ai_extraction_api_key="secret",
            ai_extraction_model="test-model",
            ai_extraction_min_confidence=0.90,
        )

        with (
            patch.object(ai_extraction, "get_settings", return_value=settings),
            patch.object(ai_extraction, "list_assignment_units", return_value=[assignment]),
            patch.object(ai_extraction, "_call_ai_extractor", return_value=ai_payload),
        ):
            result = ai_extraction.maybe_enhance_extraction_with_ai(
                document={"tenant_id": "demo-mandant", "original_filename": "773934-606.pdf"},
                extraction=extraction,
                pdf_text="BV: Neusurenland Bangkirai",
            )

        self.assertEqual(result["supplier_name"], "Hansa Holz GmbH")
        self.assertEqual(result["raw_result"]["assignment_code"], "Neula51")
        self.assertEqual(result["raw_result"]["project_number"], "26-00003")
        self.assertEqual(result["raw_result"]["assignment_kind"], "construction_project")

    def test_ai_assignment_does_not_guess_ambiguous_partial_reference(self):
        assignment_a = {
            "code": "Ekkp58",
            "label": "Eckerkamp 58",
            "kind": "construction_project",
            "project_number": "25-00007",
            "address_line": "Eckerkamp 58",
            "city": "Hamburg",
            "is_active": True,
            "aliases": [],
        }
        assignment_b = {
            "code": "Ekkp66",
            "label": "Eckerkamp 66",
            "kind": "construction_project",
            "project_number": "25-00012",
            "address_line": "Eckerkamp 66",
            "city": "Hamburg",
            "is_active": True,
            "aliases": [],
        }

        result = ai_extraction._resolve_assignment(
            {"assignment_code": "Eckerkamp", "project_number": None},
            [assignment_a, assignment_b],
        )

        self.assertIsNone(result)

    def test_ai_prompt_includes_completed_projects_for_late_invoices(self):
        prompt = ai_extraction._user_prompt(
            document={"original_filename": "rechnung.pdf", "content_type": "application/pdf", "size_bytes": 1234},
            extraction={"supplier_name": "Lieferant", "confidence": Decimal("0.50")},
            pdf_text="Kommission Eckerkamp 58",
            assignment_units=[
                {
                    "code": "Ekkp58",
                    "label": "Eckerkamp 58",
                    "kind": "construction_project",
                    "project_number": "25-00007",
                    "address_line": "Eckerkamp 58",
                    "postal_code": "22391",
                    "city": "Hamburg",
                    "is_active": False,
                    "source_status": "Abgeschlossen",
                    "aliases": [],
                }
            ],
        )

        self.assertIn('"code": "Ekkp58"', prompt)
        self.assertIn('"is_active": false', prompt)
        self.assertIn('"status": "Abgeschlossen"', prompt)

    def test_ai_prompt_prioritizes_relevant_project_masterdata(self):
        assignments = [
            {
                "code": f"Unrel{i}",
                "label": f"Unrelevantes Projekt {i}",
                "kind": "construction_project",
                "project_number": f"26-9{i:04d}",
                "address_line": f"Unbekannte Strasse {i}",
                "city": "Hamburg",
                "is_active": True,
                "aliases": [],
            }
            for i in range(60)
        ]
        assignments.append(
            {
                "code": "Neula51",
                "label": "Neusurenland 51",
                "kind": "construction_project",
                "project_number": "26-00003",
                "address_line": "Neusurenland 51",
                "city": "Hamburg",
                "is_active": True,
                "aliases": ["Neusurenland Bangkirai"],
            }
        )

        prompt = ai_extraction._user_prompt(
            document={"original_filename": "hansa-holz.pdf", "content_type": "application/pdf", "size_bytes": 1234},
            extraction={"supplier_name": "Hansa Holz GmbH", "confidence": Decimal("0.50")},
            pdf_text="BV: Neusurenland Bangkirai",
            assignment_units=assignments,
        )
        payload = json.loads(prompt)

        self.assertEqual(payload["project_masterdata_total"], 61)
        self.assertLessEqual(payload["project_masterdata_count"], 35)
        self.assertEqual(payload["project_masterdata"][0]["code"], "Neula51")
