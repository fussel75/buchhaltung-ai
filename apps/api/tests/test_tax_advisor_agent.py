from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.services import tax_advisor_agent


class TaxAdvisorAgentTests(TestCase):
    def test_disabled_agent_returns_original_extraction(self):
        extraction = {"supplier_name": "Unklar", "confidence": Decimal("0.42"), "warnings": []}
        settings = SimpleNamespace(ai_extraction_enabled=False, ai_extraction_api_key=None)

        with patch.object(tax_advisor_agent, "get_settings", return_value=settings):
            result = tax_advisor_agent.run_tax_advisor_agent(
                document={"tenant_id": "demo-mandant", "original_filename": "rechnung.pdf"},
                extraction=extraction,
                pdf_text="Rechnung",
            )

        self.assertIs(result, extraction)

    def test_agent_attaches_trace_and_field_changes(self):
        extraction = {
            "supplier_name": "4242270364",
            "invoice_number": "231-100",
            "invoice_date": None,
            "confidence": Decimal("0.72"),
            "warnings": ["Nicht sicher erkannt: Lieferant, Datum."],
            "raw_result": {
                "document_type": "incoming_invoice",
                "assignment_type": "general_cost",
                "assignment_code": "Allgemeine Kosten",
            },
        }
        ai_result = {
            **extraction,
            "supplier_name": "Linde GmbH, Gases Division",
            "invoice_date": "2026-07-23",
            "raw_result": {
                **extraction["raw_result"],
                "supplier_name": "Linde GmbH, Gases Division",
                "invoice_date": "2026-07-23",
                "ai_extraction": {
                    "status": "applied",
                    "model": "moonshotai/kimi-k3",
                    "used_vision": True,
                    "accepted_fields": ["supplier_name", "invoice_date"],
                },
            },
        }
        settings = SimpleNamespace(ai_extraction_enabled=True, ai_extraction_api_key="secret")

        with (
            patch.object(tax_advisor_agent, "get_settings", return_value=settings),
            patch.object(tax_advisor_agent, "maybe_enhance_extraction_with_ai", return_value=ai_result),
        ):
            result = tax_advisor_agent.run_tax_advisor_agent(
                document={
                    "id": "doc-1",
                    "tenant_id": "demo-mandant",
                    "original_filename": "4242270364.PDF",
                    "content_type": "application/pdf",
                },
                extraction=extraction,
                pdf_text="Linde GmbH Rechnungsdatum 23.07.2026",
                pdf_images=["data:image/png;base64,AAA"],
                force=True,
            )

        trace = result["raw_result"]["tax_advisor_agent"]
        self.assertEqual(trace["version"], "steuerberater-agent-v1")
        self.assertEqual(trace["status"], "applied")
        self.assertEqual(trace["model"], "moonshotai/kimi-k3")
        self.assertTrue(trace["used_vision"])
        self.assertIn("supplier_name", trace["field_changes"])
        self.assertIn("invoice_date", trace["field_changes"])
        self.assertEqual(trace["context"]["input"]["vision_pages"], 1)
        self.assertIn("classify_document_type", trace["context"]["workflow"])
