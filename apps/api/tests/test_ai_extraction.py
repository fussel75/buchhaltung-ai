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
